"""The one place that chooses the warehouse connection for scripts reading the marts.

Credentials come from PG* or DATABRICKS_* env vars.

Usage:
    conn, marts = connect("databricks")
"""

from __future__ import annotations

import argparse
import os

MARTS_SCHEMA = "analytics_marts"
INTERMEDIATE_SCHEMA = "analytics_intermediate"

TARGETS = ["postgres", "databricks"]


def add_target_argument(parser: argparse.ArgumentParser) -> None:
    """Add the shared --target flag."""
    parser.add_argument(
        "--target", default=os.getenv("WAREHOUSE_TARGET", "postgres"),
        choices=TARGETS,
        help="which warehouse the marts were built in (default postgres; "
             "also read from WAREHOUSE_TARGET)",
    )


def required_env(name: str) -> str:
    """Return an env var or exit naming it. Empty counts as missing (unset CI secrets)."""
    value = os.getenv(name)
    if not value:
        raise SystemExit(
            f"{name} is not set. Locally: set -a; source .env; set +a. "
            "In CI: check the repository secret of the same name."
        )
    return value


def connect(target: str, schema: str = MARTS_SCHEMA):
    """Return (connection, qualified schema). Drivers are imported lazily."""
    if target == "postgres":
        import psycopg

        conn = psycopg.connect(
            host=os.getenv("PGHOST", "localhost"),
            port=os.getenv("PGPORT", "5433"),
            dbname=os.getenv("PGDATABASE", "jobs"),
            user=os.getenv("PGUSER", "jobs"),
            password=os.getenv("PGPASSWORD", "jobs"),
        )
        return conn, schema

    if target == "databricks":
        from databricks import sql as dbsql

        conn = dbsql.connect(
            server_hostname=required_env("DATABRICKS_HOST"),
            http_path=required_env("DATABRICKS_HTTP_PATH"),
            access_token=required_env("DATABRICKS_TOKEN"),
        )
        catalog = os.getenv("DATABRICKS_CATALOG", "workspace")
        return conn, f"{catalog}.{schema}"

    raise SystemExit(f"unknown target '{target}' - expected one of {TARGETS}")
