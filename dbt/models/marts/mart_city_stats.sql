-- Where the roles are, and what they pay there.

select
    coalesce(city, 'Unknown')                                       as city,
    region,
    count(*)                                                        as postings,
    count(*) filter (where allows_home_office)                      as home_office_postings,
    count(*) filter (where salary_from is not null)                 as postings_with_salary,
    cast(percentile_cont(0.5) within group (
        order by salary_from
    ) filter (where salary_from between 20000 and 250000) as int)   as median_salary_from
from {{ ref('int_postings') }}
group by 1, 2
having count(*) >= 2
order by postings desc, city, region
