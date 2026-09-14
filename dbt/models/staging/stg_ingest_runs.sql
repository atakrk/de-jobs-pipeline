-- What each ingest run fetched, as columns.
--
-- Two of these fields are written by the loader rather than by the ingest:
-- how many posting rows it read, and how many of them the (source_id,
-- run_date) grain collapsed. Neither is recoverable downstream, because the
-- collapse happens in load/rows.py before anything reaches the warehouse --
-- so the first stage of mart_pipeline_funnel would otherwise have to be taken
-- on trust, and a funnel whose first number cannot be checked is decoration.

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
