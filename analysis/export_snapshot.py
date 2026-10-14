"""Write the marts out as dated CSVs.

The snapshots are the published time series and outlive the 30-day raw window.

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
            # By index: works for both drivers.
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
