{#
    Per-platform SQL differences (Postgres, Databricks) live here so the models stay single-source.
    Each macro must behave the same on both, and raises on an unknown adapter.
#}


{#
    Text value from a JSON payload. Path is a key or a list of keys/indexes:
        {{ json_text('payload', 'firma') }}
        {{ json_text('payload', ['stellenlokationen', 0, 'adresse', 'ort']) }}
    NULL for a missing key; scalars come back unquoted.
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


{# Length of a JSON array, NULL when the key is absent. #}
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


{# Case-sensitive regex match (find anywhere). #}
{% macro match(column, pattern) -%}
    {%- if target.type == 'postgres' -%}
        {{ column }} ~ '{{ pattern }}'
    {%- elif target.type == 'databricks' -%}
        {{ column }} rlike '{{ pattern }}'
    {%- else -%}
        {{ exceptions.raise_compiler_error("match has no implementation for target type '" ~ target.type ~ "'") }}
    {%- endif -%}
{%- endmacro %}


{# Case-insensitive regex match. #}
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
    Case-insensitive match with word boundaries ('sql' must not match 'postgresql').
    Postgres \m/\M vs Java \b: equal only for patterns that start and end on a word character.
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
    Word-boundary match where the pattern is a SQL expression (e.g. a column).
    ignore_case defaults to false; most callers compare norm()'d text.
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
    Match against a pattern built in SQL, no boundaries added (for anchors).
    Build it with concat() and avoid backslashes; the platforms escape them differently.
#}
{% macro match_expr(column, pattern_sql) -%}
    {%- if target.type == 'postgres' -%}
        {{ column }} ~ ({{ pattern_sql }})
    {%- elif target.type == 'databricks' -%}
        {{ column }} rlike ({{ pattern_sql }})
    {%- else -%}
        {{ exceptions.raise_compiler_error("match_expr has no implementation for target type '" ~ target.type ~ "'") }}
    {%- endif -%}
{%- endmacro %}


{# End-of-word boundary for use inside a literal pattern. #}
{% macro word_end() -%}
    {%- if target.type == 'postgres' -%}\M
    {%- elif target.type == 'databricks' -%}\\b
    {%- else -%}
        {{ exceptions.raise_compiler_error("word_end has no implementation for target type '" ~ target.type ~ "'") }}
    {%- endif -%}
{%- endmacro %}


{# Unix epoch seconds (as text) to a date. #}
{% macro epoch_to_date(expression) -%}
    {%- if target.type == 'postgres' -%}
        to_timestamp(cast({{ expression }} as bigint))::date
    {%- elif target.type == 'databricks' -%}
        cast(from_unixtime(cast({{ expression }} as bigint)) as date)
    {%- else -%}
        {{ exceptions.raise_compiler_error("epoch_to_date has no implementation for target type '" ~ target.type ~ "'") }}
    {%- endif -%}
{%- endmacro %}


{# Salary type: annual euro figures, numeric(12, 2) on both platforms. #}
{% macro type_money() -%}
    {%- if target.type == 'postgres' -%}
        numeric(12, 2)
    {%- elif target.type == 'databricks' -%}
        decimal(12, 2)
    {%- else -%}
        {{ exceptions.raise_compiler_error("type_money has no implementation for target type '" ~ target.type ~ "'") }}
    {%- endif -%}
{%- endmacro %}


{# Timestamp without timezone (timestamp_ntz on Databricks); the source gives local time. #}
{% macro type_timestamp() -%}
    {%- if target.type == 'postgres' -%}
        timestamp
    {%- elif target.type == 'databricks' -%}
        timestamp_ntz
    {%- else -%}
        {{ exceptions.raise_compiler_error("type_timestamp has no implementation for target type '" ~ target.type ~ "'") }}
    {%- endif -%}
{%- endmacro %}


{# Whole days between two dates, `later - earlier`. #}
{% macro days_between(later, earlier) -%}
    {%- if target.type == 'postgres' -%}
        ({{ later }} - {{ earlier }})
    {%- elif target.type == 'databricks' -%}
        datediff({{ later }}, {{ earlier }})
    {%- else -%}
        {{ exceptions.raise_compiler_error("days_between has no implementation for target type '" ~ target.type ~ "'") }}
    {%- endif -%}
{%- endmacro %}
