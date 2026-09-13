"""A synthetic raw dataset, and a dump of every model built from it.

This exists because "it still builds" proves nothing about a rewrite. Every
plausible way to express these models compiles, and a wrong one returns fewer
rows rather than an error -- which is how the Databricks port would have
shipped a silent change to the salary columns.

So a port or a refactor is checked by building both versions against the same
rows and diffing the output:

    python scripts/fixture.py --load --dump /tmp/before   # on the old code
    git stash                                             # or checkout the change
    python scripts/fixture.py --dump /tmp/after
    diff -r /tmp/before /tmp/after

The rows are chosen to hit the expressions that are easy to get wrong, not to
look like a realistic sample: nested and missing JSON keys, empty strings that
must become null, epoch and boolean casts, a title that must match ("BI
Spezialist") beside one that must not ("Bildredakteur", which is the whole
reason 'bi' carries a word boundary the other alternatives do not), a posting
outside Germany, and the same vacancy under two sources so deduplication has
something to do.

It also runs on either engine, which is what makes it usable as a CI gate.
Once production holds thirty days on Databricks and a CI Postgres holds one,
the two cannot be compared on real data -- different inputs. These rows are the
only input both can be given identically.

    python scripts/fixture.py --load --dump /tmp/pg
    python scripts/fixture.py --target databricks --load --dump /tmp/db
    diff -r /tmp/pg /tmp/db

This truncates the raw tables it writes to. Point it at the local Postgres or
at a throwaway schema, never at one holding a real run -- RAW_SCHEMA and
DATABRICKS_SCHEMA exist so the Databricks side can be sent somewhere harmless.

Recovering the local Postgres afterwards takes a truncate, not just a reload:
the loaders upsert, so re-running one leaves these synthetic rows sitting
beside the real ones and every count three too high.

    psql -c 'truncate raw.arbeitsagentur_postings, raw.arbeitsagentur_details,
             raw.arbeitnow_postings, raw.ingest_runs'
    python load/load_raw.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "load"))

RUN = "2026-09-12"

RAW_TABLES = ["arbeitsagentur_postings", "arbeitsagentur_details",
              "arbeitnow_postings"]

# (layer, table). The schema is <prefix>_<layer>, and the prefix moves with
# DATABRICKS_SCHEMA so a fixture build can be sent away from production.
MODELS = [
    ("staging", "stg_arbeitsagentur__postings"),
    ("staging", "stg_arbeitsagentur__details"),
    ("staging", "stg_arbeitnow__postings"),
    ("intermediate", "int_german_cities"),
    ("intermediate", "int_arbeitnow_geo"),
    ("intermediate", "int_postings"),
    ("intermediate", "int_posting_skills"),
    ("marts", "mart_skill_frequency"),
    ("marts", "mart_salary_by_skill"),
    ("marts", "mart_city_stats"),
    ("marts", "mart_language_requirement"),
]

DESC_DE = (
    "Wir suchen eine Data Engineer. Aufgaben: Aufbau von Pipelines mit Python und SQL, "
    "Betrieb einer PostgreSQL-Datenbank, Modellierung im Data Warehouse mit dbt, "
    "Orchestrierung mit Airflow auf Azure. Erfahrung mit Spark und Kafka von Vorteil. "
    "Sehr gute Deutschkenntnisse in Wort und Schrift sind erforderlich, English is a plus."
)
DESC_EN = (
    "We are looking for an Analytics Engineer. You will build ELT pipelines using dbt, "
    "Snowflake and Airflow, and maintain dashboards in Power BI and Tableau. "
    "Strong SQL skills required. Experience with AWS or Google Cloud is welcome. "
    "Working language is English; this is a fully remote role within Germany."
)
DESC_STUB = "Kurze Anzeige ohne Details."


def address(ort, plz, region, land):
    return {"adresse": {"ort": ort, "plz": plz, "region": region, "land": land}}


AG_POSTINGS = [
    ("ag1", "data engineer", {
        "stellenangebotsTitel": "Data Engineer (m/w/d)", "hauptberuf": "Informatiker",
        "firma": "Muster GmbH", "stellenangebotsart": "ARBEIT", "vertragsdauer": "UNBEFRISTET",
        "arbeitszeitVollzeit": True, "quereinstiegGeeignet": False,
        "gehaltsspanneVon": "55000", "gehaltsspanneBis": "72000", "verguetungsangabe": "JAHR",
        "stellenlokationen": [address("Berlin", "10115", "Berlin", "DEUTSCHLAND"),
                              address("Hamburg", "20095", "Hamburg", "DEUTSCHLAND")],
        "datumErsteVeroeffentlichung": "2026-09-01",
        "aenderungsdatum": "2026-09-05T08:30:00",
    }),
    # empty strings must become null, not zero
    ("ag2", "data engineering", {
        "stellenangebotsTitel": "BI Spezialist", "firma": "Beta AG",
        "gehaltsspanneVon": "", "gehaltsspanneBis": "",
        "stellenlokationen": [address("München", "80331", "Bayern", "DEUTSCHLAND")],
        "datumErsteVeroeffentlichung": "2026-09-02", "aenderungsdatum": "",
    }),
    # 'bi' inside a word: must stay out of scope
    ("ag3", "data engineer", {
        "stellenangebotsTitel": "Bildredakteur", "firma": "Gamma KG",
        "stellenlokationen": [address("Köln", "50667", "NRW", "DEUTSCHLAND")],
        "datumErsteVeroeffentlichung": "2026-09-03",
    }),
    # in scope by title, outside Germany
    ("ag4", "analytics engineer", {
        "stellenangebotsTitel": "Analytics Engineer", "firma": "Delta GmbH",
        "stellenlokationen": [address("Wien", "1010", "Wien", "OESTERREICH")],
        "datumErsteVeroeffentlichung": "2026-09-04",
    }),
    # no location array at all
    ("ag5", "data engineer", {
        "stellenangebotsTitel": "Data Warehouse Entwickler", "firma": "Epsilon SE",
        "datumErsteVeroeffentlichung": "2026-09-05",
    }),
]

AG_DETAILS = [
    ("ag1", {"stellenangebotsBeschreibung": DESC_DE, "homeofficemoeglich": True,
             "istArbeitnehmerUeberlassung": False,
             "istPrivateArbeitsvermittlung": False, "vertragsdauer": "UNBEFRISTET"}),
    ("ag2", {"stellenangebotsBeschreibung": DESC_EN, "homeofficemoeglich": False,
             "istArbeitnehmerUeberlassung": True}),
    ("ag3", {"stellenangebotsBeschreibung": DESC_STUB}),
    ("ag4", {"stellenangebotsBeschreibung": DESC_EN}),
]

AN_POSTINGS = [
    ("an1", {"title": "Senior Data Engineer", "company_name": "Zeta Tech",
             "description": DESC_EN, "location": "Berlin, Germany", "remote": True,
             "url": "https://example.invalid/1", "created_at": "1788912000"}),
    # explicit foreign marker
    ("an2", {"title": "Data Analyst", "company_name": "Eta Ltd",
             "description": DESC_EN, "location": "London, United Kingdom", "remote": False,
             "url": "https://example.invalid/2", "created_at": "1788912000"}),
    # genuinely unknown location
    ("an3", {"title": "Analytics Engineer", "company_name": "Theta BV",
             "description": DESC_EN, "location": "Europe - Remote", "remote": True,
             "url": "https://example.invalid/3", "created_at": "1788912000"}),
    # same vacancy as ag1, syndicated
    ("an4", {"title": "Data Engineer (m/w/d)", "company_name": "Muster GmbH",
             "description": DESC_EN, "location": "Berlin", "remote": False,
             "url": "https://example.invalid/4", "created_at": "1788912000"}),
]


def raw_schema() -> str:
    return os.getenv("RAW_SCHEMA", "raw")


def model_prefix(target: str) -> str:
    if target == "databricks":
        return os.getenv("DATABRICKS_SCHEMA", "analytics")
    return "analytics"


def qualify(target: str, schema: str) -> str:
    """Databricks needs the catalog; Postgres must not be given one."""
    if target == "databricks":
        return f"{os.getenv('DATABRICKS_CATALOG', 'workspace')}.{schema}"
    return schema


def connect(target: str):
    """A connection and its placeholder, which the two drivers spell apart."""
    if target == "postgres":
        import psycopg

        conn = psycopg.connect(
            host=os.getenv("PGHOST", "localhost"),
            port=os.getenv("PGPORT", "5433"),
            dbname=os.getenv("PGDATABASE", "jobs"),
            user=os.getenv("PGUSER", "jobs"),
            password=os.getenv("PGPASSWORD", "jobs"),
        )
        return conn, "%s"

    if target == "databricks":
        from databricks import sql as dbsql

        conn = dbsql.connect(
            server_hostname=os.environ["DATABRICKS_HOST"],
            http_path=os.environ["DATABRICKS_HTTP_PATH"],
            access_token=os.environ["DATABRICKS_TOKEN"],
        )
        return conn, "?"

    raise SystemExit(f"unknown target '{target}' - expected postgres or databricks")


def load(target: str) -> None:
    root = Path(__file__).resolve().parents[1]
    raw = qualify(target, raw_schema())

    conn, ph = connect(target)
    with conn, conn.cursor() as cur:
        if target == "databricks":
            # Reuse the loader's applier rather than re-splitting the file: it
            # already knows that a semicolon inside a comment is not the end of
            # a statement.
            from load_raw_databricks import ensure_schema

            ensure_schema(cur, os.getenv("DATABRICKS_CATALOG", "workspace"))
        else:
            cur.execute((root / "load" / "schema.sql").read_text("utf-8"))

        for table in RAW_TABLES:
            cur.execute(f"truncate table {raw}.{table}")

        def clause(columns: list[str]) -> str:
            """Delta has no column defaults: loaded_at is NOT NULL and an
            INSERT that omits it is rejected, where Postgres fills it in."""
            names, values = list(columns), [ph] * len(columns)
            if target == "databricks":
                names.append("loaded_at")
                values.append("current_timestamp()")
            return f"({', '.join(names)}) values ({', '.join(values)})"

        rows = [
            (f"{raw}.arbeitsagentur_postings",
             clause(["source_id", "run_date", "search_term", "payload"]),
             [(i, RUN, term, json.dumps(payload)) for i, term, payload in AG_POSTINGS]),
            (f"{raw}.arbeitsagentur_details",
             clause(["source_id", "run_date", "payload"]),
             [(i, RUN, json.dumps(payload)) for i, payload in AG_DETAILS]),
            (f"{raw}.arbeitnow_postings",
             clause(["source_id", "run_date", "payload"]),
             [(i, RUN, json.dumps(payload)) for i, payload in AN_POSTINGS]),
        ]
        for table, insert, values in rows:
            for value in values:
                cur.execute(f"insert into {table} {insert}", list(value))

        if target == "postgres":
            conn.commit()

    print(f"fixture loaded into {raw}: {len(AG_POSTINGS)} postings, "
          f"{len(AG_DETAILS)} details, {len(AN_POSTINGS)} board rows")


def build(target: str) -> None:
    root = Path(__file__).resolve().parents[1] / "dbt"
    dbt_target = "dev" if target == "postgres" else target
    subprocess.run(["dbt", "build", "--profiles-dir", ".", "--target", dbt_target],
                   cwd=root, check=True)


def dump(target: str, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    prefix = model_prefix(target)
    conn, _ = connect(target)
    with conn, conn.cursor() as cur:
        for layer, table in MODELS:
            schema = qualify(target, f"{prefix}_{layer}")
            cur.execute(f"select * from {schema}.{table}")
            # By position: psycopg returns Column objects, the Databricks
            # connector returns tuples.
            columns = [d[0] for d in cur.description]
            lines = ["|".join(columns)]
            rendered = [
                ["NULL" if v is None else str(v).replace("\n", " ") for v in row]
                for row in cur.fetchall()
            ]
            # Sorted on every column, not on the first. Ordering by one column
            # leaves ties to the engine, and int_posting_skills has several
            # rows per posting -- which showed up as a diff with no difference
            # in it the first time these two dumps were compared.
            for row in sorted(rendered):
                lines.append("|".join(row))
            (out / f"{table}.csv").write_text("\n".join(lines) + "\n", "utf-8")
    print(f"dumped {len(MODELS)} models to {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--load", action="store_true",
                        help="replace the raw tables with the fixture")
    parser.add_argument("--build", action="store_true",
                        help="run dbt build before dumping")
    parser.add_argument("--dump", type=Path, help="write one CSV per model here")
    parser.add_argument("--target", default="postgres",
                        choices=["postgres", "databricks"],
                        help="which engine to load, build and dump (default postgres)")
    args = parser.parse_args()

    if not (args.load or args.build or args.dump):
        parser.error("nothing to do: pass --load, --build and/or --dump")
    if args.load:
        load(args.target)
    if args.build or args.dump:
        build(args.target)
    if args.dump:
        dump(args.target, args.dump)


if __name__ == "__main__":
    main()
