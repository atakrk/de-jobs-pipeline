"""Load the same raw JSON runs into Databricks.

The Postgres loader's counterpart. It reads the identical run directories
through load/rows.py and lands the identical unflattened payloads, so the dbt
models -- which are single-source across both platforms -- see the same bytes
whichever warehouse they run against.

Two things differ from the Postgres loader, and both come from Delta rather
than from a preference:

  payload is a STRING column holding the JSON text. See load/schema_databricks.sql.

  There is no ON CONFLICT. Delta does not enforce primary keys, so a run date
  is deleted before it is inserted. Reruns replace rather than duplicate,
  which is the same guarantee the Postgres grain gives.

Credentials come from the environment and are never logged:
    DATABRICKS_HOST, DATABRICKS_HTTP_PATH, DATABRICKS_TOKEN, DATABRICKS_CATALOG

Unlike the Postgres loader this one prunes: the warehouse is written to daily
and has to stay bounded. See prune() for the window and what it costs.

Usage:
    set -a; source .env; set +a
    python load/load_raw_databricks.py
    python load/load_raw_databricks.py --run-date 2026-09-12
    python load/load_raw_databricks.py --retain-days 90
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from databricks import sql as dbsql

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RAW_DIR, log  # noqa: E402
from rows import iter_runs, read_run  # noqa: E402

SCHEMA_FILE = Path(__file__).resolve().parent / "schema_databricks.sql"

RAW_TABLES = [
    "ingest_runs",
    "arbeitsagentur_postings",
    "arbeitsagentur_details",
    "arbeitnow_postings",
]

# How many days of runs the warehouse keeps. See prune().
RETAIN_DAYS = 30

# The warehouse rejects a statement whose bound parameters exceed 1 MB in
# total. Row count is a poor proxy for that -- one posting description runs to
# several kilobytes and the next is a single line -- so batches are filled by
# measured size, with headroom for the statement text around them. A row count
# still caps the batch so a very large number of tiny rows cannot build an
# unreasonable statement.
PARAM_BUDGET_BYTES = 800_000
MAX_BATCH_ROWS = 500


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        log.error("%s is not set - source your .env first", name)
        raise SystemExit(1)
    return value


def connect():
    return dbsql.connect(
        server_hostname=required_env("DATABRICKS_HOST"),
        http_path=required_env("DATABRICKS_HTTP_PATH"),
        access_token=required_env("DATABRICKS_TOKEN"),
    )


def raw_schema() -> str:
    """Where the raw tables live. Overridden only by the fixture gate."""
    return os.getenv("RAW_SCHEMA", "raw")


def ensure_schema(cur, catalog: str, schema: str | None = None) -> None:
    """Apply the schema file one statement at a time.

    The connector takes a single statement per execute, so the file has to be
    split. Comments come out before the split, not after: the file's prose
    contains a semicolon, and splitting first leaves the remainder of that
    comment line looking like a statement of its own. Only whole-line `--`
    comments are recognised, which is all this file uses.
    """
    text = SCHEMA_FILE.read_text("utf-8").format(
        catalog=catalog, schema=schema or raw_schema())
    body = "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("--")
    )
    for statement in body.split(";"):
        stripped = statement.strip()
        if stripped:
            cur.execute(stripped)


def param_bytes(row: tuple) -> int:
    """What this row will contribute to the statement's parameter budget."""
    return sum(len(str(value).encode("utf-8")) for value in row)


def batches(rows: list[tuple]):
    """Group rows into statements that stay inside the parameter limit.

    A row larger than the budget on its own is still yielded alone rather than
    silently dropped: it will fail, and an error naming one oversized posting
    is worth more than a load that quietly skipped it.
    """
    batch: list[tuple] = []
    size = 0
    for row in rows:
        row_size = param_bytes(row)
        if batch and (size + row_size > PARAM_BUDGET_BYTES
                      or len(batch) >= MAX_BATCH_ROWS):
            yield batch
            batch, size = [], 0
        batch.append(row)
        size += row_size
    if batch:
        yield batch


def replace_run(cur, table: str, columns: list[str], rows: list[tuple],
                run_date: str, source_filter: str | None = None) -> int:
    """Delete this run date, then insert it.

    The delete runs even when there are no rows, so a run that legitimately
    returned nothing clears a previous load of the same date rather than
    leaving it in place looking current.

    loaded_at is appended here as current_timestamp() rather than passed in,
    so no caller can forget it and no clock but the warehouse's is trusted.
    """
    where = "run_date = cast(? as date)"
    params: list = [run_date]
    if source_filter is not None:
        where += " and source = ?"
        params.append(source_filter)
    cur.execute(f"DELETE FROM {table} WHERE {where}", params)

    if not rows:
        return 0

    column_list = ", ".join(columns + ["loaded_at"])
    placeholders = ", ".join(["?"] * len(columns)) + ", current_timestamp()"
    for batch in batches(rows):
        values = ", ".join(f"({placeholders})" for _ in batch)
        flat = [value for row in batch for value in row]
        cur.execute(f"INSERT INTO {table} ({column_list}) VALUES {values}", flat)
    return len(rows)


