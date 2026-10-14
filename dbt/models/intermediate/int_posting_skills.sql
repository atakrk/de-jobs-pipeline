-- One row per (posting, skill) mention.
-- Patterns come from the skills seed and match on word boundaries.

with postings as (

    select posting_id, source, description
    from {{ ref('int_postings') }}
    where description is not null
      and length(description) > {{ var('description_min_chars') }}

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
        on {{ match_word_expr('p.description', 's.pattern', ignore_case=true) }}

)

select * from matched
