-- Detail rows. The description is the whole point of this table: it is the
-- only field in the entire API that names the tools a job actually uses.

with source as (

    select * from {{ source('raw', 'arbeitsagentur_details') }}

),

flattened as (

    select
        source_id                                            as posting_id,
        run_date,
        payload ->> 'stellenangebotsBeschreibung'            as description,
        (payload ->> 'homeofficemoeglich')::boolean          as allows_home_office,
        (payload ->> 'istArbeitnehmerUeberlassung')::boolean as is_temp_agency,
        (payload ->> 'istPrivateArbeitsvermittlung')::boolean as is_private_placement,
        payload ->> 'vertragsdauer'                          as contract_duration

    from source

)

select * from flattened
