# de-jobs-pipeline

A data pipeline that answers a question I actually needed answered:
**what do German data engineering job postings really ask for?**

Not opinion, not a listicle — postings pulled from Germany's official federal
job database, parsed, and counted.

> Status: work in progress. Ingest layer is in place; modelling and analysis
> are next. Findings and charts will land in this README.

## Why this project

I am moving from Oracle PL/SQL work into data engineering and needed to decide
which platform to invest in — Azure/Databricks, AWS, or GCP. Rather than guess
from blog posts, I decided to measure the market I want to enter.

## Sources

| Source | Why | Auth |
| --- | --- | --- |
| [Bundesagentur für Arbeit Jobsuche](https://github.com/bundesAPI/jobsuche-api) | Germany's official federal job database, the largest single source of German vacancies | Public client key |
| [Arbeitnow](https://www.arbeitnow.com/blog/job-board-api) | Second source, so that cross-source deduplication becomes a real problem | None |

No scraping. Both sources are public APIs, which keeps the pipeline stable and
within terms of service.

## Architecture

```
API  ->  raw JSON (immutable)  ->  Postgres  ->  dbt  ->  marts  ->  charts
```

The raw layer is never edited. Every downstream table must be reproducible
from the JSON on disk — the same discipline as a staging table you can always
replay.

```
ingest/     API clients, one per source, writing untouched responses
load/       raw JSON -> Postgres
dbt/        staging -> intermediate (dedup, skill parsing) -> marts
analysis/   charts built on the marts
```

## Running it

Requires Docker and Python 3.11 or newer (3.9 reached end of life and
lacks wheels for some of these dependencies).

```bash
cp .env.example .env
docker compose up -d                  # Postgres on localhost:5433

python3.12 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

python ingest/arbeitsagentur.py --max-pages 5 --with-details
python ingest/arbeitnow.py --max-pages 5
python load/load_raw.py
```

Raw responses land in `data/raw/<source>/<date>/`, alongside a `_manifest.json`
recording what the run actually fetched.

## Roadmap

- [x] Raw ingest from both sources, with retry, backoff and run manifests
- [x] Load raw JSON into Postgres
- [ ] Cross-source deduplication
- [ ] Skill extraction from posting text
- [ ] dbt marts: tool frequency, city breakdown, German-language requirement
- [ ] Charts and findings
- [ ] Daily orchestration with Airflow
- [ ] Port the dbt models to Databricks

## Licence

MIT
