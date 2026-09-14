"""Regenerate the README's figures from the marts.

The README is the deliverable, and its numbers were hand-typed while the
charts beside them were regenerated daily. They disagreed within a day.

The split this enforces: **numbers are generated, meaning is hand-written.**
Everything between the FINDINGS markers is produced here from the marts.
Everything outside them is prose a person wrote, and it is deliberately
phrased without hard figures so it cannot rot the same way. Claims about
ordering ("Power BI ranks above Spark") are the exception and do need an
occasional human look -- they are structural rather than numeric, but they
are not automatically true forever.

Usage:
    python analysis/update_readme.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import warehouse  # noqa: E402
from common import log  # noqa: E402

README = Path(__file__).resolve().parents[1] / "README.md"
START = "<!-- FINDINGS:START -->"
END = "<!-- FINDINGS:END -->"

CLOUDS = ["azure", "aws", "gcp"]


def build_block(cur, marts: str, intermediate: str) -> str:
    cur.execute(f"""
        select population, postings, pct_requires_german,
               pct_english_without_german, requires_german,
               english_without_german
        from {marts}.mart_language_requirement
        where population = 'ALL'
    """)
    row = cur.fetchone()
    if row is None:
        raise SystemExit("mart_language_requirement has no ALL row")
    _, with_text, pct_german, pct_english, n_german, n_english = row

    cur.execute(f"""
        select count(*), count(distinct run_date), min(run_date), max(run_date)
        from {intermediate}.int_postings
    """)
    total_postings, run_count, first_run, last_run = cur.fetchone()

    # Spelled inline rather than bound: `= any(%s)` is Postgres, the two
    # connectors disagree on the placeholder, and CLOUDS is a constant in this
    # file rather than anything a caller supplies.
    cloud_list = ", ".join(f"'{skill}'" for skill in CLOUDS)
    cur.execute(f"""
        select skill_key, display_name, postings, pct_of_postings
        from {marts}.mart_skill_frequency
        where skill_key in ({cloud_list})
        order by postings desc
    """)
    clouds = cur.fetchall()

    cur.execute(f"""
        select stage, postings, pct_of_previous, pct_of_first
        from {marts}.mart_pipeline_funnel
        order by stage_order
    """)
    funnel = cur.fetchall()

    neither = with_text - n_german - n_english

    lines = [
        START,
        "",
        # Not "the latest run". The warehouse accumulates, and int_postings
        # keeps every posting still seen inside the freshness window -- so the
        # published set spans several runs, and saying otherwise would publish
        # a correct number under a false description.
        f"*Postings still being advertised across the {run_count} daily "
        f"{'run' if run_count == 1 else 'runs'} from {first_run} to "
        f"{last_run}. A posting leaves these figures once the sources stop "
        f"listing it, so this is what the market is asking for now rather "
        f"than one morning's sample.*",
        "",
        f"**{total_postings:,} postings** after scope filtering, location "
        f"validation and deduplication; **{with_text:,}** of them carry a "
        "description long enough to read requirements from. Every percentage "
        f"on this page is a share of those {with_text:,}.",
        "",
        "### Cloud platforms",
        "",
        "| | share of postings |",
        "| --- | --- |",
    ]
    for _, name, _, pct in clouds:
        lines.append(f"| {name} | {pct}% |")

    if len(clouds) >= 2:
        lead, second = clouds[0], clouds[1]
        ratio = float(lead[3]) / float(second[3]) if float(second[3]) else 0
        lines += [
            "",
            f"{lead[1]} appears **{ratio:.1f}×** as often as {second[1]}.",
        ]

    if funnel:
        lines += [
            "",
            "### What the published number is a share of",
            "",
            # Generated, never typed. A funnel written by hand is a snapshot of
            # the day someone wrote it, and this whole table exists because a
            # number with no stages behind it cannot be debugged.
            "Stages in the order the pipeline applies them. The last row is the "
            "denominator above.",
            "",
            "| stage | postings | of previous | of rows read |",
            "| --- | ---: | ---: | ---: |",
        ]
        for stage, postings, of_previous, of_first in funnel:
            previous = "—" if of_previous is None else f"{of_previous}%"
            first = "—" if of_first is None else f"{of_first}%"
            lines.append(
                f"| {stage.replace('_', ' ')} | {postings:,} | {previous} | {first} |"
            )

    lines += [
        "",
        "### Language requirement",
        "",
        f"| requires German | mentions English, no German requirement | "
        f"neither stated |",
        "| --- | --- | --- |",
        f"| **{pct_german}%** | **{pct_english}%** | "
        f"**{round(100.0 * neither / with_text, 1)}%** |",
        "",
        END,
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    warehouse.add_target_argument(parser)
    args = parser.parse_args()

    text = README.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise SystemExit(f"README is missing the {START} / {END} markers")

    conn, marts = warehouse.connect(args.target)
    intermediate = marts.replace(warehouse.MARTS_SCHEMA,
                                 warehouse.INTERMEDIATE_SCHEMA)
    with conn, conn.cursor() as cur:
        block = build_block(cur, marts, intermediate)

    before = text[: text.index(START)]
    after = text[text.index(END) + len(END) :]
    README.write_text(before + block + after, encoding="utf-8")
    log.info("README figures updated")


if __name__ == "__main__":
    main()
