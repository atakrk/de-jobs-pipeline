-- What the scope filter removes, and what non-German rows survive it.
--
-- The funnel audit showed the scope filter drops far more rows than dedup
-- merges. This asks whether that loss is correct, from both ends: the title
-- pattern is entirely English against a German job database, so it may drop
-- roles it should keep -- and `data` is unbounded, so it kept roles it should
-- have dropped until the exclusion list was added.
--
-- It reads title_in_scope from int_postings_scored rather than re-spelling
-- the pattern. The earlier version pasted the regex in four places; when the
-- pattern grew an exclusion list, all four would have gone on reporting the
-- old rule under the new rule's name.
--
--   psql -U jobs -d jobs -f analysis/dropped_audit.sql

\echo ''
\echo '=== 4. WHO GETS DROPPED BY THE TITLE FILTER ==='

select
    source,
    count(*)                                     as total,
    count(*) filter (where title_in_scope)       as kept,
    count(*) filter (where not title_in_scope)   as dropped,
    -- would a German vocabulary rescue any of them?
    count(*) filter (
        where not title_in_scope
          and title ~* '(daten|datenbank|auswertung|informationsmanagement)'
    ) as dropped_but_german_data_word
from analytics_intermediate.int_postings_scored
where run_rank = 1
group by source;

\echo ''
\echo '=== 5. SAMPLE OF DROPPED FEDERAL TITLES ==='
\echo '(are these really not data jobs? the list now mixes two populations:'
\echo ' titles the pattern never matched, and titles a named exclusion removed)'

select distinct left(title, 62) as dropped_title
from analytics_intermediate.int_postings_scored
where source = 'arbeitsagentur'
  and not title_in_scope
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
