-- One row per distinct posting, both sources combined.
-- int_postings_scored filtered on its flags; mart_pipeline_funnel counts the same flags.

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
    requires_german,
    mentions_english,
    description_length

from {{ ref('int_postings_scored') }}
where still_advertised
  and dedup_rank = 1
