"""Ingest job postings from the Arbeitnow job board API.

Free, no authentication, JSON. Its value here is not volume but overlap:
having a second source is what makes deduplication a real problem, and
deduplication is where most of the engineering in this project lives.

Docs: https://www.arbeitnow.com/blog/job-board-api

Usage:
    python ingest/arbeitnow.py
    python ingest/arbeitnow.py --max-pages 5
"""

from __future__ import annotations

import argparse
import time

import requests

from common import (
    MAX_PAGES,
    REQUEST_DELAY_SECONDS,
    get_json,
    log,
    run_dir,
    write_json,
    write_manifest,
)

SOURCE = "arbeitnow"
BASE_URL = "https://www.arbeitnow.com/api/job-board-api"


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json",
            "User-Agent": "de-jobs-pipeline/0.1 (portfolio project)",
        }
    )
    return session


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES)
    args = parser.parse_args()

    session = build_session()
    directory = run_dir(SOURCE)
    file_index = 0
    postings_seen = 0

    # The board is paginated but not searchable, so we pull the feed and
    # filter later in dbt. Cheap to do, and it keeps the raw layer honest.
    for page in range(1, args.max_pages + 1):
        payload = get_json(session, BASE_URL, params={"page": page})
        if payload is None:
            break

        jobs = payload.get("data") or []
        if not jobs:
            log.info("page %d empty, stopping", page)
            break

        file_index += 1
        postings_seen += len(jobs)
        write_json(directory / f"page_{file_index:04d}.json", payload)
        log.info("page %-3d -> %3d postings", page, len(jobs))

        time.sleep(REQUEST_DELAY_SECONDS)

    write_manifest(
        directory,
        source=SOURCE,
        base_url=BASE_URL,
        files_written=file_index,
        postings_seen=postings_seen,
    )
    log.info("done: %d postings across %d files", postings_seen, file_index)


if __name__ == "__main__":
    main()