def prune(cur, catalog: str, retain_days: int) -> None:
    """Drop run dates that have fallen out of the retention window.

    This runs daily and accumulates, so it needs a bound. The models ask two
    things of history: the latest run per posting, and the newest description
    ever fetched for it. Neither reaches further back than the life of a
    posting, so the window only has to outlive one -- thirty days does, with
    room to spare.

    The bound is real and accepted: a description fetched forty days ago is
    gone, and a posting still listed today whose text was never re-fetched
    inside the window reads as having no description. Widen the window rather
    than work around that.

    Not on the Postgres loader. The laptop database keeps the long history,
    which is where a question about last month gets answered.
    """
    raw = f"{catalog}.{raw_schema()}"
    cutoff = f"run_date < date_sub(current_date(), {int(retain_days)})"

    rows_pruned = 0
    dates_pruned: set[str] = set()

    for table in RAW_TABLES:
        cur.execute(f"SELECT run_date, count(*) FROM {raw}.{table} "
                    f"WHERE {cutoff} GROUP BY run_date")
        for run_date, count in cur.fetchall():
            rows_pruned += count
            dates_pruned.add(str(run_date))
        cur.execute(f"DELETE FROM {raw}.{table} WHERE {cutoff}")

    if rows_pruned:
        log.info("pruned %d rows across %d run dates older than %d days (%s)",
                 rows_pruned, len(dates_pruned), retain_days,
                 ", ".join(sorted(dates_pruned)))
    else:
        log.info("nothing older than %d days to prune", retain_days)


def as_json(payload: dict) -> str:
    """JSON text, unescaped. The German is stored as German."""
    return json.dumps(payload, ensure_ascii=False)


def write_run(cur, catalog: str, run) -> None:
    raw = f"{catalog}.{raw_schema()}"

    if run.manifest is not None:
        replace_run(
            cur, f"{raw}.ingest_runs", ["source", "run_date", "manifest"],
            [(run.source, run.run_date, as_json(run.load_manifest()))],
            run_date=run.run_date, source_filter=run.source,
        )

    if run.source == "arbeitsagentur":
        replace_run(
            cur, f"{raw}.arbeitsagentur_postings",
            ["source_id", "run_date", "search_term", "payload"],
            [(i, d, t, as_json(p)) for i, d, t, p in run.ag_postings],
            run_date=run.run_date,
        )
        replace_run(
            cur, f"{raw}.arbeitsagentur_details",
            ["source_id", "run_date", "payload"],
            [(i, d, as_json(p)) for i, d, p in run.ag_details],
            run_date=run.run_date,
        )
    else:
        replace_run(
            cur, f"{raw}.arbeitnow_postings",
            ["source_id", "run_date", "payload"],
            [(i, d, as_json(p)) for i, d, p in run.an_postings],
            run_date=run.run_date,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-date", help="load only this run date (YYYY-MM-DD)")
    parser.add_argument("--retain-days", type=int, default=RETAIN_DAYS,
                        help=f"days of runs to keep (default {RETAIN_DAYS}); "
                             "older run dates are deleted after loading")
    args = parser.parse_args()

    if not RAW_DIR.exists():
        log.error("no raw data at %s - run an ingest first", RAW_DIR)
        raise SystemExit(1)

    catalog = os.getenv("DATABRICKS_CATALOG", "workspace")
    postings = details = 0

    with connect() as conn, conn.cursor() as cur:
        ensure_schema(cur, catalog)
        log.info("schema ready in %s.%s", catalog, raw_schema())

        for source, run_dir in iter_runs(RAW_DIR, args.run_date):
            run = read_run(source, run_dir)
            write_run(cur, catalog, run)
            log.info("%-16s %s -> %d postings, %d details (%d duplicates collapsed)",
                     source, run.run_date, run.posting_count, run.detail_count,
                     run.duplicates)
            postings += run.posting_count
            details += run.detail_count

        prune(cur, catalog, args.retain_days)

    log.info("loaded %d postings and %d details into %s.%s",
             postings, details, catalog, raw_schema())


if __name__ == "__main__":
    main()
