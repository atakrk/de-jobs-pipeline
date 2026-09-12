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

import os
import sys
from datetime import date
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
from common import log  # noqa: E402

README = Path(__file__).resolve().parents[1] / "README.md"
START = "<!-- FINDINGS:START -->"
END = "<!-- FINDINGS:END -->"

CLOUDS = ["azure", "aws", "gcp"]


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5433"),
        dbname=os.getenv("PGDATABASE", "jobs"),
        user=os.getenv("PGUSER", "jobs"),
        password=os.getenv("PGPASSWORD", "jobs"),
    )


def build_block(cur) -> str:
    cur.execute("""
        select population, postings, pct_requires_german,
               pct_english_without_german, requires_german,
               english_without_german
        from analytics_marts.mart_language_requirement
        where population = 'ALL'
    """)
    row = cur.fetchone()
    if row is None:
        raise SystemExit("mart_language_requirement has no ALL row")
    _, with_text, pct_german, pct_english, n_german, n_english = row

    cur.execute("select count(*) from analytics_intermediate.int_postings")
    total_postings = cur.fetchone()[0]

    cur.execute(
        """
        select skill_key, display_name, postings, pct_of_postings
        from analytics_marts.mart_skill_frequency
        where skill_key = any(%s)
        order by postings desc
        """,
        (CLOUDS,),
    )
    clouds = cur.fetchall()

    neither = with_text - n_german - n_english

    lines = [
        START,
        "",
        f"*Generated from the latest pipeline run "
        f"({date.today().isoformat()}); these figures change when it does.*",
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
    text = README.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise SystemExit(f"README is missing the {START} / {END} markers")

    with connect() as conn, conn.cursor() as cur:
        block = build_block(cur)

    before = text[: text.index(START)]
    after = text[text.index(END) + len(END) :]
    README.write_text(before + block + after, encoding="utf-8")
    log.info("README figures updated")


if __name__ == "__main__":
    main()
