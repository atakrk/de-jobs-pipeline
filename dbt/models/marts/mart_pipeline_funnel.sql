-- Rows left after each stage, in the order int_postings applies them.
-- Counts the flags on int_postings_scored instead of re-deriving the filters.

with scored as (

    select * from {{ ref('int_postings_scored') }}

),

ingest_runs as (

    select * from {{ ref('stg_ingest_runs') }}

),

-- Stage 1 comes from the loader manifest (dedup happens before the insert).
-- Runs without rows_read fall back to their distinct count, so it is a floor.
per_run as (

    select source, run_date, count(*) as distinct_postings
    from scored
    group by source, run_date

),

runs as (

    select sum(coalesce(r.rows_read, p.distinct_postings)) as rows_read
    from per_run p
    left join ingest_runs r
      on r.source_name = p.source
     and r.run_date = p.run_date

),

-- Stages 1-4 count posting-runs, 5+ count postings; `grain` says which.
-- Stage 5's drop is runs collapsing, not postings rejected.
stages as (

    select 1 as stage_order, 'rows_read' as stage, 'posting-run' as grain,
           (select rows_read from runs) as records

    union all
    select 2, 'distinct_postings', 'posting-run', count(*) from scored

    union all
    select 3, 'title_in_scope', 'posting-run', count(*) from scored
    where title_in_scope

    union all
    select 4, 'in_germany', 'posting-run', count(*) from scored
    where title_in_scope and country_known

    -- unit changes here: posting-run -> posting
    union all
    select 5, 'latest_snapshot', 'posting', count(*) from scored
    where title_in_scope and country_known and run_rank = 1

    union all
    select 6, 'still_advertised', 'posting', count(*) from scored
    where still_advertised

    union all
    select 7, 'deduplicated', 'posting', count(*) from scored
    where still_advertised and dedup_rank = 1

    union all
    select 8, 'with_description', 'posting', count(*) from scored
    where still_advertised and dedup_rank = 1 and has_description

),

sequenced as (

    select
        stage_order,
        stage,
        grain,
        records,
        lag(records) over (order by stage_order)  as previous_records,
        lag(grain)   over (order by stage_order)  as previous_grain,
        first_value(records) over (order by stage_order
                                   rows between unbounded preceding
                                            and unbounded following) as first_records
    from stages

)

select
    stage_order,
    stage,
    grain,
    records,
    round(100.0 * records / nullif(previous_records, 0), 1) as pct_of_previous,
    round(100.0 * records / nullif(first_records, 0), 1)    as pct_of_first,
    previous_records - records                              as dropped,
    -- pct_of_previous on this row is not a filter's survival rate
    previous_grain is not null and previous_grain <> grain  as grain_changes_here
from sequenced
order by stage_order
