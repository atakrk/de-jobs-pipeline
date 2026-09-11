# de-jobs-pipeline

A data pipeline that answers a question I actually needed answered:
**what do German data engineering job postings really ask for?**

Not opinion, not a listicle — postings pulled from Germany's official federal
job database, parsed, and counted.

> Status: end-to-end and running. First findings below; the numbers are a
> single snapshot and the open questions are listed with them.

## Findings

669 postings after scope filtering and deduplication, 663 of them carrying a
description long enough to read requirements from. Numbers below are a
snapshot — see [Caveats](#caveats).

### Which tools the market asks for

![Tools named in German data engineering postings](analysis/charts/skill_frequency.png)

Python (49.3%) and SQL (47.5%) are the floor. The cloud split is the part worth
reading closely:

| | share of postings |
| --- | --- |
| Azure | **28.8%** |
| AWS | 20.2% |
| Google Cloud | 13.6% |

Azure leads AWS by roughly **1.4×**. That ratio is the finding, not the
absolute percentages: an earlier run over a third of this sample produced
32.4% / 22.0% / 12.8% — different numbers, the same 1.4× gap. Databricks was
similarly stable across both runs (16.7% then 16.4%).

Two results look distinctly German. **SAP appears in 12.8%** of postings, and
**Power BI in 16.3%** — ranking above Spark, dbt and Airflow. A US-based
dataset would not produce that shape. It suggests a large share of what
Germany labels "data engineering" is Microsoft-stack BI work sitting close to
SAP systems, which is a different job from the one the title implies
elsewhere.

Read the percentages as a share of all postings, not as market share between
clouds: most postings name no cloud at all, so among those that do, Azure's
lead is wider than the table suggests.

### How much of the market is gated on German

![How much of the market is gated on German](analysis/charts/language_requirement.png)

**41.0%** of federal postings state an explicit German-language requirement.
**215 of 663 postings (32.4%)** mention English without stating one.

The two sources disagree sharply and neither is representative alone: the
federal database is the whole German market, while Arbeitnow is a self-selected
set of internationally-oriented employers.

### Caveats

- **The German figure is a floor.** Only explicit competency phrases are
  counted. A posting written in German that states no requirement but expects
  German is invisible to this measure, and there are many.
- **Percentages moved by 3–7 points between runs.** An earlier, smaller sample
  was not a random subset — it was the first *n* postings in search order,
  which over-weighted the most tool-dense search term. Directions held;
  magnitudes did not. Treat single-point percentages as approximate.
- **Deduplication is approximate.** No shared identifier exists across sources,
  so the key is employer plus title. 1,660 unique federal postings reduce to
  669 after the role filter and deduplication together, and that split has not
  been measured.
- **One snapshot.** Two run dates are now stored, which is not yet a trend.

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
