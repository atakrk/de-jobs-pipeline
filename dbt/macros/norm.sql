{#-
  Fold German text to a comparable form: lowercase, umlauts to their base
  vowel, eszett to ss. "Düsseldorf" and "Dusseldorf" are the same place and
  a job board will spell it either way.
-#}
{% macro norm(col) -%}
    lower(replace(translate({{ col }}, 'äöüÄÖÜ', 'aouAOU'), 'ß', 'ss'))
{%- endmacro %}
