-- How much of the German market is gated on German.
--
-- Measured only over postings with a real description, and only where an
-- explicit competency phrase appears. Postings that simply happen to be
-- written in German are not counted -- that would make the answer 100% and
-- tell nobody anything, so this figure is a floor.
--
-- Per-source rows are suppressed below MIN_SOURCE_POSTINGS. After the second
-- source was validated down to the postings that are actually in Germany it
-- contributes about a dozen rows, and a percentage over a dozen postings
-- printed beside one over six hundred reads as a comparison when it is not
-- one. The ALL row always reports, and carries every posting regardless.

{% set min_source_postings = 30 %}

with scoped as (

    select *
    from {{ ref('int_postings') }}
    where description is not null
      and length(description) > {{ var('description_min_chars') }}

),

by_source as (

    select
        source                                              as population,
        count(*)                                            as postings,
        count(*) filter (where requires_german)             as requires_german,
        count(*) filter (where mentions_english)            as mentions_english,
        count(*) filter (
            where mentions_english and not requires_german
        )                                                   as english_without_german
    from scoped
    group by source
    having count(*) >= {{ min_source_postings }}

),

overall as (

    select
        'ALL'                                               as population,
        count(*)                                            as postings,
        count(*) filter (where requires_german)             as requires_german,
        count(*) filter (where mentions_english)            as mentions_english,
        count(*) filter (
            where mentions_english and not requires_german
        )                                                   as english_without_german
    from scoped

),

combined as (

    select * from by_source
    union all
    select * from overall

)

select
    population,
    postings,
    requires_german,
    mentions_english,
    english_without_german,
    round(100.0 * requires_german / nullif(postings, 0), 1)
        as pct_requires_german,
    round(100.0 * english_without_german / nullif(postings, 0), 1)
        as pct_english_without_german
from combined
order by postings desc, population
