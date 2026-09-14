# Working in this repository

A pipeline that measures what German data engineering job postings ask for.
Two public job APIs, modelled with dbt, running daily on GitHub Actions into
Databricks; Postgres is the local copy and the same models build on both. The
README holds the findings; this file holds the conventions.

## Layout

```
ingest/     API clients, one per source. Write untouched responses only.
load/       raw JSON -> warehouse. No reshaping here.
              rows.py reads a run; one writer per platform.
dbt/        staging -> intermediate -> marts
              macros/dialect.sql holds every per-platform difference
              int_postings_scored keeps every row and why it survives;
              int_postings is that model filtered
analysis/   charts, snapshot export, and audits kept next to what they audit
```

## Running it

```bash
source .venv/bin/activate          # Python 3.12
docker compose up -d               # Postgres on localhost:5433
python ingest/arbeitsagentur.py --max-pages 10 --with-details --detail-limit 1660
python ingest/arbeitnow.py --max-pages 5
python load/load_raw.py
cd dbt && dbt build --profiles-dir .
cd .. && python analysis/make_charts.py
```

Same data on Databricks, which is what the daily run writes to — credentials
come from `.env`, which is gitignored and never pasted anywhere:

```bash
set -a; source .env; set +a
python load/load_raw_databricks.py
cd dbt && dbt build --profiles-dir . --target databricks
```

dbt needs `--profiles-dir .` — `profiles.yml` lives in the repo, not `~/.dbt`.

## Conventions that are decisions, not habits

**The raw layer is immutable and unflattened.** API responses land as `jsonb`
exactly as returned. Field mapping happens in dbt, where it is versioned and
reviewable, never in the Python loader. Everything downstream must be
reproducible from the JSON on disk.

**Grain is `(source_id, run_date)`.** Reruns of a day update in place; days
accumulate. Do not collapse this to one row per posting. The grain is enforced
in `load/rows.py`, where both loaders read, and not by the Postgres primary
key: a run legitimately reads the same posting several times — the federal API
answers once per search term — and for a long time only the upsert was
collapsing those. Delta has no primary key, so the same files landed a fifth
heavier there. A guarantee that only one platform provides is an accident.

**Databricks keeps thirty days; the laptop keeps everything.** The warehouse is
written to daily, so `load_raw_databricks.py --retain-days` bounds it and
deletes older run dates after loading, logging what went. The models ask two
things of history — the latest run per posting, and the newest description
ever fetched for it — and neither reaches past the life of a posting, so the
window only has to outlive one. The bound is real: a description fetched forty
days ago is gone, and a posting whose text was never re-fetched inside the
window reads as having none. Widen the window rather than work around that.
The Postgres loader does not prune; a question about last month is answered
locally.

**Seven days of freshness, thirty of retention, and they are not the same
number.** `posting_freshness_days` in `dbt_project.yml` defines *currently
advertised*: `int_postings` keeps only postings seen in a run within that
window. Retention bounds what the warehouse stores; freshness bounds what
counts as a vacancy. A posting last seen three weeks ago has been filled, and
counting it would make the published total climb every morning while the market
stands still — which is exactly what would have happened the day the warehouse
started accumulating, because on a one-day database "last seen" and "seen
lately" are the same sentence.

The window is measured against the newest run in the data, not against today.
A schedule that fails for three days must not shrink the dataset, and the
fixture carries one fixed run date — measured against the clock it would empty
itself a week after it was written and take the parity gate with it. It is
also measured across both sources, not per source, so a dead feed shows up as
a falling count instead of hiding behind healthy-looking figures.

**Anything that picks one row must order totally.** `row_number()` over an
ordering with ties leaves the winner to the engine, and two engines choose
differently — one employer advertising the same title in two cities was enough
to make the city counts disagree. Fall through to something unique. An
arbitrary winner is fine; an irreproducible one is not.

**Skill patterns live in `dbt/seeds/skills.csv`, never in SQL.** Adding a tool
is a data change. Patterns match with word boundaries — without them `sql`
matches inside `postgresql`. Write the boundary through `imatch_word` or
`match_word_expr`, never inline: the spelling differs per platform.

**Every rate carries its denominator.** `mart_skill_frequency` reports
`postings_with_text` beside every percentage. `mart_salary_by_skill` suppresses
any tool under three observations. `mart_language_requirement` suppresses
per-source rows under thirty postings. Do not remove these guards to make a
table look fuller.

**Never assert a value the source did not give.** Two bugs in this project came
from that: a hardcoded country on a source that states none, and then a filter
that permitted null and admitted London and Paris into a German dataset.
Unknown is a real outcome — model it, exclude it deliberately, and count it.

**Any limit that truncates an ordered list is a sampling decision.** Shuffle
before truncating, and record the limit and the method in the run manifest.
`--detail-limit` silently skewed every published percentage twice before this
rule existed.

**Do not scrape.** Both sources are public APIs. Keep it that way: no
LinkedIn, no Indeed, no headless browsers.

**The models are single-source across platforms.** They run on Postgres and on
Databricks from the same files. Anything the two spell differently — JSON
access, regex, word boundaries, numeric types — goes in `dbt/macros/dialect.sql`
behind a `target.type` branch that raises on an unknown adapter. Do not fork a
model, and do not inline platform syntax "just this once".

**A port is verified by diffing output, not by building.** Every plausible
rewrite compiles, and a wrong one returns fewer rows rather than an error.

`scripts/fixture.py --target` loads the same synthetic rows into either engine
and dumps every model, and the `parity` workflow diffs the two on any change
to `dbt/models/**` or `dbt/macros/**`. It builds into `fixture_raw` and
`fixture_*` so it cannot reach the tables holding real runs.

`scripts/compare_targets.py` does the same on the real marts, and is only
meaningful when both engines hold the same runs. They no longer do by default:
Databricks accumulates what the schedule ingests, and those raw files never
reach a laptop. Load the same run directories into both first, or read its
output as a statement about the data rather than about the engines — the two
failures that mattered were a grain nobody had written down and two real
postings that tie, and a fixture can contain neither, so it is still worth
setting up deliberately when a dialect macro changes.

**The funnel is the model, counted.** `mart_pipeline_funnel` reports every
stage from rows read to the published denominator, and every stage after the
first counts `int_postings_scored` — the model `int_postings` filters. Do not
re-derive a filter to count it. Four hand-copied reconstructions of the scope
rules in `analysis/dedup_audit.sql` had all gone stale before anyone looked,
and that file was never published to anyone.

**Do not disable TLS verification.** Community docs for the federal API suggest
it. The handshake works fine.

## Things deliberately not built

- **Airflow** — this is one linear sequence on a timer, which is what cron is
  for. Revisit only if the job stops being one sequence.
- **Kafka** — the data is batch. Nothing streams.
- **A web framework for the personal site** — separate repo, one static file
  on purpose.

Adding any of these because they look good on a CV is the failure mode this
project is explicitly avoiding.

## Commit messages

Explain why, not what — the diff shows what. When a change reverses an earlier
decision, say what changed in the evidence. Several commits here read as short
postmortems; match that register rather than "fix bug".

Do not add Co-Authored-By or any assistant attribution. Commits are Ata's.

## Before publishing a number

The README is the deliverable, and a wrong percentage in it is worse than a
broken build. Anything published needs its denominator, its sample size, and a
caveat where the measurement is a floor rather than a ceiling.
