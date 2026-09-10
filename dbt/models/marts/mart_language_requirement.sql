-- How much of the market is gated on German.
--
-- Measured only over postings with a real description, and only where an
-- explicit competency phrase appears. Postings that simply happen to be
-- written in German are not counted -- that would make the answer 100% and
-- tell nobody anything.

with scoped as (

    select *
    from {{ ref('int_postings') }}
    where description is not null and length(description) > 200

)

select
    source,
    count(*)                                            as postings,
    count(*) filter (where requires_german)             as requires_german,
    count(*) filter (where mentions_english)            as mentions_english,
    count(*) filter (
        where mentions_english and not requires_german
    )                                                   as english_without_german,
    round(100.0 * count(*) filter (where requires_german) / nullif(count(*), 0), 1)
                                                        as pct_requires_german
from scoped
group by source

union all

select
    'ALL',
    count(*),
    count(*) filter (where requires_german),
    count(*) filter (where mentions_english),
    count(*) filter (where mentions_english and not requires_german),
    round(100.0 * count(*) filter (where requires_german) / nullif(count(*), 0), 1)
from scoped
