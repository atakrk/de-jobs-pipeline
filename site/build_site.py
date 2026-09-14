"""Generate docs/index.html from the pipeline's daily snapshots.

The site is static: no backend, no database, no API. Every figure it shows comes
from the CSVs the pipeline commits to de-jobs-pipeline under
data/snapshots/<date>/, which means the site can only ever show numbers that are
already in a public repository, traceable to the run that produced them.

Every day is compiled, not just the newest, because the point of a site that
runs continuously is the series. The latest day answers "what does the market
ask for"; the days behind it answer "and is that changing".

The data is written into the page between markers rather than served beside it,
so the published page is one self-contained document: no fetch to fail, no
request that can 404, nothing to keep in sync. site/template.html is the source
and is the only file edited by hand; docs/index.html is a build artifact and
anything typed into it is lost on the next run.

Run it in the same job that produced the snapshots, never on its own
schedule: a site rebuilt separately is a site that can quietly publish
yesterday's numbers while looking current.

    python site/build_site.py
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_SNAPSHOTS = ROOT / "data" / "snapshots"
DEFAULT_PROJECT = ROOT / "dbt" / "dbt_project.yml"
TEMPLATE = HERE / "template.html"
OUTPUT = ROOT / "docs" / "index.html"

START = "<!-- DATA:START -->"
END = "<!-- DATA:END -->"

# Which columns are numbers. Everything else stays a string, and an empty cell
# stays null rather than becoming zero -- a suppressed median is not a salary of
# nothing, and the site has to be able to tell those apart.
NUMERIC = {
    "postings", "postings_with_text", "pct_of_postings",
    "postings_with_salary", "median_salary_from", "median_salary_to",
    "min_salary_from", "max_salary_to",
    "home_office_postings", "requires_german", "mentions_english",
    "english_without_german", "pct_requires_german", "pct_english_without_german",
    "stage_order", "records", "pct_of_previous", "pct_of_first", "dropped",
}

MARTS = [
    "mart_skill_frequency",
    "mart_language_requirement",
    "mart_city_stats",
    "mart_salary_by_skill",
    "mart_pipeline_funnel",
]

# Marts the page can do without. A mart added today does not exist in the
# snapshots taken before it, and requiring it would drop every one of those
# days -- so the series the site is built to show would be erased on the
# morning a new table was added, and rebuilt only after enough runs had
# passed. The page hides the sections it has no data for instead.
OPTIONAL_MARTS = {"mart_pipeline_funnel"}


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        rows = []
        for row in csv.DictReader(handle):
            clean = {}
            for key, value in row.items():
                if value is None or value == "":
                    clean[key] = None
                elif key in NUMERIC:
                    clean[key] = float(value) if "." in value else int(value)
                else:
                    clean[key] = value
            rows.append(clean)
        return rows


def read_day(day_dir: Path) -> dict | None:
    """One day's marts, or None if the run did not produce the required ones.

    Optional marts are skipped rather than fatal: see OPTIONAL_MARTS.
    """
    day = {}
    for mart in MARTS:
        path = day_dir / f"{mart}.csv"
        if not path.exists():
            if mart in OPTIONAL_MARTS:
                continue
            return None
        day[mart.removeprefix("mart_")] = read_csv(path)
    return day


def read_freshness_days(project: Path) -> int | None:
    """How long a posting keeps counting after it was last seen.

    Read from the pipeline's own dbt_project.yml rather than repeated here.
    The site states this number in prose, and a site that says seven while the
    models use fourteen is worse than a site that says nothing -- so it is read
    from the one place that decides it, or left out entirely.
    """
    if not project.exists():
        return None
    match = re.search(r"^\s*posting_freshness_days:\s*(\d+)\s*$",
                      project.read_text(encoding="utf-8"), re.MULTILINE)
    return int(match.group(1)) if match else None


def compile_data(snapshots: Path, freshness_days: int | None = None) -> dict:
    days = {}
    for day_dir in sorted(p for p in snapshots.iterdir() if p.is_dir()):
        parsed = read_day(day_dir)
        if parsed is not None:
            days[day_dir.name] = parsed

    if not days:
        raise SystemExit(f"no complete snapshots under {snapshots}")

    dates = sorted(days)
    latest = days[dates[-1]]

    # The denominator every percentage on the page is a share of. It is read
    # from the data rather than restated, so the page cannot drift from it.
    overall = next(
        row for row in latest["language_requirement"] if row["population"] == "ALL"
    )

    return {
        "generated_at": date.today().isoformat(),
        "freshness_days": freshness_days,
        "latest_date": dates[-1],
        "first_date": dates[0],
        "days_tracked": len(dates),
        "postings": overall["postings"],
        "latest": latest,
        # Only what a trend needs, so the page stays small as days accumulate.
        "history": [
            {
                "date": d,
                "postings": next(
                    r for r in days[d]["language_requirement"]
                    if r["population"] == "ALL"
                )["postings"],
                "pct_requires_german": next(
                    r for r in days[d]["language_requirement"]
                    if r["population"] == "ALL"
                )["pct_requires_german"],
                "skills": {
                    r["skill_key"]: r["pct_of_postings"]
                    for r in days[d]["skill_frequency"]
                },
            }
            for d in dates
        ],
    }


def render(data: dict) -> None:
    page = TEMPLATE.read_text(encoding="utf-8")
    block = (
        f'{START}\n<script id="data" type="application/json">\n'
        f'{json.dumps(data, ensure_ascii=False, separators=(",", ":"))}\n'
        f'</script>\n{END}'
    )
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(page):
        raise SystemExit(f"{TEMPLATE.name} has no {START} / {END} block to fill")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(pattern.sub(lambda _: block, page, count=1), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", type=Path, default=DEFAULT_SNAPSHOTS,
                        help="the pipeline's data/snapshots directory")
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT,
                        help="the pipeline's dbt_project.yml, for the freshness window")
    args = parser.parse_args()

    if not args.snapshots.exists():
        raise SystemExit(f"no snapshots directory at {args.snapshots}")

    data = compile_data(args.snapshots, read_freshness_days(args.project))
    render(data)
    print(f"{OUTPUT.relative_to(ROOT)}: {data['days_tracked']} day(s), "
          f"latest {data['latest_date']}, {data['postings']} postings")


if __name__ == "__main__":
    main()
