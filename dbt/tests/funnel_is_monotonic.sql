-- A funnel stage must never be larger than the one before it.
--
-- Every stage is a filter over the stage above, so growth is impossible unless
-- a filter does the opposite of what its name says -- a flag inverted, a rank
-- compared the wrong way, a window that partitions on something it should not.
-- Nothing else here would catch that: the counts would still be plausible, the
-- percentages would still sum, and the published total would simply be wrong.
--
-- Stage 1 is exempt from nothing: it is read from the loader's manifest rather
-- than counted from the model, so a stage 2 above it means the two disagree
-- about what was ingested, which is exactly the disagreement this mart exists
-- to make visible.
--
-- The unit change at stage 5 does not weaken this. Collapsing the runs of a
-- posting into one can only reduce the count, so non-increasing still has to
-- hold across the boundary even though the percentage across it means
-- something else.

with sequenced as (

    select
        stage_order,
        stage,
        records,
        lag(records) over (order by stage_order) as previous_records,
        lag(stage)   over (order by stage_order) as previous_stage
    from {{ ref('mart_pipeline_funnel') }}

)

select
    stage_order,
    previous_stage,
    previous_records,
    stage,
    records
from sequenced
where previous_records is not null
  and records > previous_records
