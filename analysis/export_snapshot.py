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
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import warehouse  # noqa: E402
from common import log  # noqa: E402

OUT_ROOT = Path(__file__).resolve().parents[1] / "data" / "snapshots"

MARTS = [
    "mart_skill_frequency",
    "mart_language_requirement",
    "mart_city_stats",
    "mart_salary_by_skill",
    "mart_pipeline_funnel",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    warehouse.add_target_argument(parser)
    args = parser.parse_args()

    out_dir = OUT_ROOT / date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)

    conn, marts = warehouse.connect(args.target)
    with conn, conn.cursor() as cur:
        for mart in MARTS:
            cur.execute(f"select * from {marts}.{mart}")
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
