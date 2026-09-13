"""One connection helper for everything that reads the marts.

The models are single-source across Postgres and Databricks, and so is the
loader's reader. The analysis scripts were the exception: three copies of the
same `connect()`, each hardcoding `analytics_marts` in its SQL. Giving each of
them a second connection path would have made that six.

So the choice of warehouse lives here, once. Callers ask for a connection and
the schema to qualify the marts with, and nothing else about them changes --
which is the point. A chart built from Databricks has to be the same chart.

    conn, marts = connect("databricks")
    with conn, conn.cursor() as cur:
        cur.execute(f"select * from {marts}.mart_skill_frequency")

Postgres credentials come from PG*; Databricks from DATABRICKS_*, which are
read from the environment and never from a file this code opens.
"""

from __future__ import annotations

import argparse
import os

MARTS_SCHEMA = "analytics_marts"
INTERMEDIATE_SCHEMA = "analytics_intermediate"

TARGETS = ["postgres", "databricks"]


def add_target_argument(parser: argparse.ArgumentParser) -> None:
    """The same flag, spelled the same way, in every script that reads marts."""
    parser.add_argument(
        "--target", default=os.getenv("WAREHOUSE_TARGET", "postgres"),
        choices=TARGETS,
        help="which warehouse the marts were built in (default postgres; "
             "also read from WAREHOUSE_TARGET)",
    )


def required_env(name: str) -> str:
    """A missing credential should say which one.

    Empty counts as missing: an unset GitHub secret interpolates to an empty
    string rather than disappearing, and an empty hostname reaches the driver
    as a URL it tries to negotiate OAuth against. The resulting error names
    neither the variable nor the workflow.

    load/load_raw_databricks.py keeps its own copy: load/ does not import from
    analysis/, and one small function in each beats a dependency between them.
    """
    value = os.getenv(name)
    if not value:
        raise SystemExit(
            f"{name} is not set. Locally: set -a; source .env; set +a. "
            "In CI: check the repository secret of the same name."
        )
    return value


def connect(target: str, schema: str = MARTS_SCHEMA):
    """A connection, and the qualified schema to read from.

    Drivers are imported inside the branch so that running against one engine
    does not require the other's driver to be installed.
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
