{#- Fold German text for comparison: lowercase, umlauts to base vowel, ß to ss. -#}
{% macro norm(col) -%}
    lower(replace(translate({{ col }}, 'äöüÄÖÜ', 'aouAOU'), 'ß', 'ss'))
{%- endmacro %}
