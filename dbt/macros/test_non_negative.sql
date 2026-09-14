{#
    A count that has gone negative.

    dbt ships no range test and dbt_utils is not a dependency this project
    wants for four lines. Written as a generic test rather than a singular one
    so it stays beside the column it constrains in _schema.yml, where someone
    reading the column's description will see it.
#}
{% test non_negative(model, column_name) %}

select {{ column_name }}
from {{ model }}
where {{ column_name }} < 0

{% endtest %}
