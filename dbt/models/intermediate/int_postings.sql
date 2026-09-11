-- One row per distinct job posting, both sources combined.
--
-- Three things happen here, in order:
--   1. Attach the description. The federal API splits salary (listing) from
--      text (detail), so a posting is only complete once both are joined.
--   2. Keep the latest run per posting. Postings reappear across daily runs;
--      the newest snapshot wins.
--   3. Deduplicate across sources on employer + title. The same vacancy is
--      routinely syndicated to several boards, and counting it twice would
--      inflate exactly the numbers this project exists to report.
--
-- The cross-source key is approximate: no shared identifier exists, so an
-- employer that posts two genuinely different roles under one title will be
-- collapsed. That is the trade this project accepts, and it is why the
-- source column is kept -- so the effect stays measurable.

with arbeitsagentur as (

    select
        p.posting_id,
        'arbeitsagentur'  as source,
        p.run_date,
        p.title,
        p.employer,
        p.city,
        p.region,
        p.country,
        p.salary_from,
        p.salary_to,
        p.is_full_time,
        p.published_at,
        d.description,
        d.allows_home_office,
        d.is_temp_agency

    from {{ ref('stg_arbeitsagentur__postings') }} p
    left join {{ ref('stg_arbeitsagentur__details') }} d
        using (posting_id, run_date)

),

arbeitnow as (

    select
        p.posting_id,
        'arbeitnow'          as source,
        p.run_date,
        p.title,
        p.employer,
        p.city,
        null::text           as region,
        g.resolved_country   as country,   -- derived, see int_arbeitnow_geo
        null::numeric        as salary_from,
        null::numeric        as salary_to,
        null::boolean        as is_full_time,
        p.published_at,
        p.description,
        p.allows_home_office,
        null::boolean        as is_temp_agency

    from {{ ref('stg_arbeitnow__postings') }} p
    left join {{ ref('int_arbeitnow_geo') }} g using (posting_id)

),

unioned as (

    select * from arbeitsagentur
    union all
    select * from arbeitnow

),

-- Scope, defined in one place and visible rather than buried in a WHERE
-- clause somewhere downstream. Two rules:
--
--   1. Role: the Arbeitnow feed is a general board, not a search, so it needs
--      filtering to the roles this project is about. The federal rows already
--      came from a search, but applying the same rule to both keeps a single
--      definition of "in scope".
--   2. Country: this project reports on the German market, so a posting is
--      kept only where Germany is established -- stated by the source, or
--      resolved from the location text against known German place names.
--
--      An earlier version kept unknown-country rows instead, reasoning that
--      dropping them would discard the whole second source. Measurement
--      settled it: over half the second source's surviving rows were in
--      London and Paris. A dataset that reports on Germany cannot keep rows
--      it merely hopes are German, so unknown is now excluded and counted.
in_scope as (

    select *
    from unioned
    where title ~* '(data|analytics|bi\M|business intelligence|etl)'
      and country = 'DEUTSCHLAND'

),

latest_per_posting as (

    select
        *,
        row_number() over (
            partition by source, posting_id
            order by run_date desc
        ) as run_rank
    from in_scope

),

deduplicated as (

    select
        *,
        row_number() over (
            partition by lower(coalesce(employer, '')), lower(title)
            order by
                -- prefer the federal source: it carries salary and region
                case when source = 'arbeitsagentur' then 0 else 1 end,
                published_at desc nulls last
        ) as dedup_rank
    from latest_per_posting
    where run_rank = 1

)

select
    posting_id,
    source,
    run_date,
    title,
    employer,
    city,
    region,
    country,
    salary_from,
    salary_to,
    is_full_time,
    published_at,
    description,
    allows_home_office,
    is_temp_agency,

    -- A German posting is not the same as a posting that requires German:
    -- almost every federal listing is written in German regardless. Only an
    -- explicit competency phrase counts.
    description ~* '(deutschkenntnis|fließend(e|es)? deutsch|verhandlungssicher|sehr gute deutsch|gute deutschkenntnisse)'
        as requires_german,
    description ~* '(english|englischkenntnis|englisch)' as mentions_english,
    length(coalesce(description, ''))                    as description_length

from deduplicated
where dedup_rank = 1
