"""Write the marts out as dated CSVs.

A CI run has no memory: its Postgres is created and destroyed with the job.
So the history lives in git instead. Each run commits a small snapshot of the
marts, and over months those files become the time series that a single
database run can never be.

Usage:
    python analysis/export_snapshot.py
"""

from __future__ import annotations

import csv
import os
import sys
from datetime import date
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
from common import log  # noqa: E402

OUT_ROOT = Path(__file__).resolve().parents[1] / "data" / "snapshots"

MARTS = [
    "mart_skill_frequency",
    "mart_language_requirement",
    "mart_city_stats",
    "mart_salary_by_skill",
]


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5433"),
        dbname=os.getenv("PGDATABASE", "jobs"),
        user=os.getenv("PGUSER", "jobs"),
        password=os.getenv("PGPASSWORD", "jobs"),
    )


def main() -> None:
    out_dir = OUT_ROOT / date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)

    with connect() as conn, conn.cursor() as cur:
        for mart in MARTS:
            cur.execute(f"select * from analytics_marts.{mart}")
            columns = [c.name for c in cur.description]
            rows = cur.fetchall()

            path = out_dir / f"{mart}.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(columns)
                writer.writerows(rows)

            log.info("%-28s %4d rows -> %s", mart, len(rows), path.name)

    log.info("snapshot written to %s", out_dir)


if __name__ == "__main__":
    main()
