-- How often each tool is named, and in what share of postings.
-- The denominator is postings that HAVE a description, not all postings:
-- dividing by rows we could never have matched would understate everything.

with scored as (

    select posting_id
    from {{ ref('int_postings') }}
    where description is not null and length(description) > 200

),

total as (

    select count(*) as postings_with_text from scored

),

per_skill as (

    select
        skill_key,
        display_name,
        category,
        count(distinct posting_id) as postings
    from {{ ref('int_posting_skills') }}
    group by 1, 2, 3

)

select
    s.skill_key,
    s.display_name,
    s.category,
    s.postings,
    t.postings_with_text,
    round(100.0 * s.postings / nullif(t.postings_with_text, 0), 1) as pct_of_postings
from per_skill s
cross join total t
order by s.postings desc
