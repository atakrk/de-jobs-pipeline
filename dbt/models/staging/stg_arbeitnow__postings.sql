-- Second source. Shape differs from the federal API, so it is normalised
-- into the same column names here rather than in the union downstream.
--
-- This board covers the wider DACH/EU region and its payload states no
-- country, only a free-text location. Country is therefore left null
-- rather than assumed to be Germany: an assumption here would quietly put
-- Austrian and Swiss vacancies inside figures reported as German.

with source as (

    select * from {{ source('raw', 'arbeitnow_postings') }}

),

flattened as (

    select
        source_id                            as posting_id,
        run_date,
        payload ->> 'title'                  as title,
        payload ->> 'company_name'           as employer,
        payload ->> 'description'            as description,
        payload ->> 'location'               as city,
        (payload ->> 'remote')::boolean      as allows_home_office,
        payload ->> 'url'                    as url,
        to_timestamp((payload ->> 'created_at')::bigint)::date as published_at

    from source

)

select * from flattened
