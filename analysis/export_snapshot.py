"""Write the marts out as dated CSVs.

The snapshots are the published time series. They began as a workaround -- a
CI Postgres was created and destroyed with the job, so a single run could not
hold history and git had to. The daily run now builds on Databricks, which
does accumulate, but the snapshots stay: they are small, they are diffable,
and they outlive the thirty-day retention window the warehouse is bounded to.

One reader, two connections, the same shape the loaders use. Which marts are
read and how they are written must not depend on where they were built, or the
two paths drift and the CSVs stop being comparable across the change.

Usage:
    python analysis/export_snapshot.py
    set -a; source .env; set +a
    python analysis/export_snapshot.py --target databricks
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
from common import log  # noqa: E402

OUT_ROOT = Path(__file__).resolve().parents[1] / "data" / "snapshots"

MARTS = [
    "mart_skill_frequency",
    "mart_language_requirement",
    "mart_city_stats",
    "mart_salary_by_skill",
]


def connect(target: str):
    """The connection, and the prefix the marts are qualified by.

    Imports are local so that running against one engine does not require the
    other's driver to be installed.
    """
    if target == "postgres":
        import psycopg

        conn = psycopg.connect(
            host=os.getenv("PGHOST", "localhost"),
            port=os.getenv("PGPORT", "5433"),
            dbname=os.getenv("PGDATABASE", "jobs"),
            user=os.getenv("PGUSER", "jobs"),
            password=os.getenv("PGPASSWORD", "jobs"),
        )
        return conn, ""

    if target == "databricks":
        from databricks import sql as dbsql

        conn = dbsql.connect(
            server_hostname=os.environ["DATABRICKS_HOST"],
            http_path=os.environ["DATABRICKS_HTTP_PATH"],
            access_token=os.environ["DATABRICKS_TOKEN"],
        )
        return conn, os.getenv("DATABRICKS_CATALOG", "workspace") + "."

    raise SystemExit(f"unknown target '{target}' - expected postgres or databricks")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="postgres",
                        choices=["postgres", "databricks"],
                        help="which warehouse the marts were built in")
    args = parser.parse_args()

    out_dir = OUT_ROOT / date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)

    conn, prefix = connect(args.target)
    with conn, conn.cursor() as cur:
        for mart in MARTS:
            cur.execute(f"select * from {prefix}analytics_marts.{mart}")
            # Indexed rather than by name: psycopg returns Column objects and
            # the Databricks connector returns plain tuples.
            columns = [c[0] for c in cur.description]
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
