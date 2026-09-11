# de-jobs-pipeline

A data pipeline that answers a question I actually needed answered:
**what do German data engineering job postings really ask for?**

Not opinion, not a listicle — postings pulled from Germany's official federal
job database, parsed, and counted.

> Status: end-to-end and running. First findings below; the numbers are a
> single snapshot and the open questions are listed with them.

## Findings

633 postings after scope filtering, location validation and deduplication,
627 of them carrying a description long enough to read requirements from.
Numbers below are a snapshot — see [Caveats](#caveats).

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

**40%** state an explicit German-language requirement. **31%** mention English
without stating one. The remaining **28%** say nothing about language either
way — which is not evidence of either, and is shown separately rather than
folded into the friendlier number.

The federal figure on its own is 41.0%. The second source is too small after
location validation to report separately, and the mart suppresses per-source
rows below thirty postings for that reason.

### Caveats

- **The German figure is a floor.** Only explicit competency phrases are
  counted. A posting written in German that states no requirement but expects
  German is invisible to this measure, and there are many.
- **Percentages moved by 3–7 points between runs.** An earlier, smaller sample
  was not a random subset — it was the first *n* postings in search order,
  which over-weighted the most tool-dense search term. Directions held;
  magnitudes did not. Treat single-point percentages as approximate.
- **Deduplication turned out to be a minor effect**, and it was audited rather
  than assumed: `analysis/dedup_audit.sql` splits the funnel. The role filter
  removes 1,596 rows; deduplication merges 32. The large reduction is the
  scope filter doing its job, since the API's search is fuzzy and returns
  loosely related postings.
- **The second source is DACH/EU-wide, not German**, and states no country.
  Across its full feed, 224 postings resolve as foreign, 213 as German and 157
  as unknown. Locations are validated against German place names taken from
  the federal database itself, and only verified-German rows are kept — twelve
  of them. Everything here is the German market by construction, not by
  assumption.
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
dbt/        staging -> intermediate (dedup, geo, skill parsing) -> marts
analysis/   charts, snapshot export, and the audits behind two decisions
```

It runs itself. A [scheduled workflow](.github/workflows/daily.yml) ingests,
loads, builds and tests every morning, then commits the marts as dated CSVs
under `data/snapshots/`. A CI database is created and destroyed with the job,
so the history lives in git instead — and those files accumulate into the time
series a single run can never produce.

The schedule is not really about fresh data. It is that dbt's tests run daily
against a live third-party API: if the source changes shape, the build goes
red and says so, rather than the numbers quietly drifting.

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
- [x] Daily scheduled run, with dbt's tests running against the live API
- [ ] Airflow, if and when the job stops being one linear sequence
- [ ] Port the dbt models to Databricks

## Licence

MIT
