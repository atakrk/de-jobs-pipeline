"""Diff every mart between the Postgres build and the Databricks build.

The models are single-source across both platforms, which is only worth
anything if both platforms actually agree. A green `dbt build` does not show
that: every dialect rewrite compiles, and a wrong one returns different rows
rather than an error.

scripts/fixture.py answers the same question against synthetic rows chosen to
hit each rewritten expression. This answers it against whatever is really
loaded, which is where the two failures that mattered turned up -- a grain
that only one platform's primary key was enforcing, and a dedup whose
ordering was not a total order, so each engine kept a different city.

Run it after building both targets from the same raw data:

    set -a; source .env; set +a
    cd dbt && dbt build --profiles-dir .
    dbt build --profiles-dir . --target databricks
    cd .. && python scripts/compare_targets.py

Exits non-zero if any mart differs, so it can gate a change to a dialect macro.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal

import psycopg
from databricks import sql as dbsql

MARTS = [
    "mart_skill_frequency",
    "mart_salary_by_skill",
    "mart_city_stats",
    "mart_language_requirement",
]


def norm(value):
    """One spelling per value, so a type difference is not read as a data one.

    Postgres hands back Decimal where Databricks hands back float, and the two
    print the same number differently. Trailing zeros are stripped for the same
    reason: `55000.00` and `55000` are the same salary.
    """
    if isinstance(value, Decimal):
        return f"{value.normalize():f}"
    if isinstance(value, float):
        return f"{Decimal(repr(value)).normalize():f}"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value if value is None else str(value)


def sort_key(row):
    """Total order over rows that may contain nulls, which do not compare."""
    return tuple((value is None, value or "") for value in row)


def fetch(cur, table):
    cur.execute(f"select * from {table}")
    columns = [d[0] for d in cur.description]
    rows = [tuple(norm(v) for v in row) for row in cur.fetchall()]
    return columns, sorted(rows, key=sort_key)


def main() -> int:
    postgres = psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5433")),
        dbname=os.getenv("PGDATABASE", "jobs"),
        user=os.getenv("PGUSER", "jobs"),
        password=os.getenv("PGPASSWORD", "jobs"),
    )
    databricks = dbsql.connect(
        server_hostname=os.environ["DATABRICKS_HOST"],
        http_path=os.environ["DATABRICKS_HTTP_PATH"],
        access_token=os.environ["DATABRICKS_TOKEN"],
    )
    catalog = os.getenv("DATABRICKS_CATALOG", "workspace")

    differences = 0
    with postgres.cursor() as pg_cur, databricks.cursor() as db_cur:
        for mart in MARTS:
            pg_columns, pg_rows = fetch(pg_cur, f"analytics_marts.{mart}")
            db_columns, db_rows = fetch(db_cur, f"{catalog}.analytics_marts.{mart}")

            if pg_columns != db_columns:
                differences += 1
                print(f"{mart}: COLUMNS DIFFER")
                print(f"  postgres   {pg_columns}")
                print(f"  databricks {db_columns}")
                continue

            if pg_rows == db_rows:
                print(f"{mart}: identical ({len(pg_rows)} rows)")
                continue

            differences += 1
            print(f"{mart}: DIFFERS  postgres={len(pg_rows)} databricks={len(db_rows)}")
            for row in [r for r in pg_rows if r not in db_rows][:10]:
                print("   postgres only:  ", dict(zip(pg_columns, row)))
            for row in [r for r in db_rows if r not in pg_rows][:10]:
                print("   databricks only:", dict(zip(db_columns, row)))

    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main())
