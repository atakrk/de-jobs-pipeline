-- Listing rows, flattened. One row per posting per run.
--
-- A posting can sit in several locations; we keep the first, and carry the
-- count so a later model can tell "Berlin" from "Berlin plus four others"
-- rather than silently pretending every posting is single-site.

with source as (

    select * from {{ source('raw', 'arbeitsagentur_postings') }}

),

flattened as (

    select
        source_id                                          as posting_id,
        run_date,
        search_term,
        {{ json_text('payload', 'stellenangebotsTitel') }}   as title,
        {{ json_text('payload', 'hauptberuf') }}             as occupation,
        {{ json_text('payload', 'firma') }}                  as employer,
        {{ json_text('payload', 'stellenangebotsart') }}     as posting_type,
        {{ json_text('payload', 'vertragsdauer') }}          as contract_duration,
        cast({{ json_text('payload', 'arbeitszeitVollzeit') }} as boolean)   as is_full_time,
        cast({{ json_text('payload', 'quereinstiegGeeignet') }} as boolean)  as suits_career_changers,

        cast(nullif({{ json_text('payload', 'gehaltsspanneVon') }}, '') as {{ type_money() }}) as salary_from,
        cast(nullif({{ json_text('payload', 'gehaltsspanneBis') }}, '') as {{ type_money() }}) as salary_to,
        {{ json_text('payload', 'verguetungsangabe') }}      as salary_basis,

        {{ json_text('payload', ['stellenlokationen', 0, 'adresse', 'ort']) }}    as city,
        {{ json_text('payload', ['stellenlokationen', 0, 'adresse', 'plz']) }}    as postcode,
        {{ json_text('payload', ['stellenlokationen', 0, 'adresse', 'region']) }} as region,
        {{ json_text('payload', ['stellenlokationen', 0, 'adresse', 'land']) }}   as country,
        coalesce({{ json_array_len('payload', 'stellenlokationen') }}, 0)         as location_count,

        cast(nullif({{ json_text('payload', 'datumErsteVeroeffentlichung') }}, '') as date)      as published_at,
        cast(nullif({{ json_text('payload', 'aenderungsdatum') }}, '') as timestamp)             as changed_at

    from source

)

select * from flattened
