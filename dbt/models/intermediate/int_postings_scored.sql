-- Every row the pipeline read, with the reason it does or does not survive.
--
-- One row per (source, posting_id, run_date) -- the raw grain, nothing
-- dropped. `int_postings` is this model filtered on the flags below, and
-- `mart_pipeline_funnel` counts them. That is the whole point of splitting it:
-- the published count and the explanation of the published count come from one
-- expression, so they cannot drift apart.
--
-- They already did once. `analysis/dedup_audit.sql` carried four hand-copied
-- reconstructions of the scope filter and every one of them had gone stale --
-- still admitting `country is null` after the model stopped, still joining
-- details on run_date after the model stopped. An audit that re-derives what it
-- audits eventually audits something else. A funnel published to a website
-- would do the same, louder.
--
-- The flags are cumulative, and the window functions must see the same
-- populations the filtered chain used to see. Ranking over every row would give
-- a different answer, so each rank partitions on the flag that gated it: rows
-- that failed an earlier stage rank among themselves and are never read.

with ag_postings as (

    select * from {{ ref('stg_arbeitsagentur__postings') }}

),

ag_details as (

    -- The most recent description a run ever fetched for this posting, not the
    -- one from its latest listing run. Details are sampled: --detail-limit
    -- truncates, the seeded shuffle picks a different subset each day, and an
    -- interrupted run fetches almost none. Joining on run_date therefore threw
    -- away text that was sitting in the raw layer -- 171 of 634 postings on the
    -- day an interrupted run happened to be the latest one, every one of them
    -- counted as having no requirements to read.
    --
    -- The raw layer accumulates days precisely so this is possible. A
    -- description fetched on Monday is still that posting's description on
    -- Tuesday, and if the text has since changed, the newest one wins.
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
        p.city,
        cast(null as {{ dbt.type_string() }})  as region,
        g.resolved_country   as country,   -- derived, see int_arbeitnow_geo
        cast(null as {{ type_money() }}) as salary_from,
        cast(null as {{ type_money() }}) as salary_to,
        cast(null as boolean)                  as is_full_time,
        p.published_at,
        p.description,
        p.allows_home_office,
        cast(null as boolean)                  as is_temp_agency

    from an_postings p
    left join an_geo g using (posting_id)

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
scoped as (

    select
        *,
        {{ imatch('title', '(data|analytics|bi' ~ word_end() ~ '|business intelligence|etl)') }}
            as title_in_scope,
        country = 'DEUTSCHLAND' as country_known
    from unioned

),

-- The last day the pipeline ingested anything, taken from the data rather
-- than from the clock. Two reasons. A run that does not happen must not
-- shrink the dataset -- if the schedule fails for three days, the answer is
-- still the last thing measured, not three days of decay. And the fixture
-- carries one fixed run date, so a window measured against today would empty
-- it the week after it was written and take the parity gate with it.
latest_run as (

    select max(run_date) as run_date from unioned

),

ranked as (

    select
        s.*,
        {{ days_between('r.run_date', 's.run_date') }} as days_since_latest_run,

        -- Newest run per posting. Partitioned on the scope flag as well as the
        -- key, so in-scope rows rank among themselves exactly as they did when
        -- this ran over a filtered CTE. Out-of-scope rows get a rank too; it is
        -- never read.
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

-- Only postings the source has shown us recently.
--
-- `run_rank` says when a posting was last seen; it never said that had to be
-- lately. On a database holding one day those are the same sentence, which is
-- why this was invisible until the warehouse began to accumulate. On thirty
-- days it stops being: "every posting seen at least once this month" counts
-- vacancies that were filled and withdrawn weeks ago, and the published total
-- climbs every morning while the market does not.
--
-- The window is one number, in dbt_project.yml, and is not the retention
-- window. Retention bounds storage; this defines "currently advertised". They
-- answer different questions and need not agree.
--
-- The comparison is against the newest run across both sources, not per
-- source. If one API stops answering, its postings age out and the count
-- falls -- which is the signal. Per-source freshness would hide a dead feed
-- behind figures that still look healthy.
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

-- Deduplicate across sources on employer + title. The same vacancy is
-- routinely syndicated to several boards, and counting it twice would inflate
-- exactly the numbers this project exists to report.
--
-- The cross-source key is approximate: no shared identifier exists, so an
-- employer that posts two genuinely different roles under one title will be
-- collapsed. That is the trade this project accepts, and it is why the source
-- column is kept -- so the effect stays measurable.
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
                -- and break the remaining ties on something unique, or the
                -- winner is whichever row the engine happened to reach first.
                -- One employer advertised the same title in Bremen and
                -- Osnabrück on the same day: Postgres kept Bremen, Databricks
                -- kept Osnabrück, and neither was wrong because nothing in the
                -- ordering said which should win. The choice is arbitrary; it
                -- has to be reproducible.
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

    -- A German posting is not the same as a posting that requires German:
    -- almost every federal listing is written in German regardless. Only an
    -- explicit competency phrase counts.
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

    -- Long enough to read requirements from. The threshold is a variable
    -- because two places need the same answer: this flag, and the denominator
    -- mart_skill_frequency publishes every percentage against. Two literals
    -- would be one edit away from disagreeing.
    description is not null
        and length(description) > {{ var('description_min_chars') }}
        as has_description

from deduplicated
