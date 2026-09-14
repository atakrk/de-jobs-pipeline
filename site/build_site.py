"""Generate dedata.dev from the pipeline's daily snapshots.

The site is static: no backend, no database, no API. Every figure it shows comes
from the CSVs the pipeline commits to de-jobs-pipeline under
data/snapshots/<date>/, which means the site can only ever show numbers that are
already in a public repository, traceable to the run that produced them.

Every day is compiled, not just the newest, because the point of a site that
runs continuously is the series. The latest day answers "what does the market
ask for"; the days behind it answer "and is that changing".

The figures are written into the markup here, not drawn by the browser. The page
used to arrive with no numbers in it and a script that put them there, which is
a page with no numbers to anything that does not run scripts -- a search
crawler, a link preview, a model reading the web. What the site has that the
pages already ranking for the subject do not is a number, so the number has to
be in the HTML. The script left in the page filters and expands rows that are
already there; it never writes a figure. The data is still embedded beside the
markup, between the same kind of marker, because the tooltips read from it.

site/template.html is the source and the only page file edited by hand. What
this writes into docs/ is a build artifact, and anything typed into one is lost
on the next run: index.html, sitemap.xml, llms.txt and og.png. robots.txt,
favicon.svg and CNAME are hand-written, and nothing here touches them.

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
import shutil
import struct
from datetime import date
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_SNAPSHOTS = ROOT / "data" / "snapshots"
DEFAULT_PROJECT = ROOT / "dbt" / "dbt_project.yml"
TEMPLATE = HERE / "template.html"
DOCS = ROOT / "docs"
OUTPUT = DOCS / "index.html"
SITEMAP = DOCS / "sitemap.xml"
LLMS = DOCS / "llms.txt"
OG_IMAGE = DOCS / "og.png"
# The chart the same run drew. Copied next to the page rather than linked from
# the repository, so a link preview does not depend on a second host.
CHART = ROOT / "analysis" / "charts" / "skill_frequency.png"

SITE_URL = "https://dedata.dev/"
REPO_URL = "https://github.com/atakrk/de-jobs-pipeline"
RAW_URL = "https://raw.githubusercontent.com/atakrk/de-jobs-pipeline/main"

# Several organisations are already called dedata, and a search for the name
# finds them rather than this. The title carries the subject so that a search
# for the subject can land here; the name is only what it lands on.
TITLE = "DEdata — Data Engineering Jobs in Germany: Skills & Salaries"

AUTHOR = {
    "@type": "Person",
    "@id": "https://atakuruk.com/#person",
    "name": "Ata Kürük",
    "url": "https://atakuruk.com/",
    "sameAs": [
        "https://atakuruk.com/",
        "https://github.com/atakrk",
        "https://www.linkedin.com/in/atakrk",
    ],
}

SOURCES = {"arbeitsagentur": "Bundesagentur für Arbeit", "arbeitnow": "Arbeitnow"}

# How many rows a list shows before "show all". Written onto the element, so
# the page script reads the number rather than repeating it.
TOP_SKILLS = 15
TOP_CITIES = 12

SLOT = re.compile(r"<!-- SLOT:([a-z-]+) -->")

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
# passed. The page says what it has no data for instead.
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


def overall(latest: dict) -> dict:
    """The row every percentage on the page is a share of."""
    return next(r for r in latest["language_requirement"] if r["population"] == "ALL")


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

    return {
        "generated_at": date.today().isoformat(),
        "freshness_days": freshness_days,
        "latest_date": dates[-1],
        "first_date": dates[0],
        "days_tracked": len(dates),
        # The denominator. Read from the data rather than restated, so the page
        # cannot drift from it.
        "postings": overall(latest)["postings"],
        "latest": latest,
        # Only what a trend needs, so the page stays small as days accumulate.
        "history": [
            {
                "date": d,
                "postings": overall(days[d])["postings"],
                "pct_requires_german": overall(days[d])["pct_requires_german"],
                "skills": {
                    r["skill_key"]: r["pct_of_postings"]
                    for r in days[d]["skill_frequency"]
                },
            }
            for d in dates
        ],
    }


# ---------------------------------------------------------------------------
# Formatting. These match what the page script prints in its tooltips, so a
# figure reads the same in the markup and on hover.
# ---------------------------------------------------------------------------

def number(n: int | float) -> str:
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    return f"{n:,}"


def fmt(n: int | float | None) -> str:
    return "—" if n is None else number(n)


def pct(n: float | None) -> str:
    return "—" if n is None else f"{n:.1f}%"


def euro(n: int | float | None) -> str:
    return "—" if n is None else "€" + number(n)


def day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d:%B %Y}"


def esc(value: object) -> str:
    return escape(str(value), quote=True)


def listing(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def script_json(value: object) -> str:
    """JSON safe to place inside a <script> element."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def ranked_skills(latest: dict) -> list[dict]:
    # Stable, so tied tools keep the order the snapshot has them in.
    return sorted(latest["skill_frequency"], key=lambda s: -s["pct_of_postings"])


