-- The funnel's last stage is the number every published percentage divides by.
--
-- mart_skill_frequency reports postings_with_text beside each rate, and the
-- README repeats it as the sample size. If the funnel's tail and that
-- denominator disagree, one of them is lying to a reader who has no way to
-- tell which -- and the funnel exists precisely so that a moving number can be
-- traced rather than guessed at.
--
-- They are computed from the same flag on the same model, so this should be
-- impossible. It is asserted because "should be impossible" is what was true
-- of the hardcoded country and of the grain the primary key was silently
-- holding.

with funnel as (

    select postings
    from {{ ref('mart_pipeline_funnel') }}
    where stage = 'with_description'

),

published as (

    select distinct postings_with_text
    from {{ ref('mart_skill_frequency') }}

)

select
    f.postings        as funnel_tail,
    p.postings_with_text as published_denominator
from funnel f
full outer join published p
  on f.postings = p.postings_with_text
where f.postings is null
   or p.postings_with_text is null
