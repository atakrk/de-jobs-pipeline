-- Every row read, one per (source, posting_id, run_date), with flags instead of filters.
-- int_postings filters on these flags and mart_pipeline_funnel counts them.
-- Each rank partitions on the flag before it, so failed rows rank separately.

with ag_postings as (

    select * from {{ ref('stg_arbeitsagentur__postings') }}

),

ag_details as (

    -- Newest description ever fetched, not only same-day: details are sampled.
    select * from (
        select
            *,
            row_number() over (
                partition by posting_id
                order by run_date desc
            ) as detail_rank
        from {{ ref('stg_arbeitsagentur__details') }}
    ) ranked
    where detail_rank = 1

),

an_postings as (

    select * from {{ ref('stg_arbeitnow__postings') }}

),

an_geo as (

    select * from {{ ref('int_arbeitnow_geo') }}

),

arbeitsagentur as (

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

    from ag_postings p
    left join ag_details d using (posting_id)

),

arbeitnow as (

    select
        p.posting_id,
        'arbeitnow'          as source,
        p.run_date,
        p.title,
        p.employer,
        -- Derived in int_arbeitnow_geo; null unless one city is named.
        g.resolved_city      as city,
        g.resolved_region    as region,
        g.resolved_country   as country,   -- derived, see int_arbeitnow_geo
        cast(null as {{ type_money() }}) as salary_from,
        cast(null as {{ type_money() }}) as salary_to,
        cast(null as boolean)                  as is_full_time,
        p.published_at,
        p.description,
        p.allows_home_office,
        cast(null as boolean)                  as is_temp_agency

    from an_postings p
    left join an_geo g using (posting_id, run_date)

),

unioned as (

    select * from arbeitsagentur
    union all
    select * from arbeitnow

),

-- Scope. Role: positive pattern minus exclusions (data centre, data protection,
-- sales, dual study). Country: keep only rows where Germany is established;
-- unknown is excluded and counted.
{%- set scope_roles = '(data|analytics|bi' ~ word_end() ~ '|business intelligence|etl)' %}
{%- set scope_exclusions = [
    'data ?cent(er|re)',
    'rechenzentr',
    'data protection',
    'datenschutz',
    'vertrieb',
    'sales (specialist|representative|professional|consultant|manager|engineer|support)',
    'account manager',
    'dual(es|er|e|en)?[ -](studium|student|bachelor|master|hochschul|studien)',
    'dhbw'
] %}
-- Employer names in the title that contain a scope word (NTT DATA). Excluded
-- only when the title names no data role, so real data roles survive.
{%- set scope_employer_noise = '(ntt data)' %}
{%- set scope_role_words = [
    'engineer', 'engineering', 'scientist', 'science', 'analyst', 'analytics',
    'architect', 'warehouse', 'platform', 'steward', 'governance',
    'migration', 'integration'
] %}
{%- set scope_role_head = '((data|analytics|bi)[ /&-]*('
                          ~ scope_role_words | join('|') ~ '))' %}
scoped as (

    select
        *,
        {{ imatch('title', scope_roles) }}
            and not {{ imatch('title', '(' ~ scope_exclusions | join('|') ~ ')') }}
            and not (
                {{ imatch('title', scope_employer_noise) }}
                and not {{ imatch('title', scope_role_head) }}
            )
            as title_in_scope,
        country = 'DEUTSCHLAND' as country_known
    from unioned

),

-- Newest run in the data, not today's date, so missed runs and the fixture don't empty the window.
latest_run as (

    select max(run_date) as run_date from unioned

),

ranked as (

    select
        s.*,
        {{ days_between('r.run_date', 's.run_date') }} as days_since_latest_run,

        -- Newest run per posting, ranked within the scope flag.
        row_number() over (
            partition by
                s.source,
                s.posting_id,
                case when s.title_in_scope and s.country_known then 1 else 0 end
            order by s.run_date desc
        ) as run_rank

    from scoped s
    cross join latest_run r

),

-- Still advertised: seen within posting_freshness_days (7) of the newest run.
-- Freshness is not retention (30 days). Measured across both sources so a dead feed shows.
staged as (

    select
        *,
        title_in_scope
            and country_known
            and run_rank = 1
            and days_since_latest_run < {{ var('posting_freshness_days') }}
            as still_advertised
    from ranked

),

-- Dedup on employer + title. No shared id across sources, so this is approximate.
deduplicated as (

    select
        *,
        row_number() over (
            partition by
                lower(coalesce(employer, '')),
                lower(title),
                case when still_advertised then 1 else 0 end
            order by
                -- prefer the federal source: it carries salary and region
                case when source = 'arbeitsagentur' then 0 else 1 end,
                published_at desc nulls last,
                -- unique tie-breaker so both engines pick the same row
                posting_id
        ) as dedup_rank
    from staged

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

    -- Only an explicit phrase counts, not text written in German.
    {{ imatch('description', '(deutschkenntnis|fließend(e|es)? deutsch|verhandlungssicher|sehr gute deutsch|gute deutschkenntnisse)') }}
        as requires_german,
    {{ imatch('description', '(english|englischkenntnis|englisch)') }} as mentions_english,
    length(coalesce(description, ''))                    as description_length,

    -- Stage flags, in the order int_postings applies them.
    title_in_scope,
    country_known,
    run_rank,
    days_since_latest_run,
    still_advertised,
    dedup_rank,

    -- Same threshold var as the mart_skill_frequency denominator.
    description is not null
        and length(description) > {{ var('description_min_chars') }}
        as has_description

from deduplicated
