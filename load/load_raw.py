"""Load raw JSON runs into Postgres.

Reads everything under data/raw/<source>/<run_date>/ and upserts it into the
``raw`` schema. Nothing is reshaped: the JSON goes in as jsonb exactly as the
API returned it, and every interpretation of it happens later in dbt.

Reruns are safe. The grain is (source_id, run_date), so loading the same day
twice updates in place rather than duplicating.

Reading the run directory lives in load/rows.py, shared with the Databricks
loader. This file is only the Postgres writer.

Usage:
    python load/load_raw.py
    python load/load_raw.py --run-date 2026-09-10
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RAW_DIR, log  # noqa: E402
from rows import iter_runs, read_run  # noqa: E402

SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5433"),
        dbname=os.getenv("PGDATABASE", "jobs"),
        user=os.getenv("PGUSER", "jobs"),
        password=os.getenv("PGPASSWORD", "jobs"),
    )


def upsert(cur, table: str, rows: list[tuple], columns: list[str]) -> int:
    if not rows:
        return 0
    placeholders = ", ".join(["%s"] * len(columns))
    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in columns if c not in ("source_id", "run_date")
    )
    cur.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT (source_id, run_date) DO UPDATE SET {updates}, loaded_at = now()",
        rows,
    )
    return len(rows)


def write_run(cur, run) -> None:
    if run.manifest is not None:
        cur.execute(
            "INSERT INTO raw.ingest_runs (source, run_date, manifest) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (source, run_date) DO UPDATE "
            "SET manifest = EXCLUDED.manifest, loaded_at = now()",
            (run.source, run.run_date, Jsonb(run.manifest)),
        )

    upsert(cur, "raw.arbeitsagentur_postings",
           [(i, d, t, Jsonb(p)) for i, d, t, p in run.ag_postings],
           ["source_id", "run_date", "search_term", "payload"])
    upsert(cur, "raw.arbeitsagentur_details",
           [(i, d, Jsonb(p)) for i, d, p in run.ag_details],
           ["source_id", "run_date", "payload"])
    upsert(cur, "raw.arbeitnow_postings",
           [(i, d, Jsonb(p)) for i, d, p in run.an_postings],
           ["source_id", "run_date", "payload"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-date", help="load only this run date (YYYY-MM-DD)")
    args = parser.parse_args()

    if not RAW_DIR.exists():
        log.error("no raw data at %s - run an ingest first", RAW_DIR)
        raise SystemExit(1)

    postings = details = 0
    with connect() as conn, conn.cursor() as cur:
        cur.execute(SCHEMA_FILE.read_text("utf-8"))
        log.info("schema ready")

        for source, run_dir in iter_runs(RAW_DIR, args.run_date):
            run = read_run(source, run_dir)
            write_run(cur, run)
            log.info("%-16s %s -> %d postings, %d details",
                     source, run.run_date, run.posting_count, run.detail_count)
            postings += run.posting_count
            details += run.detail_count

        conn.commit()

    log.info("loaded %d postings and %d details", postings, details)


if __name__ == "__main__":
    main()
