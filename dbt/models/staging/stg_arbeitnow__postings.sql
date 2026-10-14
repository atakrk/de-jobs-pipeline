-- Arbeitnow postings, renamed to the same columns as the federal source.
-- The source states no country, so country is left null (not assumed Germany).

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
