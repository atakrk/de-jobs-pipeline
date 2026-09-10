-- One row per (posting, skill) mention.
--
-- Matching uses word boundaries, which matters more than it looks: without
-- them 'sql' matches inside 'postgresql' and 'r' matches inside every German
-- word on the page. Patterns live in a seed rather than in this SQL so that
-- adding a tool is a data change, reviewable as a one-line diff.

with postings as (

    select posting_id, source, description
    from {{ ref('int_postings') }}
    where description is not null
      and length(description) > 200   -- stubs carry no requirements

),

skills as (

    select * from {{ ref('skills') }}

),

matched as (

    select
        p.posting_id,
        p.source,
        s.skill_key,
        s.display_name,
        s.category
    from postings p
    inner join skills s
        on p.description ~* ('\m(' || s.pattern || ')\M')

)

select * from matched
