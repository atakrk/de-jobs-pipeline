"""Read a run directory into rows. Shared by the Postgres and Databricks loaders.

Payloads are kept exactly as the API returned them; mapping happens in dbt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

ID_FIELDS = ["referenznummer", "refnr", "hashId"]


@dataclass
class RunRows:
    """Everything one ingest run contributes, keyed by destination table."""

    source: str
    run_date: str
    manifest: dict | None = None
    ag_postings: list[tuple] = field(default_factory=list)   # (id, run_date, search_term, payload)
    ag_details: list[tuple] = field(default_factory=list)    # (id, run_date, payload)
    an_postings: list[tuple] = field(default_factory=list)   # (id, run_date, payload)
    duplicates: int = 0                                      # rows collapsed by the grain
    postings_read: int = 0                                   # posting rows before that

    @property
    def posting_count(self) -> int:
        return len(self.ag_postings) + len(self.an_postings)

    @property
    def posting_duplicates(self) -> int:
        """Posting rows the grain collapsed (unlike `duplicates`, excludes details)."""
        return self.postings_read - self.posting_count

    def load_manifest(self) -> dict:
        """The ingest manifest plus row counts before/after dedupe (for the funnel)."""
        return {
            **(self.manifest or {}),
            "rows_read": self.postings_read,
            "duplicates_collapsed": self.posting_duplicates,
        }

    @property
    def detail_count(self) -> int:
        return len(self.ag_details)


def posting_id(posting: dict) -> str | None:
    """The federal API has used three different names for the same field."""
    for name in ID_FIELDS:
        if posting.get(name):
            return str(posting[name])
    return None


def dedupe(rows: list[tuple]) -> list[tuple]:
    """Collapse rows sharing (source_id, run_date), keeping the last.

    Done here because Delta has no primary key; last wins, like ON CONFLICT DO UPDATE.
    """
    collapsed: dict[tuple, tuple] = {}
    for row in rows:
        collapsed[(row[0], row[1])] = row
    return list(collapsed.values())


def read_run(source: str, run_dir: Path) -> RunRows:
    run_date = run_dir.name
    rows = RunRows(source=source, run_date=run_date)

    manifest_file = run_dir / "_manifest.json"
    if manifest_file.exists():
        rows.manifest = json.loads(manifest_file.read_text("utf-8"))

    for page_file in sorted(run_dir.glob("page_*.json")):
        blob = json.loads(page_file.read_text("utf-8"))

        if source == "arbeitsagentur":
            # Use the results key the ingest recorded.
            key = blob.get("results_key", "ergebnisliste")
            for posting in blob["payload"].get(key) or []:
                found = posting_id(posting)
                if found:
                    rows.ag_postings.append(
                        (found, run_date, blob.get("search_term"), posting)
                    )
        else:  # arbeitnow
            for posting in blob.get("data") or []:
                slug = posting.get("slug")
                if slug:
                    rows.an_postings.append((slug, run_date, posting))

    if source == "arbeitsagentur":
        for detail_file in sorted((run_dir / "details").glob("*.json")):
            blob = json.loads(detail_file.read_text("utf-8"))
            rows.ag_details.append((blob["id"], run_date, blob["payload"]))

    rows.postings_read = len(rows.ag_postings) + len(rows.an_postings)
    before = rows.postings_read + len(rows.ag_details)
    rows.ag_postings = dedupe(rows.ag_postings)
    rows.ag_details = dedupe(rows.ag_details)
    rows.an_postings = dedupe(rows.an_postings)
    rows.duplicates = before - (
        len(rows.ag_postings) + len(rows.ag_details) + len(rows.an_postings)
    )

    return rows


def iter_runs(raw_dir: Path, run_date: str | None = None):
    """Yield (source, run_dir) for every run on disk, oldest first."""
    for source_dir in sorted(p for p in raw_dir.iterdir() if p.is_dir()):
        for run_dir in sorted(p for p in source_dir.iterdir() if p.is_dir()):
            if run_date and run_dir.name != run_date:
                continue
            yield source_dir.name, run_dir
