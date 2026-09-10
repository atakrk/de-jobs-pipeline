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
        posting_id,
        'arbeitnow'          as source,
        run_date,
        title,
        employer,
        city,
        null::text           as region,
        'DEUTSCHLAND'        as country,
        null::numeric        as salary_from,
        null::numeric        as salary_to,
        null::boolean        as is_full_time,
        published_at,
        description,
        allows_home_office,
        null::boolean        as is_temp_agency

    from {{ ref('stg_arbeitnow__postings') }}

),

unioned as (

    select * from arbeitsagentur
    union all
    select * from arbeitnow

),

-- The Arbeitnow feed is a general board, not a search: filter it down to the
-- roles this project is about. The federal rows already came from a search,
-- but the same filter keeps the definition of "in scope" in one place.
in_scope as (

    select *
    from unioned
    where title ~* '(data|analytics|bi\M|business intelligence|etl)'

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
