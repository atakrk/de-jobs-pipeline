-- One row per distinct job posting, both sources combined.
--
-- The logic that produces this lives in int_postings_scored, which keeps every
-- row the pipeline read and records why each one does or does not survive.
-- This model is that model filtered on those flags, in the order they are
-- applied:
--
--   1. title_in_scope and country_known - the role matches, and Germany is
--      established rather than assumed.
--   2. run_rank = 1 - the newest run this posting appeared in.
--   3. still_advertised - and that run was recent enough to mean the vacancy
--      is still open.
--   4. dedup_rank = 1 - one row per employer and title across both sources.
--
-- Split out so that mart_pipeline_funnel counts the same expression this
-- filters on. A funnel that re-derived these rules would drift from them, which
-- is exactly what happened to the four copies in analysis/dedup_audit.sql.

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
