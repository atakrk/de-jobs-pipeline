{#
    Uniqueness over more than one column.

    dbt's built-in `unique` takes a single column and dbt_utils is not a
    dependency this project wants. Written as a generic test so the grain of a
    model is declared beside the column it starts with, rather than hidden in a
    file under tests/ that nobody reads while editing the model.

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
