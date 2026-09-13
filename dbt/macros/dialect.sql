{#
    Cross-database dialect helpers.

    This project runs on Postgres locally and on Databricks in the cloud. The
    two platforms disagree about three things the models depend on: how JSON
    is read, how a case-insensitive regex is written, and how a word boundary
    is spelt. The obvious answer -- a second copy of the models -- means every
    future change has to be made twice, and the two copies drift. Drift is the
    failure mode this project keeps finding, so the disagreements live here
    instead and the models stay single-source.

    Two rules for anything added here:

      1. It must behave identically on both platforms, not merely compile on
         both. A macro that emits valid SQL with different semantics is worse
         than no macro, because nothing will fail.
      2. An unknown adapter raises rather than falling through to a default.
         A silent Postgres fallback on a third platform would produce a
         plausible-looking build that is wrong.
#}


{#
    Read a text value out of a JSON payload.

    Path is a single key, or a list of keys and array indexes:

        {{ json_text('payload', 'firma') }}
          postgres:   payload ->> 'firma'
          databricks: get_json_object(payload, '$.firma')

        {{ json_text('payload', ['stellenlokationen', 0, 'adresse', 'ort']) }}
          postgres:   payload -> 'stellenlokationen' -> 0 -> 'adresse' ->> 'ort'
          databricks: get_json_object(payload, '$.stellenlokationen[0].adresse.ort')

    Both return NULL for a missing key, and both return the scalar unquoted --
    Postgres because the last step uses ->> rather than ->, Databricks because
    get_json_object strips the quotes from a JSON string.
#}
{% macro json_text(column, path) -%}
    {%- set segments = [path] if path is string else path -%}
    {%- if target.type == 'postgres' -%}
        {{ column }}
        {%- for seg in segments -%}
            {{- ' ->> ' if loop.last else ' -> ' -}}
            {{- "'" ~ seg ~ "'" if seg is string else seg -}}
        {%- endfor -%}
    {%- elif target.type == 'databricks' -%}
        get_json_object({{ column }}, '{{ json_path(segments) }}')
    {%- else -%}
        {{ exceptions.raise_compiler_error("json_text has no implementation for target type '" ~ target.type ~ "'") }}
    {%- endif -%}
{%- endmacro %}


{#
    Length of a JSON array, or NULL when the key is absent.

    Postgres jsonb_array_length and Databricks json_array_length agree on both
    the answer and the null behaviour, so only the extraction differs.
#}
{% macro json_array_len(column, path) -%}
    {%- set segments = [path] if path is string else path -%}
    {%- if target.type == 'postgres' -%}
        jsonb_array_length({{ column }}
        {%- for seg in segments -%}
            {{- ' -> ' -}}{{- "'" ~ seg ~ "'" if seg is string else seg -}}
        {%- endfor -%})
    {%- elif target.type == 'databricks' -%}
        json_array_length(get_json_object({{ column }}, '{{ json_path(segments) }}'))
    {%- else -%}
        {{ exceptions.raise_compiler_error("json_array_len has no implementation for target type '" ~ target.type ~ "'") }}
    {%- endif -%}
{%- endmacro %}


{# JSONPath string for the Databricks branches above. Internal. #}
{% macro json_path(segments) -%}
    ${%- for seg in segments -%}
        {{- '[' ~ seg ~ ']' if seg is not string else '.' ~ seg -}}
    {%- endfor -%}
{%- endmacro %}


{#
    Case-sensitive regex match. Postgres ~ and Databricks rlike are both
    "find anywhere in the string", so anchors and quantifiers carry over
    unchanged; only word boundaries differ, and those have their own macros.
#}
{% macro match(column, pattern) -%}
    {%- if target.type == 'postgres' -%}
        {{ column }} ~ '{{ pattern }}'
    {%- elif target.type == 'databricks' -%}
        {{ column }} rlike '{{ pattern }}'
    {%- else -%}
        {{ exceptions.raise_compiler_error("match has no implementation for target type '" ~ target.type ~ "'") }}
    {%- endif -%}
{%- endmacro %}


{#
    Case-insensitive regex match. Postgres has a dedicated operator;
    Databricks has none, so the flag goes inside the pattern.
#}
{% macro imatch(column, pattern) -%}
    {%- if target.type == 'postgres' -%}
        {{ column }} ~* '{{ pattern }}'
    {%- elif target.type == 'databricks' -%}
        {{ column }} rlike '(?i){{ pattern }}'
    {%- else -%}
        {{ exceptions.raise_compiler_error("imatch has no implementation for target type '" ~ target.type ~ "'") }}
    {%- endif -%}
{%- endmacro %}


{#
    Case-insensitive match wrapped in word boundaries, which is what keeps
    'sql' out of 'postgresql' and 'r' out of every German word on the page.

    Postgres uses POSIX \m (start of word) and \M (end of word); Java, which
    is what Databricks compiles to, has only the symmetric \b. They agree on
    every pattern in this project, all of which start and end on a word
    character. A pattern starting or ending with punctuation would not be
    equivalent, and does not belong here.
#}
{% macro imatch_word(column, pattern) -%}
    {%- if target.type == 'postgres' -%}
        {{ column }} ~* '\m({{ pattern }})\M'
    {%- elif target.type == 'databricks' -%}
        {{ column }} rlike '(?i)\\b({{ pattern }})\\b'
    {%- else -%}
        {{ exceptions.raise_compiler_error("imatch_word has no implementation for target type '" ~ target.type ~ "'") }}
    {%- endif -%}
{%- endmacro %}


{#
    Same, but the pattern is a SQL expression rather than a literal -- a
    column, typically, when the patterns are themselves rows in a table.

    ignore_case defaults to false because two of the three callers compare
    text that both sides have already put through norm(). It has to be
    explicit either way: a case-sensitive match against raw posting text
    would silently return fewer rows rather than fail.
#}
{% macro match_word_expr(column, pattern_sql, ignore_case=false) -%}
    {%- if target.type == 'postgres' -%}
        {{ column }} {{ '~*' if ignore_case else '~' }} ('\m' || {{ pattern_sql }} || '\M')
    {%- elif target.type == 'databricks' -%}
        {{ column }} rlike concat('{{ '(?i)' if ignore_case else '' }}\\b', {{ pattern_sql }}, '\\b')
    {%- else -%}
        {{ exceptions.raise_compiler_error("match_word_expr has no implementation for target type '" ~ target.type ~ "'") }}
    {%- endif -%}
{%- endmacro %}


{#
    End-of-word boundary, for embedding inside a literal pattern where only
    one alternative needs bounding. 'bi' must not match inside 'bild', but
    'data' is deliberately allowed to match inside 'database'.
#}
{% macro word_end() -%}
    {%- if target.type == 'postgres' -%}\M
    {%- elif target.type == 'databricks' -%}\\b
    {%- else -%}
        {{ exceptions.raise_compiler_error("word_end has no implementation for target type '" ~ target.type ~ "'") }}
    {%- endif -%}
{%- endmacro %}


{#
    Unix epoch seconds (as text) to a date.
#}
{% macro epoch_to_date(expression) -%}
    {%- if target.type == 'postgres' -%}
        to_timestamp(cast({{ expression }} as bigint))::date
    {%- elif target.type == 'databricks' -%}
        cast(from_unixtime(cast({{ expression }} as bigint)) as date)
    {%- else -%}
        {{ exceptions.raise_compiler_error("epoch_to_date has no implementation for target type '" ~ target.type ~ "'") }}
    {%- endif -%}
{%- endmacro %}


{#
    Advertised salary.

    Postgres will accept a bare `numeric` and store anything; Spark will not,
    and a scale has to be chosen somewhere. Choosing it here rather than
    letting each platform default keeps the two builds comparable, and pins
    the choice next to the reason: these are annual euro figures, so twelve
    digits with two decimals is more headroom than any real posting needs and
    an implausible value fails loudly instead of being stored.
#}
{% macro type_money() -%}
    {%- if target.type == 'postgres' -%}
        numeric(12, 2)
    {%- elif target.type == 'databricks' -%}
        decimal(12, 2)
    {%- else -%}
        {{ exceptions.raise_compiler_error("type_money has no implementation for target type '" ~ target.type ~ "'") }}
    {%- endif -%}
{%- endmacro %}


{#
    A timestamp with no timezone attached.

    Postgres `timestamp` is a wall-clock reading. Spark's `TIMESTAMP` is an
    instant interpreted through the session timezone, so the same cast returns
    a value that shifts with a session setting the source never mentioned --
    the federal API states a local time and no offset. `TIMESTAMP_NTZ` is the
    type that means what Postgres means, and pinning it keeps the two builds
    comparable rather than coincidentally equal in UTC.
#}
{% macro type_timestamp() -%}
    {%- if target.type == 'postgres' -%}
        timestamp
    {%- elif target.type == 'databricks' -%}
        timestamp_ntz
    {%- else -%}
        {{ exceptions.raise_compiler_error("type_timestamp has no implementation for target type '" ~ target.type ~ "'") }}
    {%- endif -%}
{%- endmacro %}


{#
    Whole days between two dates, as `later - earlier`.

    Postgres subtracts dates directly and returns an integer; Spark rejects the
    operator and wants datediff. Used by the freshness window, where getting
    the sign or the unit wrong silently changes how many postings are counted
    rather than failing.
#}
{% macro days_between(later, earlier) -%}
    {%- if target.type == 'postgres' -%}
        ({{ later }} - {{ earlier }})
    {%- elif target.type == 'databricks' -%}
        datediff({{ later }}, {{ earlier }})
    {%- else -%}
        {{ exceptions.raise_compiler_error("days_between has no implementation for target type '" ~ target.type ~ "'") }}
    {%- endif -%}
{%- endmacro %}
