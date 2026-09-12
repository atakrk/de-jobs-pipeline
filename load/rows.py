"""Turn a run directory into rows, without knowing where they are going.

The project now loads the same raw JSON into two places: Postgres locally and
Databricks in the cloud. Reading the run directory is identical for both, and
a second copy of that logic would drift from the first the moment the ingest
output changes shape -- so the reading lives here and each loader only writes.

Nothing is reshaped in this module. A row's payload is the object exactly as
the API returned it; every interpretation of it happens later in dbt.
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

    @property
    def posting_count(self) -> int:
        return len(self.ag_postings) + len(self.an_postings)

    @property
    def detail_count(self) -> int:
        return len(self.ag_details)


def posting_id(posting: dict) -> str | None:
    """The federal API has used three different names for the same field."""
    for name in ID_FIELDS:
        if posting.get(name):
            return str(posting[name])
    return None


def read_run(source: str, run_dir: Path) -> RunRows:
    run_date = run_dir.name
    rows = RunRows(source=source, run_date=run_date)

    manifest_file = run_dir / "_manifest.json"
    if manifest_file.exists():
        rows.manifest = json.loads(manifest_file.read_text("utf-8"))

    for page_file in sorted(run_dir.glob("page_*.json")):
        blob = json.loads(page_file.read_text("utf-8"))

        if source == "arbeitsagentur":
            # The manifest records which key this endpoint answered with;
            # assuming one of them is how a working endpoint got logged as
            # broken once already.
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

    return rows


def iter_runs(raw_dir: Path, run_date: str | None = None):
    """Yield (source, run_dir) for every run on disk, oldest first."""
    for source_dir in sorted(p for p in raw_dir.iterdir() if p.is_dir()):
        for run_dir in sorted(p for p in source_dir.iterdir() if p.is_dir()):
            if run_date and run_dir.name != run_date:
                continue
            yield source_dir.name, run_dir
