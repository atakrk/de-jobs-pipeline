-- Share of postings that require German (explicit phrase only, so a floor).
-- Per-source rows under min_source_postings are suppressed; the ALL row always shows.

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