def named(skill: dict) -> str:
    return f"{skill['display_name']} ({pct(skill['pct_of_postings'])})"


# ---------------------------------------------------------------------------
# The sentences. The lede, the meta description, the dataset description and
# llms.txt all state the same headline figures, so they are built from the same
# rows here rather than each phrased by hand -- a hand-written "Azure leads"
# would stay written the morning it stopped being true.
# ---------------------------------------------------------------------------

def lede(data: dict) -> str:
    latest = data["latest"]
    german = overall(latest)
    skills = ranked_skills(latest)
    clouds = [s for s in skills if s["category"] == "cloud"]

    parts = [
        f"On {day(data['latest_date'])}, {fmt(german['postings'])} data engineering "
        "postings advertised in Germany carried a description to read."
    ]
    if skills:
        parts.append(
            f"The tools named most often are {listing([named(s) for s in skills[:3]])}."
        )
    if len(clouds) >= 2:
        if clouds[0]["pct_of_postings"] > clouds[1]["pct_of_postings"]:
            parts.append(
                f"Among cloud platforms, {named(clouds[0])} is named more often than "
                f"{listing([named(s) for s in clouds[1:]])}."
            )
        else:
            parts.append(f"Among cloud platforms: {listing([named(s) for s in clouds])}.")
    if german["pct_requires_german"] is not None:
        # "At least": only an explicit phrase counts, so this is a floor.
        parts.append(
            f"At least {pct(german['pct_requires_german'])} state a German-language "
            "requirement."
        )
    return " ".join(parts)


def meta_description(data: dict) -> str:
    latest = data["latest"]
    german = overall(latest)
    skills = ranked_skills(latest)
    figures = [
        f"{s['display_name']} {pct(s['pct_of_postings'])}"
        for s in [s for s in skills if s["category"] != "cloud"][:2]
    ]
    clouds = [s for s in skills if s["category"] == "cloud"][:2]
    if len(clouds) == 2:
        figures.append(" vs ".join(
            f"{s['display_name']} {pct(s['pct_of_postings'])}" for s in clouds
        ))
    text = (f"{fmt(german['postings'])} data engineering job postings in Germany, "
            f"counted daily: {', '.join(figures)}.")
    if german["pct_requires_german"] is not None:
        text += f" At least {pct(german['pct_requires_german'])} require German."
    return text


def stamp(data: dict) -> str:
    return (
        f"Updated {day(data['latest_date'])}"
        + (f" · counting postings the sources have listed within "
           f"{data['freshness_days']} days"
           if data["freshness_days"] else
           " · counting postings the sources are still listing")
        + f" · tracked daily since {day(data['first_date'])}"
    )


def denominator(data: dict) -> str:
    return (
        f"{fmt(data['postings'])} postings carried a description long enough to read "
        "requirements from. Every percentage on this page is a share of that number, "
        "never of all postings ever seen. A posting counts while the sources are still "
        "listing it"
        + (f" — for {data['freshness_days']} days after it was last seen"
           if data["freshness_days"] else "")
        + ", so a filled vacancy leaves these figures rather than inflating them forever."
    )


# ---------------------------------------------------------------------------
# Head
# ---------------------------------------------------------------------------

