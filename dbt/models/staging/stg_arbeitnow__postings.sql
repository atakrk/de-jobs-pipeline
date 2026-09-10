-- Second source. Shape differs from the federal API, so it is normalised
-- into the same column names here rather than in the union downstream.

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
