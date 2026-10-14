-- Raw landing zone.
--
-- Payloads are stored as jsonb, untouched. Flattening happens in dbt.
-- Grain is (source_id, run_date), so reruns of a day are idempotent.

CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.ingest_runs (
    source        text        NOT NULL,
    run_date      date        NOT NULL,
    manifest      jsonb       NOT NULL,
    loaded_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, run_date)
);

CREATE TABLE IF NOT EXISTS raw.arbeitsagentur_postings (
    source_id     text        NOT NULL,
    run_date      date        NOT NULL,
    search_term   text,
    payload       jsonb       NOT NULL,
    loaded_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, run_date)
);

CREATE TABLE IF NOT EXISTS raw.arbeitsagentur_details (
    source_id     text        NOT NULL,
    run_date      date        NOT NULL,
    payload       jsonb       NOT NULL,
    loaded_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, run_date)
);

CREATE TABLE IF NOT EXISTS raw.arbeitnow_postings (
    source_id     text        NOT NULL,
    run_date      date        NOT NULL,
    payload       jsonb       NOT NULL,
    loaded_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, run_date)
);

-- Postings are almost always filtered by publication date and location.
CREATE INDEX IF NOT EXISTS idx_ag_postings_published
    ON raw.arbeitsagentur_postings ((payload ->> 'datumErsteVeroeffentlichung'));
CREATE INDEX IF NOT EXISTS idx_ag_details_gin
    ON raw.arbeitsagentur_details USING gin (payload);