def structured_data(data: dict) -> dict:
    latest = data["latest"]
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                # What lets a search result say "DEdata" rather than the domain,
                # and tie it to a person rather than to the other dedatas.
                "@type": "WebSite",
                "@id": SITE_URL + "#website",
                "name": "DEdata",
                "alternateName": "dedata.dev",
                "url": SITE_URL,
                "inLanguage": "en",
                "creator": {"@id": AUTHOR["@id"]},
            },
            AUTHOR,
            {
                "@type": "Dataset",
                "@id": SITE_URL + "#dataset",
                "name": "Data engineering job postings in Germany: skills, "
                        "German-language requirements, cities and salaries",
                "description": lede(data) + " Counted every morning from the "
                    "Bundesagentur für Arbeit's public job API and the Arbeitnow board; "
                    "every percentage is a share of postings with a readable description, "
                    "and each day's figures are published as CSV.",
                "url": SITE_URL,
                "creator": {"@id": AUTHOR["@id"]},
                "isAccessibleForFree": True,
                # No license: the repository does not state one, and this does
                # not get to state one for it.
                "dateModified": data["latest_date"],
                "temporalCoverage": f"{data['first_date']}/{data['latest_date']}",
                "spatialCoverage": {"@type": "Place", "name": "Germany"},
                "isBasedOn": [
                    "https://github.com/bundesAPI/jobsuche-api",
                    "https://www.arbeitnow.com/blog/job-board-api",
                ],
                "variableMeasured": [
                    "Share of postings naming each tool",
                    "Share of postings stating a German-language requirement",
                    "Postings by city",
                    "Median advertised salary by tool",
                    "Postings remaining at each pipeline stage",
                ],
                "distribution": [
                    {
                        "@type": "DataDownload",
                        "name": f"mart_{key}.csv",
                        "encodingFormat": "text/csv",
                        "contentUrl": f"{RAW_URL}/data/snapshots/"
                                      f"{data['latest_date']}/mart_{key}.csv",
                    }
                    for key in latest
                ],
            },
        ],
    }


def head(data: dict, image_size: tuple[int, int]) -> str:
    title = esc(TITLE)
    description = esc(meta_description(data))
    width, height = image_size
    return "\n".join([
        f"<title>{title}</title>",
        f'<meta name="description" content="{description}">',
        # index.html answers too, and is the same page.
        f'<link rel="canonical" href="{SITE_URL}">',
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="DEdata">',
        f'<meta property="og:url" content="{SITE_URL}">',
        f'<meta property="og:title" content="{title}">',
        f'<meta property="og:description" content="{description}">',
        f'<meta property="og:image" content="{SITE_URL}{OG_IMAGE.name}">',
        f'<meta property="og:image:width" content="{width}">',
        f'<meta property="og:image:height" content="{height}">',
        '<meta property="og:image:alt" content="Tools named in German data '
        'engineering postings, as a share of postings">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{title}">',
        f'<meta name="twitter:description" content="{description}">',
        '<script type="application/ld+json">',
        script_json(structured_data(data)),
        "</script>",
    ])


# ---------------------------------------------------------------------------
# Body
# ---------------------------------------------------------------------------

def kpis(data: dict) -> str:
    latest = data["latest"]
    german = overall(latest)
    tiles = [
        ("Currently advertised", fmt(data["postings"]), "#sec-funnel", True),
        ("Require German", pct(german["pct_requires_german"]), "#sec-language", False),
        ("Tools tracked", fmt(len(latest["skill_frequency"])), "#sec-salary", False),
        ("Cities hiring", fmt(len(latest["city_stats"])), "#sec-cities", False),
    ]
    # The freshness tile carries the dot alone, by design decision. The date it
    # stands for is on its label here and in the masthead stamp; the page script
    # turns the label into an age, which only the reader's clock can know.
    built = esc(f"Figures from {day(data['latest_date'])}")
    html = []
    for label, value, href, pulse in tiles:
        marker = (f'<span class="pulse" id="pulse" title="{built}" aria-label="{built}">'
                  "<i></i></span>" if pulse else
                  '<span class="jump" aria-hidden="true">&#8595;</span>')
        html.append(
            f'<a class="kpi" href="{href}"><span class="head">'
            f'<span class="lbl">{esc(label)}</span>{marker}</span>'
            f'<span class="val">{esc(value)}</span></a>'
        )
    return '<div class="kpis" id="kpis">' + "".join(html) + "</div>"


def chips(latest: dict) -> str:
    categories = ["all"] + sorted({s["category"] for s in latest["skill_frequency"]})
    buttons = "".join(
        f'<button class="chip" type="button" data-cat="{esc(c)}" '
        f'aria-pressed="{"true" if c == "all" else "false"}">'
        f'{esc("all tools" if c == "all" else c)}</button>'
        for c in categories
    )
    # Hidden until the script that makes them do something has run.
    return f'<div class="chips" id="chips" hidden>{buttons}</div>'


