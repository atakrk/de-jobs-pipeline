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
        {{ json_text('payload', 'title') }}          as title,
        {{ json_text('payload', 'company_name') }}   as employer,
        {{ json_text('payload', 'description') }}    as description,
        {{ json_text('payload', 'location') }}       as city,
        cast({{ json_text('payload', 'remote') }} as boolean)  as allows_home_office,
        {{ json_text('payload', 'url') }}            as url,
        {{ epoch_to_date(json_text('payload', 'created_at')) }} as published_at

    from source

)

select * from flattened
