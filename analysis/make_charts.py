"""Render the charts that go in the README.

Reads the marts, writes PNGs to analysis/charts/. Deliberately single-theme:
these are embedded in a README that renders on a light page, so the surface
is fixed rather than left to inherit something unpredictable.

Usage:
    python analysis/make_charts.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
from common import log  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "charts"

# Chart chrome. One accent hue: nothing here encodes identity by colour except
# the two-series language chart, so a second hue would be decoration.
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
SERIES_1 = "#2a78d6"
SERIES_2 = "#eb6834"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "text.color": INK,
    "axes.labelcolor": INK_SECONDARY,
    "xtick.color": MUTED,
    "ytick.color": INK_SECONDARY,
})


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5433"),
        dbname=os.getenv("PGDATABASE", "jobs"),
        user=os.getenv("PGUSER", "jobs"),
        password=os.getenv("PGPASSWORD", "jobs"),
    )


def strip_frame(ax, keep_left: bool = True) -> None:
    for side in ("top", "right", "bottom"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_visible(keep_left)
    ax.spines["left"].set_color(GRID)
    ax.tick_params(length=0)


def chart_skills(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            select display_name, postings, pct_of_postings
            from analytics_marts.mart_skill_frequency
            order by postings desc
            limit 15
        """)
        rows = cur.fetchall()

    names = [r[0] for r in rows][::-1]
    pct = [float(r[2]) for r in rows][::-1]
    counts = [r[1] for r in rows][::-1]

    fig, ax = plt.subplots(figsize=(9, 6.4))
    ax.barh(names, pct, height=0.62, color=SERIES_1)

    for y, (p, c) in enumerate(zip(pct, counts)):
        ax.text(p + 0.8, y, f"{p:.1f}%  ({c})",
                va="center", ha="left", fontsize=9.5, color=INK_SECONDARY)

    ax.set_xlim(0, max(pct) * 1.22)
    ax.set_xticks([])
    strip_frame(ax)
    ax.set_title("Tools named in German data engineering postings",
                 fontsize=13.5, color=INK, pad=30, loc="left")
    ax.text(0, 1.012, "share of postings with a description",
            transform=ax.transAxes, fontsize=9.5, color=MUTED)

    fig.tight_layout()
    fig.savefig(OUT_DIR / "skill_frequency.png", dpi=180)
    plt.close(fig)
    log.info("wrote skill_frequency.png")


def chart_language(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            select source, postings, requires_german
            from analytics_marts.mart_language_requirement
            where source <> 'ALL'
            order by postings desc
        """)
        rows = cur.fetchall()

    labels = {"arbeitsagentur": "Bundesagentur für Arbeit\n(federal database)",
              "arbeitnow": "Arbeitnow\n(international board)"}
    names = [labels.get(r[0], r[0]) for r in rows][::-1]
    totals = [r[1] for r in rows][::-1]
    german = [r[2] for r in rows][::-1]

    pct_german = [100.0 * g / t for g, t in zip(german, totals)]
    pct_other = [100.0 - p for p in pct_german]

    fig, ax = plt.subplots(figsize=(9, 3.1))
    ax.barh(names, pct_german, height=0.5, color=SERIES_1,
            label="Explicitly requires German")
    ax.barh(names, pct_other, height=0.5, left=[p + 0.6 for p in pct_german],
            color=SERIES_2, label="No explicit requirement")

    for y, (pg, total) in enumerate(zip(pct_german, totals)):
        ax.text(pg / 2, y, f"{pg:.0f}%", va="center", ha="center",
                fontsize=10, color="white", weight="bold")
        ax.text(101.5, y, f"n={total}", va="center", ha="left",
                fontsize=9.5, color=MUTED)

    ax.set_xlim(0, 112)
    ax.set_xticks([])
    strip_frame(ax, keep_left=False)
    ax.set_title("How much of the market is gated on German",
                 fontsize=13.5, color=INK, pad=26, loc="left")
    ax.text(0, 1.10, "a floor, not a ceiling: only explicit competency phrases are counted",
            transform=ax.transAxes, fontsize=9.5, color=MUTED)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.3), ncol=2,
              frameon=False, fontsize=9.5, labelcolor=INK_SECONDARY)

    fig.tight_layout()
    fig.savefig(OUT_DIR / "language_requirement.png", dpi=180,
                bbox_inches="tight")
    plt.close(fig)
    log.info("wrote language_requirement.png")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        chart_skills(conn)
        chart_language(conn)
    log.info("charts written to %s", OUT_DIR)


if __name__ == "__main__":
    main()
