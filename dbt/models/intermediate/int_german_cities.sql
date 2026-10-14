-- German place names taken from federal postings with country = DEUTSCHLAND,
-- plus aliases (e.g. Munich -> München). Used to place Arbeitnow locations.
-- Short names and names with regex-unsafe punctuation are dropped.

with federal as (

    select
        {{ norm('city') }} as city_norm,
        city,
        region,
        count(*)           as postings
    from {{ ref('stg_arbeitsagentur__postings') }}
    where city is not null
      and country = 'DEUTSCHLAND'
    group by 1, 2, 3

),

-- Most common spelling and state per name. Ties break on md5 so both engines agree.
federal_canonical as (

    select city_norm, city, region
    from (
        select
            *,
            row_number() over (
                partition by city_norm
                order by postings desc, md5(city), md5(coalesce(region, ''))
            ) as spelling_rank
        from federal
    ) ranked
    where spelling_rank = 1

),

-- Aliases map to the German name and take its state if known.
-- Own CTE because `dbt run --empty` breaks on an aliased ref.
aliases as (

    select alias, city from {{ ref('city_aliases') }}

),

from_aliases as (

    select
        {{ norm('a.alias') }} as city_norm,
        a.city,
        f.region
    from aliases a
    left join federal_canonical f
        on f.city_norm = {{ norm('a.city') }}

),

combined as (

    select city_norm, city, region from federal_canonical
    union all
    select city_norm, city, region from from_aliases
    where city_norm not in (select city_norm from federal_canonical)

)

select city_norm, city, region
from combined
where length(city_norm) >= 4
  and {{ match('city_norm', '^[a-z0-9 .-]+$') }}
