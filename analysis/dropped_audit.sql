-- What the scope filter removes, and what non-German rows survive it.
--
-- The funnel audit showed the scope filter drops 1,596 rows against dedup's
-- 32. This asks whether that loss is correct: the title pattern is entirely
-- English, and the source is a German job database.
--
--   psql -U jobs -d jobs -f analysis/dropped_audit.sql

\echo ''
\echo '=== 4. WHO GETS DROPPED BY THE TITLE FILTER ==='

with ag as (
    select posting_id, 'arbeitsagentur'::text as source, run_date, title, city, country
    from analytics_staging.stg_arbeitsagentur__postings
),
an as (
    select posting_id, 'arbeitnow'::text, run_date, title, city, null::text
    from analytics_staging.stg_arbeitnow__postings
),
unioned as (select * from ag union all select * from an),
latest as (
    select *, row_number() over (
        partition by source, posting_id order by run_date desc
    ) as run_rank
    from unioned
)
select
    source,
    count(*) as total,
    count(*) filter (
        where title ~* '(data|analytics|bi\M|business intelligence|etl)'
    ) as kept,
    count(*) filter (
        where title !~* '(data|analytics|bi\M|business intelligence|etl)'
    ) as dropped,
    -- would a German vocabulary rescue any of them?
    count(*) filter (
        where title !~* '(data|analytics|bi\M|business intelligence|etl)'
          and title ~* '(daten|datenbank|auswertung|informationsmanagement)'
    ) as dropped_but_german_data_word
from latest
where run_rank = 1
group by source;

\echo ''
\echo '=== 5. SAMPLE OF DROPPED FEDERAL TITLES ==='
\echo '(are these really not data jobs?)'

select distinct left(title, 62) as dropped_title
from analytics_staging.stg_arbeitsagentur__postings
where title !~* '(data|analytics|bi\M|business intelligence|etl)'
order by 1
limit 30;

\echo ''
\echo '=== 6. NON-GERMAN ROWS THAT SURVIVED ==='
\echo '(country is unknown for Arbeitnow, so location text is all we have)'

select
    left(city, 40) as location,
    count(*)       as postings
from analytics_intermediate.int_postings
where source = 'arbeitnow'
group by 1
order by 2 desc, 1
limit 40;
