-- Audit of the reduction from raw postings to int_postings.
--
-- int_postings drops roughly a thousand rows and the README reports numbers
-- built on what survives. This splits the loss into its causes, shows what
-- deduplication actually merged, and measures what adding city to the dedup
-- key would change -- so each trade stops being an assumption.
--
--   psql -U jobs -d jobs -f analysis/dedup_audit.sql
--
-- Section 1 selects mart_pipeline_funnel rather than recomputing it. The
-- sections after it still reconstruct scope, because they ask questions the
-- marts do not answer -- but scope is built once, into a temp view, rather
-- than pasted into each. The version before this one repeated it four times
-- and all four had drifted from the model: still admitting `country is null`
-- after the model stopped, still joining details on run_date after the model
-- stopped. An audit that re-derives what it audits eventually audits
-- something else.
--
-- The remaining reconstruction is the reason int_postings_scored exists. If
-- these sections start mattering enough to publish, they should move onto it
-- too.

\set ON_ERROR_STOP on

create temp view audit_scope as

with ag as (
    select
        posting_id,
        'arbeitsagentur'::text as source,
        run_date, title, employer, city, country
    from analytics_staging.stg_arbeitsagentur__postings
),

an as (
    select
        p.posting_id,
        'arbeitnow'::text as source,
        p.run_date, p.title, p.employer, p.city,
        g.resolved_country as country
    from analytics_staging.stg_arbeitnow__postings p
    left join analytics_intermediate.int_arbeitnow_geo g using (posting_id)
),

unioned as (select * from ag union all select * from an),

latest as (
    select *, row_number() over (
        partition by source, posting_id order by run_date desc
    ) as run_rank
    from unioned
)

select *
from latest
where run_rank = 1
  and title ~* '(data|analytics|bi\M|business intelligence|etl)'
  and country = 'DEUTSCHLAND';

\echo ''
\echo '=== 1. FUNNEL ==='
\echo '(read from mart_pipeline_funnel, not recomputed -- see the header.'
\echo ' the unit changes where grain does: nothing is rejected on that row)'

select
    stage_order,
    stage,
    grain,
    records,
    pct_of_previous,
    pct_of_first,
    dropped
from analytics_marts.mart_pipeline_funnel
order by stage_order;

\echo ''
\echo '=== 2. WHAT DEDUP MERGED ==='

with groups as (
    select
        count(*)                            as members,
        count(distinct source)              as distinct_sources,
        count(distinct coalesce(city, '?')) as distinct_cities
    from audit_scope
    group by lower(coalesce(employer, '')), lower(title)
)
select
    case
        when members = 1            then 'unique (not merged)'
        when distinct_sources > 1   then 'merged ACROSS sources'
        when distinct_cities > 1    then 'merged within one source, DIFFERENT cities'
        else                             'merged within one source, same city'
    end                     as merge_type,
    count(*)                as groups,
    sum(members)            as rows_involved,
    sum(members) - count(*) as rows_dropped
from groups
group by 1
order by rows_dropped desc;

\echo ''
\echo '=== 3. WHAT ADDING CITY TO THE KEY WOULD CHANGE ==='
\echo '(recovered = postings that would stop being merged)'

with by_key as (
    select
        lower(coalesce(employer, '')) as emp_key,
        lower(title)                  as title_key,
        count(*)                      as members,
        count(distinct source)        as distinct_sources,
        count(distinct lower(coalesce(city, '')))
                                      as distinct_cities
    from audit_scope
    group by 1, 2
)
select
    case
        when distinct_sources > 1 then 'across sources - risks double counting'
        else                           'within one source - likely real vacancies'
    end                              as split_type,
    count(*)                         as groups_that_would_split,
    sum(distinct_cities) - count(*)  as postings_recovered
from by_key
where members > 1 and distinct_cities > 1
group by 1
order by postings_recovered desc;

\echo ''
\echo '=== 4. THE RISKY ONES: cross-source groups spanning cities ==='
\echo '(same employer and title on both boards, different location text --'
\echo ' if these are the same place spelled twice, splitting double counts)'

select
    left(employer, 30)                                    as employer,
    left(title, 34)                                       as title,
    count(*)                                              as rows,
    left(string_agg(distinct source || ':' || coalesce(city, '?'), ' | '), 58)
                                                          as source_and_city
from audit_scope
group by lower(coalesce(employer, '')), lower(title), employer, title
having count(distinct source) > 1
   and count(distinct lower(coalesce(city, ''))) > 1
order by count(*) desc
limit 20;

\echo ''
\echo '=== 5. IS CITY EVEN THE RIGHT QUESTION? ==='
\echo '(of the groups that span cities, which carry the same description?'
\echo ' identical text across two cities is one vacancy advertised twice,'
\echo ' and splitting it would count the same text twice in the skill rates)'

with latest_detail as (
    -- Newest description ever fetched, matching int_postings. Joining on
    -- run_date instead is the bug that made most of this section undecidable:
    -- details are sampled, so the latest listing run often has none.
    select distinct on (posting_id) posting_id, description
    from analytics_staging.stg_arbeitsagentur__details
    order by posting_id, run_date desc
),
scoped as (
    select s.*, d.description
    from audit_scope s
    left join latest_detail d on d.posting_id = s.posting_id
),
groups as (
    select
        count(*)                                   as rows,
        count(distinct lower(coalesce(city, '')))  as cities,
        count(*) filter (where description is not null) as with_text,
        count(distinct md5(description))           as distinct_texts
    from scoped
    group by lower(coalesce(employer, '')), lower(title)
)
select
    case
        when with_text < rows   then 'some rows carry no text - undecidable'
        when distinct_texts = 1 then 'IDENTICAL text - one vacancy, many sites'
        else                         'different text - genuinely separate vacancies'
    end                     as verdict,
    count(*)                as groups,
    sum(cities) - count(*)  as postings_recovered_if_split
from groups
where rows > 1 and cities > 1
group by 1
order by 3 desc;

\echo ''
\echo '=== 6. WITHIN ONE SOURCE, DIFFERENT CITIES ==='
\echo '(one employer advertising one title in several places)'

select
    left(employer, 30)                                        as employer,
    left(title, 34)                                           as title,
    count(*)                                                  as rows,
    count(distinct lower(coalesce(city, '')))                 as cities,
    left(string_agg(distinct coalesce(city, '?'), ', '), 48)   as city_list
from audit_scope
group by lower(coalesce(employer, '')), lower(title), employer, title
having count(*) > 1
   and count(distinct source) = 1
   and count(distinct lower(coalesce(city, ''))) > 1
order by count(distinct lower(coalesce(city, ''))) desc, count(*) desc
limit 20;
