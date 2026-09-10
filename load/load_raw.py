"""Load raw JSON runs into Postgres.

Reads everything under data/raw/<source>/<run_date>/ and upserts it into the
``raw`` schema. Nothing is reshaped: the JSON goes in as jsonb exactly as the
API returned it, and every interpretation of it happens later in dbt.

Reruns are safe. The grain is (source_id, run_date), so loading the same day
twice updates in place rather than duplicating.

Usage:
    python load/load_raw.py
    python load/load_raw.py --run-date 2026-09-10
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
from common import RAW_DIR, log  # noqa: E402

SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"
ID_FIELDS = ["referenznummer", "refnr", "hashId"]


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5433"),
        dbname=os.getenv("PGDATABASE", "jobs"),
        user=os.getenv("PGUSER", "jobs"),
        password=os.getenv("PGPASSWORD", "jobs"),
    )


def posting_id(posting: dict) -> str | None:
    for field in ID_FIELDS:
        if posting.get(field):
            return str(posting[field])
    return None


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


def load_run(cur, source: str, run_dir: Path) -> dict[str, int]:
    run_date = run_dir.name
    counts = {"postings": 0, "details": 0}

    manifest_file = run_dir / "_manifest.json"
    if manifest_file.exists():
        cur.execute(
            "INSERT INTO raw.ingest_runs (source, run_date, manifest) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (source, run_date) DO UPDATE "
            "SET manifest = EXCLUDED.manifest, loaded_at = now()",
            (source, run_date, Jsonb(json.loads(manifest_file.read_text("utf-8")))),
        )

    posting_rows: list[tuple] = []
    for page_file in sorted(run_dir.glob("page_*.json")):
        blob = json.loads(page_file.read_text("utf-8"))

        if source == "arbeitsagentur":
            payload = blob["payload"]
            key = blob.get("results_key", "ergebnisliste")
            for posting in payload.get(key) or []:
                found = posting_id(posting)
                if found:
                    posting_rows.append(
                        (found, run_date, blob.get("search_term"), Jsonb(posting))
                    )
        else:  # arbeitnow
            for posting in blob.get("data") or []:
                slug = posting.get("slug")
                if slug:
                    posting_rows.append((slug, run_date, Jsonb(posting)))

    if source == "arbeitsagentur":
        counts["postings"] = upsert(
            cur, "raw.arbeitsagentur_postings", posting_rows,
            ["source_id", "run_date", "search_term", "payload"],
        )
        detail_rows = [
            (blob["id"], run_date, Jsonb(blob["payload"]))
            for blob in (
                json.loads(f.read_text("utf-8"))
                for f in sorted((run_dir / "details").glob("*.json"))
            )
        ]
        counts["details"] = upsert(
            cur, "raw.arbeitsagentur_details", detail_rows,
            ["source_id", "run_date", "payload"],
        )
    else:
        counts["postings"] = upsert(
            cur, "raw.arbeitnow_postings", posting_rows,
            ["source_id", "run_date", "payload"],
        )

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-date", help="load only this run date (YYYY-MM-DD)")
    args = parser.parse_args()

    if not RAW_DIR.exists():
        log.error("no raw data at %s - run an ingest first", RAW_DIR)
        raise SystemExit(1)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(SCHEMA_FILE.read_text("utf-8"))
        log.info("schema ready")

        total = {"postings": 0, "details": 0}
        for source_dir in sorted(p for p in RAW_DIR.iterdir() if p.is_dir()):
            for run_dir in sorted(p for p in source_dir.iterdir() if p.is_dir()):
                if args.run_date and run_dir.name != args.run_date:
                    continue
                counts = load_run(cur, source_dir.name, run_dir)
                log.info("%-16s %s -> %d postings, %d details",
                         source_dir.name, run_dir.name,
                         counts["postings"], counts["details"])
                total["postings"] += counts["postings"]
                total["details"] += counts["details"]

        conn.commit()

    log.info("loaded %d postings and %d details", total["postings"], total["details"])


if __name__ == "__main__":
    main()