def skill_bars(latest: dict) -> str:
    skills = ranked_skills(latest)
    top = skills[0]["pct_of_postings"] if skills else 1
    top = top or 1
    rows = "".join(
        f'<div class="row" data-key="{esc(s["skill_key"])}" '
        f'data-cat="{esc(s["category"])}"{" hidden" if i >= TOP_SKILLS else ""}>'
        f'<div class="name">{esc(s["display_name"])}</div>'
        f'<div class="track"><div class="fill" style="width:'
        f'{s["pct_of_postings"] / top * 100:.1f}%"></div></div>'
        f'<div class="val">{pct(s["pct_of_postings"])}</div></div>'
        for i, s in enumerate(skills)
    )
    return f'<div class="bars" id="skills" data-top="{TOP_SKILLS}">{rows}</div>'


def language(latest: dict) -> dict[str, str]:
    german = overall(latest)
    required = german["pct_requires_german"]
    english = german["pct_english_without_german"]
    neither = (None if required is None or english is None
               else round(100 - required - english, 1))

    segments = [
        ("s1", required, "Requires German", "var(--accent)"),
        ("s2", english, "English, no German required", "var(--series-2)"),
        ("s3", neither, "Neither stated", "var(--neutral)"),
    ]
    # A value is printed inside its segment only where it fits; every segment
    # is named in the legend regardless, so identity never rests on colour.
    split = "".join(
        f'<div class="seg {cls}" style="width:{value or 0}%" '
        f'title="{esc(name)} — {pct(value)}">'
        f'{pct(value) if value is not None and value >= 13 else ""}</div>'
        for cls, value, name, _ in segments
    )
    legend = "".join(
        f'<span><i style="background:{colour}"></i>{esc(name)} <b>{pct(value)}</b></span>'
        for _, value, name, colour in segments
    )
    return {
        "german-figure": pct(required),
        "german-of": esc(
            f"of postings state a German-language requirement — "
            f"{fmt(german['requires_german'])} of {fmt(german['postings'])}."
        ),
        "split": f'<div class="split" id="split">{split}</div>',
        "split-legend": f'<div class="legend" id="split-legend">{legend}</div>',
    }


def funnel(latest: dict) -> dict[str, str]:
    stages = sorted(latest.get("pipeline_funnel") or [], key=lambda s: s["stage_order"])
    if not stages:
        return {
            "funnel": '<div class="funnel" id="funnel"></div>',
            "funnel-note": "The run these figures come from did not export its stage counts.",
        }

    first = stages[0]["records"] or 1
    html = []
    for i, s in enumerate(stages):
        # Where the grain changes, say so on its own line. Everything above it
        # counts a posting once per run it appeared in; everything below counts
        # a posting once. Without this the collapse reads as a filter.
        if i > 0 and s["grain"] != stages[i - 1]["grain"]:
            html.append(f'<div class="unit-break"><div class="lbl">one row per '
                        f'{esc(s["grain"])}</div><hr></div>')
        html.append(
            f'<div class="stage{" last" if i == len(stages) - 1 else ""}" '
            f'data-stage="{esc(s["stage"])}">'
            f'<div class="name">{esc(s["stage"].replace("_", " "))}</div>'
            f'<div class="bar"><span style="width:{s["records"] / first * 100:.2f}%">'
            f'</span></div>'
            f'<div class="n">{fmt(s["records"])}</div>'
            f'<div class="keep">{"" if s["pct_of_first"] is None else pct(s["pct_of_first"])}'
            f'</div></div>'
        )

    top, tail = stages[0], stages[-1]
    note = (f"{fmt(top['records'])} rows read, {fmt(tail['records'])} postings published — "
            f"{pct(tail['pct_of_first'])}. The right-hand column is each stage's share of "
            "the rows read, not of the stage above it.")
    return {
        "funnel": '<div class="funnel" id="funnel">' + "".join(html) + "</div>",
        "funnel-note": esc(note),
    }


