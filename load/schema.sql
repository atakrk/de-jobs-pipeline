-- Raw landing zone.
--
-- Payloads are stored as jsonb and NOT flattened here on purpose. Flattening
-- is a modelling decision, and modelling decisions belong in dbt where they
-- are versioned, tested and reviewable -- not buried in a Python loader that
-- silently drops a field nobody notices for a month.
--
-- (source_id, run_date) is the grain: one row per posting per ingest run, so
-- a rerun of the same day is idempotent while history across days is kept.

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
