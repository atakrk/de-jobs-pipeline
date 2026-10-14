{# Generic test: fails on negative values (avoids a dbt_utils dependency). #}
{% test non_negative(model, column_name) %}

select {{ column_name }}
from {{ model }}
where {{ column_name }} < 0

{% endtest %}
