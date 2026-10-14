"""Create the raw tables without loading anything into them.

Used for `dbt docs generate`, which needs the relations but not the rows.

Usage:
    python load/create_schema_only.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
from common import log  # noqa: E402

SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"


def main() -> None:
    with psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5433"),
        dbname=os.getenv("PGDATABASE", "jobs"),
        user=os.getenv("PGUSER", "jobs"),
        password=os.getenv("PGPASSWORD", "jobs"),
    ) as conn, conn.cursor() as cur:
        cur.execute(SCHEMA_FILE.read_text("utf-8"))
        conn.commit()
    log.info("raw schema created (no rows loaded)")


if __name__ == "__main__":
    main()
