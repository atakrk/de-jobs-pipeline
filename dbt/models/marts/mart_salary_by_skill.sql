-- Advertised salary by tool.
--
-- Only a minority of postings state a salary at all, so postings_with_salary
-- is reported alongside every figure. A median over four postings is not a
-- market rate, and the column is there so nobody reads it as one.

with posting_skills as (

    select * from {{ ref('int_posting_skills') }}

),

salaried as (

    select posting_id, salary_from, salary_to
    from {{ ref('int_postings') }}
    where salary_from is not null
      and salary_from between 20000 and 250000   -- drop monthly/hourly figures

)

select
    k.skill_key,
    k.display_name,
    k.category,
    count(*)                                                          as postings_with_salary,
    cast(percentile_cont(0.5) within group (order by s.salary_from) as int) as median_salary_from,
    cast(percentile_cont(0.5) within group (order by s.salary_to) as int)   as median_salary_to,
    cast(min(s.salary_from) as int)                                         as min_salary_from,
    cast(max(s.salary_to) as int)                                           as max_salary_to
from salaried s
inner join posting_skills k using (posting_id)
group by 1, 2, 3
having count(*) >= 3
order by median_salary_from desc nulls last
