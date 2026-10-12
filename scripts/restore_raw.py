"""Put the last thirty days of raw responses back on the runner.

The daily job builds into a Postgres service container, which GitHub creates
empty and destroys when the job ends. On its own that makes every published
figure one morning's sample: the models ask for the latest run per posting and
the newest description ever fetched for it, and a one-day database has nothing
to choose between. That is why the schedule moved to Databricks, which kept
thirty days. It moved back when the free workspace stopped accepting loads:
from 5 October every morning ingested, kept its responses, and failed at the
load.

The history it needed was never in the warehouse anyway. Every daily run has
uploaded its untouched responses as a `raw-<run_date>` artifact since
29 September, for ninety days. The raw layer is defined as reproducible from
the JSON on disk, so this restores the JSON and lets the ordinary loader
rebuild the warehouse from it each morning. Thirty days is the same window the
Databricks loader pruned to, for the same reason: the models need history to
outlive one posting, not more.

Rules:
  - A run date already on disk is left alone. Today's ingest is fresher than
    any artifact of today, and a rerun of the same morning must not be
    overwritten by its own earlier copy.
  - When a date has several artifacts (a manual rerun), the newest wins.
  - Expired artifacts are skipped; they cannot be downloaded.
  - A failure to list artifacts fails the job. Building on today alone would
    publish a dataset that shrank overnight and look healthy doing it.

Needs GITHUB_TOKEN with actions:read and GITHUB_REPOSITORY (owner/repo), both
set by the workflow.

Usage:
    python scripts/restore_raw.py --days 30
    python scripts/restore_raw.py --days 30 --dry-run
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
from common import RAW_DIR, log  # noqa: E402

API = "https://api.github.com"
PREFIX = "raw-"


def list_artifacts(session: requests.Session, repo: str) -> list[dict]:
    """Every artifact in the repository, across pages."""
    artifacts: list[dict] = []
    url = f"{API}/repos/{repo}/actions/artifacts?per_page=100"
    while url:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        artifacts.extend(response.json()["artifacts"])
        url = response.links.get("next", {}).get("url")
    return artifacts


def select(artifacts: list[dict], since: date, until: date) -> dict[str, dict]:
    """The newest unexpired raw-<date> artifact for each date in the window."""
    chosen: dict[str, dict] = {}
    for artifact in artifacts:
        name = artifact["name"]
        if not name.startswith(PREFIX) or artifact.get("expired"):
            continue
        try:
            run_date = date.fromisoformat(name[len(PREFIX):])
        except ValueError:
            continue
        if not since <= run_date <= until:
            continue
        key = run_date.isoformat()
        current = chosen.get(key)
        if current is None or artifact["created_at"] > current["created_at"]:
            chosen[key] = artifact
    return dict(sorted(chosen.items()))


def dates_on_disk(raw_dir: Path) -> set[str]:
    """Run dates any source already has locally."""
    if not raw_dir.exists():
        return set()
    return {d.name for source in raw_dir.iterdir() if source.is_dir()
            for d in source.iterdir() if d.is_dir()}


def extract(archive: bytes, raw_dir: Path) -> int:
    """Unpack an artifact into data/raw, refusing paths that leave it."""
    root = raw_dir.resolve()
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        for member in zf.namelist():
            target = (root / member).resolve()
            if root not in target.parents and target != root:
                raise SystemExit(f"artifact member escapes data/raw: {member}")
        zf.extractall(root)
        return len(zf.namelist())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=30,
                        help="how many days back from --until to restore (default 30)")
    parser.add_argument("--until", default=date.today().isoformat(),
                        help="newest run date to consider (default today, UTC on a runner)")
    parser.add_argument("--dry-run", action="store_true",
                        help="list what would be restored without downloading")
    args = parser.parse_args()

    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    if not token or not repo:
        raise SystemExit("GITHUB_TOKEN and GITHUB_REPOSITORY must be set")

    until = date.fromisoformat(args.until)
    since = until - timedelta(days=args.days - 1)

    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })

    wanted = select(list_artifacts(session, repo), since, until)
    present = dates_on_disk(RAW_DIR)

    restored = skipped = 0
    for run_date, artifact in wanted.items():
        if run_date in present:
            log.info("%s  on disk already, kept", run_date)
            skipped += 1
            continue
        if args.dry_run:
            log.info("%s  would restore artifact %s (%d bytes)",
                     run_date, artifact["id"], artifact["size_in_bytes"])
            continue
        # The zip endpoint redirects to blob storage; requests drops the
        # Authorization header on the cross-host hop, which is what that
        # signed URL expects.
        response = session.get(artifact["archive_download_url"], timeout=300)
        response.raise_for_status()
        files = extract(response.content, RAW_DIR)
        log.info("%s  restored %d files from artifact %s", run_date, files, artifact["id"])
        restored += 1

    missing = [d for d in ((since + timedelta(days=i)).isoformat()
                           for i in range(args.days))
               if d not in wanted and d not in present]
    log.info("window %s .. %s: %d restored, %d already on disk, %d dates with no run",
             since, until, restored, skipped, len(missing))
    if missing:
        # Not an error: a day the ingest failed, or before artifacts existed.
        # Logged so a gap in the published series has a visible cause.
        log.info("no run for: %s", ", ".join(missing))


if __name__ == "__main__":
    main()
