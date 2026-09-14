-- How many rows survive each stage, in the order int_postings applies them.
--
-- The README publishes the last stage. Publishing only the survivors hides
-- that the run began with roughly five thousand rows, and when the published
-- number moves overnight nothing says which stage moved it: fewer ingested,
-- more filtered out of scope, more aged past the freshness window, more
-- collapsed by deduplication, or simply fewer descriptions fetched. Each of
-- those is a different problem and they are indistinguishable from the total.
--
-- Every stage after the first counts int_postings_scored, which is the model
-- int_postings filters. The funnel therefore cannot disagree with the number
-- it explains -- the alternative is re-deriving the filters here, which is how
-- the four copies in analysis/dedup_audit.sql quietly stopped describing the
-- model they audited.

with scored as (

    select * from {{ ref('int_postings_scored') }}

),

-- Stage 1 has to come from the loader. The grain is applied in load/rows.py,
-- before the insert, so by the time anything is queryable the duplicates are
-- already gone and no dbt model can count what was read.
--
-- Driven from the runs actually present in the data rather than from
-- ingest_runs, so a manifest left behind by a pruned run cannot inflate it.
--
-- A run loaded before the loader recorded rows_read has none, and there is no
-- way to recover it -- the files it read are gone. Rather than drop the run,
-- which would make stage 2 larger than stage 1, the count falls back to what
-- survived the grain for that run. That understates rather than invents: the
-- run certainly read at least that many rows. Stage 1 is therefore a floor
-- while any such run is still inside the retention window, and exact again
-- once they age out.
per_run as (

    select source, run_date, count(*) as distinct_postings
    from scored
    group by source, run_date

),

runs as (

    select sum(coalesce(r.rows_read, p.distinct_postings)) as rows_read
    from per_run p
    left join {{ ref('stg_ingest_runs') }} r
      on r.source_name = p.source
     and r.run_date = p.run_date

),

stages as (

    select 1 as stage_order, 'rows_read' as stage,
           (select rows_read from runs) as postings

    union all
    select 2, 'distinct_postings', count(*) from scored

    union all
    select 3, 'title_in_scope', count(*) from scored
    where title_in_scope

    union all
    select 4, 'in_germany', count(*) from scored
    where title_in_scope and country_known

    union all
    select 5, 'latest_snapshot', count(*) from scored
    where title_in_scope and country_known and run_rank = 1

    union all
    select 6, 'still_advertised', count(*) from scored
    where still_advertised

    union all
    select 7, 'deduplicated', count(*) from scored
    where still_advertised and dedup_rank = 1

    union all
    select 8, 'with_description', count(*) from scored
    where still_advertised and dedup_rank = 1 and has_description

),

-- pct_of_previous and pct_of_first are kept apart on purpose. They answer
-- different questions -- "what did this stage cost" against "what is left of
-- what we started with" -- and a reader who takes one for the other reads a
-- 94% stage as a 94% survival rate. Publishing one column and letting the
-- context decide which it meant is how a wrong percentage gets published.
sequenced as (

    select
        stage_order,
        stage,
        postings,
        lag(postings) over (order by stage_order)  as previous_postings,
        first_value(postings) over (order by stage_order
                                    rows between unbounded preceding
                                             and unbounded following) as first_postings
    from stages

)

select
    stage_order,
    stage,
    postings,
    round(100.0 * postings / nullif(previous_postings, 0), 1) as pct_of_previous,
    round(100.0 * postings / nullif(first_postings, 0), 1)    as pct_of_first,
    previous_postings - postings                              as dropped
from sequenced
order by stage_order
