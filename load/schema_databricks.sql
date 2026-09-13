-- Raw landing zone, Databricks / Unity Catalog.
--
-- The same shape as load/schema.sql, with two differences that are forced by
-- the platform rather than chosen:
--
--   payload is STRING, not jsonb. Databricks has a VARIANT type, but the
--   functions the models use (get_json_object, json_array_length) read JSON
--   out of strings, and switching to VARIANT would mean a second dialect of
--   every staging model. The bytes are the same; only the column type differs.
--
--   There are no primary keys. Delta does not enforce them, so idempotence is
--   handled by the loader instead: it deletes the rows for a run date before
--   inserting them. Loading the same day twice therefore replaces rather than
--   duplicates, which is the same guarantee (source_id, run_date) gives in
--   Postgres, arrived at differently.
--
-- {catalog} and {schema} are substituted by the loader. The schema is not
-- hardcoded so the fixture gate can be pointed at a throwaway one in the
-- same workspace, where it cannot reach a table holding a real run.

CREATE SCHEMA IF NOT EXISTS {catalog}.{schema};

CREATE TABLE IF NOT EXISTS {catalog}.{schema}.ingest_runs (
    source      STRING    NOT NULL,
    run_date    DATE      NOT NULL,
    manifest    STRING    NOT NULL,
    loaded_at   TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS {catalog}.{schema}.arbeitsagentur_postings (
    source_id   STRING    NOT NULL,
    run_date    DATE      NOT NULL,
    search_term STRING,
    payload     STRING    NOT NULL,
    loaded_at   TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS {catalog}.{schema}.arbeitsagentur_details (
    source_id   STRING    NOT NULL,
    run_date    DATE      NOT NULL,
    payload     STRING    NOT NULL,
    loaded_at   TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS {catalog}.{schema}.arbeitnow_postings (
    source_id   STRING    NOT NULL,
    run_date    DATE      NOT NULL,
    payload     STRING    NOT NULL,
    loaded_at   TIMESTAMP NOT NULL
);
