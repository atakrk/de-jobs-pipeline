# de-jobs-pipeline

A data pipeline that answers a question I actually needed answered:
**what do German data engineering job postings really ask for?**

Not opinion, not a listicle — postings pulled from Germany's official federal
job database, parsed, and counted.

> Status: end-to-end and running. First findings below; the numbers are a
> single snapshot and the open questions are listed with them.

## Findings

First pass: 662 postings after scope filtering and deduplication, 414 of them
carrying a description long enough to read requirements from. Numbers below are
a snapshot, not a settled answer — see [Caveats](#caveats).

### Which tools the market asks for

![Tools named in German data engineering postings](analysis/charts/skill_frequency.png)

Python (56.5%) and SQL (55.1%) are the floor, as expected. The interesting part
is the cloud split:

| | share of postings |
| --- | --- |
| Azure | **32.4%** |
| AWS | 22.0% |
| Google Cloud | 12.8% |

Azure appears roughly one and a half times as often as AWS, and Google Cloud
trails both — consistent with DACH enterprises being Microsoft shops before
they are cloud shops. Databricks (16.7%) sits ahead of both dbt and Snowflake
(14.7% each), and Spark's 17.6% largely travels with it.

Read the percentages as a share of all postings, not as market share between
clouds: most postings name no cloud at all, so among those that do, Azure's
lead is wider than the table suggests.

### How much of the market is gated on German

![How much of the market is gated on German](analysis/charts/language_requirement.png)

44.3% of federal postings state an explicit German-language requirement. 29.5%
of all postings mention English without stating a German requirement.

The two sources disagree sharply and both numbers are worth distrusting on
their own: the federal database is the whole German market, while Arbeitnow is
a self-selected set of internationally-oriented employers. Neither is
representative alone.

### What the roles advertise

Median advertised salary clusters at **€65,000–80,000**. Per-tool differences
in `mart_salary_by_skill` are not meaningful at these sample sizes — between
four and twenty-one postings per tool — and the table reports its sample size
beside every figure for exactly that reason.

Fewer than one posting in five states a salary at all, and those that do skew
public sector and large employers.

### Caveats

- **Description coverage is 600 of 1,660 postings.** Skill counts describe
  roughly a third of what was collected.
- **The German figure is a floor.** Only explicit competency phrases are
  counted. A posting written in German that states no requirement but expects
  German is invisible to this measure, and there are certainly many.
- **Deduplication is approximate.** No shared identifier exists across sources,
  so the key is employer plus title.
- **One snapshot, one day.** Nothing here says anything about a trend yet.

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

cd dbt
dbt seed --profiles-dir .
dbt build --profiles-dir .
cd ..

python analysis/make_charts.py
```

Raw responses land in `data/raw/<source>/<date>/`, alongside a `_manifest.json`
recording what the run actually fetched.

## Roadmap

- [x] Raw ingest from both sources, with retry, backoff and run manifests
- [x] Load raw JSON into Postgres
- [x] Cross-source deduplication
- [x] Skill extraction from posting text
- [x] dbt marts: tool frequency, city breakdown, German-language requirement
- [x] Charts and findings
- [ ] Daily orchestration with Airflow
- [ ] Port the dbt models to Databricks

## Licence

MIT
