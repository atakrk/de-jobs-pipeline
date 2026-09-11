-- Audit of the reduction from raw postings to int_postings.
--
-- int_postings drops roughly 1,000 rows and the README reports numbers built
-- on what survives. This splits the loss into its two causes and then shows
-- what deduplication actually merged, so the trade stops being an assumption.
--
--   psql -U jobs -d jobs -f analysis/dedup_audit.sql

\echo ''
\echo '=== 1. FUNNEL ==='

with ag as (
    select posting_id, 'arbeitsagentur'::text as source, run_date,
           title, employer, city, country
    from analytics_staging.stg_arbeitsagentur__postings
),
an as (
    select posting_id, 'arbeitnow'::text, run_date,
           title, employer, city, null::text
    from analytics_staging.stg_arbeitnow__postings
),
unioned as (select * from ag union all select * from an),
latest as (
    select *, row_number() over (
        partition by source, posting_id order by run_date desc
    ) as run_rank
    from unioned
),
current_rows as (select * from latest where run_rank = 1),
in_scope as (
    select * from current_rows
    where title ~* '(data|analytics|bi\M|business intelligence|etl)'
      and (country is null or country = 'DEUTSCHLAND')
)
select
    (select count(*) from unioned)                             as raw_rows_all_runs,
    (select count(*) from current_rows)                        as after_latest_run,
    (select count(*) from in_scope)                            as after_scope_filter,
    (select count(*) from current_rows) - (select count(*) from in_scope)
                                                               as lost_to_scope_filter,
    (select count(*) from analytics_intermediate.int_postings) as after_dedup,
    (select count(*) from in_scope)
      - (select count(*) from analytics_intermediate.int_postings)
                                                               as lost_to_dedup;

\echo ''
\echo '=== 2. WHAT DEDUP MERGED ==='

with ag as (
    select posting_id, 'arbeitsagentur'::text as source, run_date,
           title, employer, city, country
    from analytics_staging.stg_arbeitsagentur__postings
),
an as (
    select posting_id, 'arbeitnow'::text, run_date,
           title, employer, city, null::text
    from analytics_staging.stg_arbeitnow__postings
),
unioned as (select * from ag union all select * from an),
latest as (
    select *, row_number() over (
        partition by source, posting_id order by run_date desc
    ) as run_rank
    from unioned
),
in_scope as (
    select * from latest
    where run_rank = 1
      and title ~* '(data|analytics|bi\M|business intelligence|etl)'
      and (country is null or country = 'DEUTSCHLAND')
),
groups as (
    select
        lower(coalesce(employer, '')) as emp_key,
        lower(title)                  as title_key,
        count(*)                      as members,
        count(distinct source)        as distinct_sources,
        count(distinct coalesce(city, '?')) as distinct_cities
    from in_scope
    group by 1, 2
)
select
    case
        when members = 1 then 'unique (not merged)'
        when distinct_sources > 1 then 'merged ACROSS sources'
        when distinct_cities > 1 then 'merged within one source, DIFFERENT cities'
        else 'merged within one source, same city'
    end                                as merge_type,
    count(*)                           as groups,
    sum(members)                       as rows_involved,
    sum(members) - count(*)            as rows_dropped
from groups
group by 1
order by rows_dropped desc;

\echo ''
\echo '=== 3. SAMPLE: LARGEST MERGES WITHIN ONE SOURCE ==='
\echo '(these are the risky ones - same employer, same title, one source)'

with ag as (
    select posting_id, 'arbeitsagentur'::text as source, run_date,
           title, employer, city, country
    from analytics_staging.stg_arbeitsagentur__postings
),
an as (
    select posting_id, 'arbeitnow'::text, run_date,
           title, employer, city, null::text
    from analytics_staging.stg_arbeitnow__postings
),
unioned as (select * from ag union all select * from an),
latest as (
    select *, row_number() over (
        partition by source, posting_id order by run_date desc
    ) as run_rank
    from unioned
),
in_scope as (
    select * from latest
    where run_rank = 1
      and title ~* '(data|analytics|bi\M|business intelligence|etl)'
      and (country is null or country = 'DEUTSCHLAND')
)
select
    left(employer, 38)                                  as employer,
    left(title, 42)                                     as title,
    count(*)                                            as merged_rows,
    count(distinct coalesce(city, '?'))                 as cities,
    left(string_agg(distinct coalesce(city, '?'), ', '), 46) as city_list
from in_scope
group by lower(coalesce(employer, '')), lower(title), employer, title
having count(*) > 1 and count(distinct source) = 1
order by count(*) desc
limit 15;
