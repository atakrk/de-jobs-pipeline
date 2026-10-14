-- No funnel stage may be larger than the one before it.
-- Stage 1 comes from the loader manifest, so it is checked against stage 2 too.

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
