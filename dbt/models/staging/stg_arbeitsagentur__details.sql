-- Detail rows. The description is the whole point of this table: it is the
-- only field in the entire API that names the tools a job actually uses.

with source as (

    select * from {{ source('raw', 'arbeitsagentur_details') }}

),

flattened as (

    select
        source_id                                            as posting_id,
        run_date,
        {{ json_text('payload', 'stellenangebotsBeschreibung') }}   as description,
        cast({{ json_text('payload', 'homeofficemoeglich') }} as boolean)          as allows_home_office,
        cast({{ json_text('payload', 'istArbeitnehmerUeberlassung') }} as boolean) as is_temp_agency,
        cast({{ json_text('payload', 'istPrivateArbeitsvermittlung') }} as boolean) as is_private_placement,
        {{ json_text('payload', 'vertragsdauer') }}          as contract_duration

    from source

)

select * from flattened
