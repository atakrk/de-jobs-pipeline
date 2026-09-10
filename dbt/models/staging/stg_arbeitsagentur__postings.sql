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
        payload ->> 'stellenangebotsTitel'                 as title,
        payload ->> 'hauptberuf'                           as occupation,
        payload ->> 'firma'                                as employer,
        payload ->> 'stellenangebotsart'                   as posting_type,
        payload ->> 'vertragsdauer'                        as contract_duration,
        (payload ->> 'arbeitszeitVollzeit')::boolean       as is_full_time,
        (payload ->> 'quereinstiegGeeignet')::boolean      as suits_career_changers,

        nullif(payload ->> 'gehaltsspanneVon', '')::numeric as salary_from,
        nullif(payload ->> 'gehaltsspanneBis', '')::numeric as salary_to,
        payload ->> 'verguetungsangabe'                    as salary_basis,

        payload -> 'stellenlokationen' -> 0 -> 'adresse' ->> 'ort'    as city,
        payload -> 'stellenlokationen' -> 0 -> 'adresse' ->> 'plz'    as postcode,
        payload -> 'stellenlokationen' -> 0 -> 'adresse' ->> 'region' as region,
        payload -> 'stellenlokationen' -> 0 -> 'adresse' ->> 'land'   as country,
        coalesce(jsonb_array_length(payload -> 'stellenlokationen'), 0) as location_count,

        nullif(payload ->> 'datumErsteVeroeffentlichung', '')::date as published_at,
        nullif(payload ->> 'aenderungsdatum', '')::timestamp        as changed_at

    from source

)

select * from flattened
