-- The funnel's last stage must equal postings_with_text in mart_skill_frequency
-- (the denominator of every published rate).

with funnel as (

    select records
    from {{ ref('mart_pipeline_funnel') }}
    where stage = 'with_description'

),

published as (

    select distinct postings_with_text
    from {{ ref('mart_skill_frequency') }}

)

select
    f.records            as funnel_tail,
    p.postings_with_text as published_denominator
from funnel f
full outer join published p
  on f.records = p.postings_with_text
where f.records is null
   or p.postings_with_text is null
