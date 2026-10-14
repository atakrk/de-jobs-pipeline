-- Spot-check skill matches for false positives by reading the context.
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
        -- substring() returns the first capture group, so the keyword group is non-capturing.
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
