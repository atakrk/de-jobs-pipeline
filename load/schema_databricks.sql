-- Raw landing zone, Databricks / Unity Catalog.
--
-- Same shape as load/schema.sql, except:
--   payload is STRING, since the models' JSON functions read strings.
--   No primary keys (Delta doesn't enforce them); the loader replaces a run date instead.
-- {catalog} and {schema} are filled in by the loader, so the fixture can use its own schema.

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
