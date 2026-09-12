-- Look at what the skill patterns actually matched.
--
-- The seed is a list of regexes run against free German prose. Word
-- boundaries stop 'sql' matching inside 'postgresql', but they do nothing
-- about a real German word that happens to equal a pattern. The only way to
-- know is to read the surrounding text.
--
--   psql -U jobs -d jobs -f analysis/skill_audit.sql

\echo ''
\echo '=== MATCH COUNTS, SHORTEST PATTERNS FIRST ==='
\echo '(short patterns are where false positives live)'

select
    s.skill_key,
    s.pattern,
    length(s.pattern) as pattern_len,
    count(distinct p.posting_id) as postings
from analytics_intermediate.int_postings p
join analytics_seeds.skills s
    on p.description ~* ('\m(' || s.pattern || ')\M')
where p.description is not null
group by 1, 2, 3
order by pattern_len, postings desc
limit 15;

\echo ''
\echo '=== CONTEXT AROUND THE RISKY MATCHES ==='
\echo '(read these: is the match really about the tool?)'

with sampled as (
    select
        s.skill_key,
        -- substring(... from pattern) returns only the FIRST parenthesised
        -- subexpression when the pattern has one. The alternation needs
        -- grouping, so make it non-capturing and wrap the whole span in the
        -- capture group instead -- otherwise this returns the bare keyword
        -- and the surrounding text we actually wanted is discarded.
        substring(
            lower(p.description)
            from ('(.{0,45}\m(?:' || s.pattern || ')\M.{0,45})')
        ) as context,
        row_number() over (partition by s.skill_key order by p.posting_id) as rn
    from analytics_intermediate.int_postings p
    join analytics_seeds.skills s
        on p.description ~* ('\m(' || s.pattern || ')\M')
    where p.description is not null
      and s.skill_key in ('etl', 'sap', 'java', 'sql', 'dbt', 'aws', 'gcp', 'spark')
)
select skill_key, replace(context, E'\n', ' ') as context
from sampled
where rn <= 4
order by skill_key, rn;
