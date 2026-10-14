-- One row per ingest run, manifest fields as columns.
-- rows_read and duplicates_collapsed come from the loader (load/rows.py);
-- they feed the first stage of mart_pipeline_funnel.

with source as (

    select * from {{ source('raw', 'ingest_runs') }}

)

select
    source                                                        as source_name,
    run_date,
    cast({{ json_text('manifest', 'rows_read') }} as int)         as rows_read,
    cast({{ json_text('manifest', 'duplicates_collapsed') }} as int)
                                                                  as duplicates_collapsed,
    {{ json_text('manifest', 'results_key') }}                    as results_key

from source