def cities_table(latest: dict) -> str:
    cities = sorted(latest["city_stats"], key=lambda c: -c["postings"])
    rows = "".join(
        f'<tr{" hidden" if i >= TOP_CITIES else ""}><td>{esc(c["city"])}'
        + (f' <span class="dim">{esc(c["region"].lower())}</span>' if c["region"] else "")
        + f'</td><td class="num">{fmt(c["postings"])}</td>'
        f'<td class="num">{fmt(c["home_office_postings"])}</td>'
        f'<td class="num">{euro(c["median_salary_from"])}'
        + (f' <span class="dim">n={c["postings_with_salary"]}</span>'
           if c["postings_with_salary"] else "")
        + "</td></tr>"
        for i, c in enumerate(cities)
    )
    return (
        f'<table id="cities" data-top="{TOP_CITIES}">'
        '<caption class="vh">Data engineering postings in Germany by city: postings, '
        "postings offering home office, and the median advertised starting salary with "
        "the number of postings stating one</caption>"
        '<thead><tr><th scope="col">City</th><th scope="col" class="num">Postings</th>'
        '<th scope="col" class="num">Home office</th>'
        '<th scope="col" class="num">Median salary</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )


def salary_table(latest: dict) -> str:
    skills = sorted(latest["salary_by_skill"],
                    key=lambda s: -(s["median_salary_from"] or 0))
    rows = "".join(
        f'<tr><td>{esc(s["display_name"])} <span class="dim">{esc(s["category"])}</span>'
        f'</td><td class="num">{euro(s["median_salary_from"])}</td>'
        f'<td class="num">{euro(s["median_salary_to"])}</td>'
        f'<td class="num">{fmt(s["postings_with_salary"])}</td></tr>'
        for s in skills
    )
    return (
        '<table id="salary">'
        '<caption class="vh">Median advertised salary range for data engineering postings '
        "in Germany naming each tool, with the number of postings stating a salary"
        "</caption>"
        '<thead><tr><th scope="col">Tool</th><th scope="col" class="num">Median from</th>'
        '<th scope="col" class="num">Median to</th>'
        '<th scope="col" class="num">Postings</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )


def fill(page: str, slots: dict[str, str]) -> str:
    """Put each slot's markup where the template names it.

    A slot the template names and the build does not fill would publish a blank
    where a figure belongs, and one the build fills that the template has lost
    is a figure that silently stopped appearing. Both stop the build.
    """
    found = SLOT.findall(page)
    unfilled = sorted(set(found) - slots.keys())
    unused = sorted(slots.keys() - set(found))
    repeated = sorted({name for name in found if found.count(name) > 1})
    if unfilled or unused or repeated:
        raise SystemExit(
            f"{TEMPLATE.name} and build_site.py disagree on slots: "
            f"unfilled {unfilled}, unused {unused}, repeated {repeated}"
        )
    return SLOT.sub(lambda m: slots[m.group(1)], page)


def render_page(data: dict, image_size: tuple[int, int]) -> str:
    latest = data["latest"]
    slots = {
        "head": head(data, image_size),
        "lede": esc(lede(data)),
        "stamp": esc(stamp(data)),
        "kpis": kpis(data),
        "chips": chips(latest),
        "skills": skill_bars(latest),
        "skills-hint": esc(
            f"Share of the {fmt(data['postings'])} postings carrying a description "
            "long enough to read requirements from."
        ),
        **language(latest),
        **funnel(latest),
        "cities": cities_table(latest),
        "salary": salary_table(latest),
        "denominator": esc(denominator(data)),
        "data": f'<script id="data" type="application/json">\n{script_json(data)}\n</script>',
    }
    return fill(TEMPLATE.read_text(encoding="utf-8"), slots)


# ---------------------------------------------------------------------------
# Beside the page
# ---------------------------------------------------------------------------

def sitemap(data: dict) -> str:
    # lastmod is the run the figures come from, not the day this ran: a rebuild
    # on the same data did not change what the page says.
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{SITE_URL}</loc><lastmod>{data['latest_date']}</lastmod></url>\n"
        "</urlset>\n"
    )


def llms_txt(data: dict) -> str:
    """The headline figures as plain text, for tools that read rather than render.

    Every rate is printed with the count it came from and the caveats the page
    carries, because this is the version most likely to be quoted without the
    page around it.
    """
    latest = data["latest"]
    german = overall(latest)

    def share(value: float | None, part: int | None, whole: int | None) -> str:
        return f"{pct(value)} ({fmt(part)} of {fmt(whole)})"

    lines = [
        "# DEdata",
        "",
        "> What data engineering job postings in Germany ask for: tools, German-language "
        "requirements, cities and advertised salaries. Counted every morning from two "
        "public job APIs. Open source; every figure traces to a committed daily snapshot.",
        "",
        f"Figures from the run of {day(data['latest_date'])}, tracked daily since "
        f"{day(data['first_date'])}. Every percentage is a share of the "
        f"{fmt(data['postings'])} currently advertised postings that carried a description "
        "to read.",
        "",
        "## Tools named in postings",
        "",
        "A posting counts once per tool, however often it names it.",
        "",
    ]
    lines += [
        f"- {s['display_name']} ({s['category']}): "
        f"{share(s['pct_of_postings'], s['postings'], s['postings_with_text'])}"
        for s in ranked_skills(latest)
    ]

    lines += [
        "",
        "## German-language requirement",
        "",
        "Only an explicit competency phrase counts as requiring German, and most German "
        "postings are written in German regardless, so the German shares are floors, "
        "not ceilings.",
        "",
    ]
    for row in latest["language_requirement"]:
        who = ("All postings" if row["population"] == "ALL"
               else SOURCES.get(row["population"], row["population"]))
        lines.append(
            f"- {who}: {share(row['pct_requires_german'], row['requires_german'], row['postings'])}"
            f" state a German requirement; "
            f"{share(row['pct_english_without_german'], row['english_without_german'], row['postings'])}"
            " mention English without requiring German"
        )

    lines += [
        "",
        "## Median advertised salary by tool",
        "",
        "Advertised, not paid. Only a minority of postings state a salary, tools with "
        "fewer than three that do are left out, and n is the number of postings each "
        "median is taken over.",
        "",
    ]
    lines += [
        f"- {s['display_name']}: {euro(s['median_salary_from'])} to "
        f"{euro(s['median_salary_to'])} (n={fmt(s['postings_with_salary'])})"
        for s in sorted(latest["salary_by_skill"],
                        key=lambda s: -(s["median_salary_from"] or 0))
    ]

    lines += ["", "## Cities with the most postings", ""]
    lines += [
        f"- {c['city']}: {fmt(c['postings'])} postings"
        for c in sorted(latest["city_stats"], key=lambda c: -c["postings"])[:TOP_CITIES]
    ]

    lines += [
        "",
        "## Method",
        "",
        "- Sources: the Bundesagentur für Arbeit's public job API and the Arbeitnow board. "
        "Nothing is scraped.",
        "- Scope: data engineering, analytics engineering, BI and data analyst roles, "
        "entered only where Germany is established by the source or resolved from the "
        "location text. Unknown stays out.",
        "- Deduplication: postings are collapsed on employer and title, which merges an "
        "employer's genuinely different roles under one title.",
        "- Freshness: a posting counts while the sources are still listing it"
        + (f", for {data['freshness_days']} days after it was last seen."
           if data["freshness_days"] else "."),
        "- Each run is a fresh sample of that morning. Read a one-day change as noise.",
        "",
        "## Links",
        "",
        f"- [Dashboard]({SITE_URL})",
        f"- [Pipeline source]({REPO_URL})",
        f"- [Daily snapshots as CSV]({REPO_URL}/tree/main/data/snapshots)",
        f"- [Model documentation]({SITE_URL}models/)",
        "",
    ]
    return "\n".join(lines)


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"{path} is not a PNG")
    return struct.unpack(">II", header[16:24])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", type=Path, default=DEFAULT_SNAPSHOTS,
                        help="the pipeline's data/snapshots directory")
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT,
                        help="the pipeline's dbt_project.yml, for the freshness window")
    args = parser.parse_args()

    if not args.snapshots.exists():
        raise SystemExit(f"no snapshots directory at {args.snapshots}")
    if not CHART.exists():
        raise SystemExit(f"no chart at {CHART}: run analysis/make_charts.py first")

    data = compile_data(args.snapshots, read_freshness_days(args.project))
    page = render_page(data, png_size(CHART))

    DOCS.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(page, encoding="utf-8")
    SITEMAP.write_text(sitemap(data), encoding="utf-8")
    LLMS.write_text(llms_txt(data), encoding="utf-8")
    shutil.copyfile(CHART, OG_IMAGE)

    written = ", ".join(p.name for p in (OUTPUT, SITEMAP, LLMS, OG_IMAGE))
    print(f"docs/{{{written}}}: {data['days_tracked']} day(s), "
          f"latest {data['latest_date']}, {data['postings']} postings")


if __name__ == "__main__":
    main()
