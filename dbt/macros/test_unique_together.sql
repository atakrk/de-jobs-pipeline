{#
    Generic test: uniqueness over several columns (avoids dbt_utils).

        - name: posting_id
          tests:
            - unique_together:
                others: [run_date]
#}
{% test unique_together(model, column_name, others) %}

{%- set key = [column_name] + others -%}

with counted as (

    select {{ key | join(', ') }}, count(*) as rows_for_key
    from {{ model }}
    group by {{ key | join(', ') }}

)

select *
from counted
where rows_for_key > 1

{% endtest %}
