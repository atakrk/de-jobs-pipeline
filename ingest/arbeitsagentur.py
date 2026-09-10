"""Ingest job postings from the Bundesagentur für Arbeit Jobsuche API.

This is Germany's official federal job database and the largest single source
of German vacancies. The API is public; the key below is the well-known client
key the Jobbörse front-end itself uses, documented at
https://github.com/bundesAPI/jobsuche-api

Usage:
    python ingest/arbeitsagentur.py
    python ingest/arbeitsagentur.py --terms "data engineer" --max-pages 5
"""

from __future__ import annotations

import argparse

import requests

from common import (
    MAX_PAGES,
    REQUEST_DELAY_SECONDS,
    SEARCH_TERMS,
    get_json,
    log,
    run_dir,
    write_json,
    write_manifest,
)
import time

SOURCE = "arbeitsagentur"
BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
API_KEY = "jobboerse-jobsuche"
PAGE_SIZE = 100


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "X-API-Key": API_KEY,
            "Accept": "application/json",
            "User-Agent": "de-jobs-pipeline/0.1 (portfolio project)",
        }
    )
    return session


def fetch_term(session: requests.Session, term: str, max_pages: int) -> list[dict]:
    """Fetch every page for one search term. Returns the raw page payloads."""
    pages: list[dict] = []
    for page in range(1, max_pages + 1):
        payload = get_json(
            session,
            BASE_URL,
            params={
                "was": term,
                "page": page,
                "size": PAGE_SIZE,
                # 100 = published within the last 100 days
                "veroeffentlichtseit": 100,
            },
        )
        if payload is None:
            break

        postings = payload.get("stellenangebote") or []
        total = payload.get("maxErgebnisse")
        log.info("%-18s page %-3d -> %3d postings (total reported: %s)",
                 term, page, len(postings), total)
        pages.append(payload)

        if len(postings) < PAGE_SIZE:
            break
        time.sleep(REQUEST_DELAY_SECONDS)

    return pages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terms", nargs="*", default=SEARCH_TERMS)
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES)
    args = parser.parse_args()

    session = build_session()
    directory = run_dir(SOURCE)
    file_index = 0
    postings_seen = 0
    per_term: dict[str, int] = {}

    for term in args.terms:
        pages = fetch_term(session, term, args.max_pages)
        term_count = 0
        for payload in pages:
            file_index += 1
            write_json(directory / f"page_{file_index:04d}.json",
                       {"search_term": term, "payload": payload})
            term_count += len(payload.get("stellenangebote") or [])
        per_term[term] = term_count
        postings_seen += term_count

    write_manifest(
        directory,
        source=SOURCE,
        base_url=BASE_URL,
        search_terms=args.terms,
        files_written=file_index,
        postings_seen=postings_seen,
        postings_per_term=per_term,
    )
    log.info("done: %d postings across %d files", postings_seen, file_index)


if __name__ == "__main__":
    main()
