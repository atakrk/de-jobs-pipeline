"""Ingest job postings from the Bundesagentur für Arbeit Jobsuche API.

This is Germany's official federal job database and the largest single source
of German vacancies. The API is public; the key below is the well-known client
key the Jobbörse front-end itself uses, documented at
https://github.com/bundesAPI/jobsuche-api

Two stages:
  1. Search  -> listing pages (titles, employers, locations, refnr)
  2. Details -> the full posting text, which is where the tool names live.
     The detail endpoint takes the base64 of ``refnr`` as its path segment.

Usage:
    python ingest/arbeitsagentur.py --max-pages 2
    python ingest/arbeitsagentur.py --max-pages 2 --with-details --detail-limit 50
"""

from __future__ import annotations

import argparse
import base64
import time

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

SOURCE = "arbeitsagentur"
HOST = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
PAGE_SIZE = 100

# The service is behind OAuth2 client credentials, not a static key. The
# client id and secret below are the ones published in the official API
# documentation for public use; the issued token goes in a header named
# OAuthAccessToken rather than Authorization.
TOKEN_URL = "https://rest.arbeitsagentur.de/oauth/gettoken_cc"
CLIENT_ID = "c003a37f-024f-462a-b36d-b001be4cd24a"
CLIENT_SECRET = "32a39620-32b3-4307-9aa1-511e3d7f48a8"

USER_AGENT = (
    "Jobsuche/2.9.2 (de.arbeitsagentur.jobboerse; build:1077; iOS 15.1.0) "
    "Alamofire/5.4.4"
)

# The service has shipped several versions of the search path and the older
# ones are not always retired. The documented example uses /pc/v4/app/jobs,
# so try that first, then fall back. Probe once, reuse whichever answers.
SEARCH_PATHS = ["/pc/v4/app/jobs", "/pc/v6/jobs", "/pc/v4/jobs"]
DETAIL_PATH = "/pc/v4/jobdetails/{code}"

# angebotsart=1 restricts results to employment (not self-employment,
# apprenticeships or internships); pav excludes private placement agencies.
BASE_PARAMS = {"angebotsart": 1, "pav": "false"}


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Connection": "keep-alive",
        }
    )
    return session


def authenticate(session: requests.Session) -> bool:
    """Fetch an access token and attach it to the session.

    Tokens are short-lived JWTs. A run takes minutes, so one token per run
    is enough; a long-running schedule would need to refresh on 401.
    """
    try:
        response = session.post(
            TOKEN_URL,
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "client_credentials",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        log.error("token request failed: %s", exc)
        return False

    if response.status_code != 200:
        log.error("token endpoint returned HTTP %s :: %s",
                  response.status_code, response.text[:300])
        return False

    token = (response.json() or {}).get("access_token")
    if not token:
        log.error("token endpoint returned no access_token: %s", response.text[:300])
        return False

    session.headers["OAuthAccessToken"] = token
    log.info("authenticated (token length %d)", len(token))
    return True


def resolve_search_url(session: requests.Session) -> str | None:
    """Return the first search path the service actually answers."""
    for path in SEARCH_PATHS:
        url = HOST + path
        payload = get_json(
            session,
            url,
            params={**BASE_PARAMS, "was": "data engineer", "page": 1, "size": 1},
            max_retries=2,
        )
        if payload is not None and "stellenangebote" in payload:
            log.info("using search endpoint %s", path)
            return url
        log.info("endpoint %s did not answer, trying next", path)
    return None


def fetch_term(session: requests.Session, url: str, term: str, max_pages: int) -> list[dict]:
    """Fetch every page for one search term. Returns the raw page payloads."""
    pages: list[dict] = []
    for page in range(1, max_pages + 1):
        payload = get_json(
            session,
            url,
            params={
                **BASE_PARAMS,
                "was": term,
                "page": page,
                "size": PAGE_SIZE,
                "veroeffentlichtseit": 100,  # published within the last 100 days
            },
        )
        if payload is None:
            break

        postings = payload.get("stellenangebote") or []
        log.info(
            "%-20s page %-3d -> %3d postings (total reported: %s)",
            term, page, len(postings), payload.get("maxErgebnisse"),
        )
        pages.append(payload)

        if len(postings) < PAGE_SIZE:
            break
        time.sleep(REQUEST_DELAY_SECONDS)

    return pages


def encode_refnr(refnr: str) -> str:
    """The detail endpoint identifies a posting by base64(refnr)."""
    return base64.b64encode(refnr.encode("utf-8")).decode("ascii")


def fetch_details(
    session: requests.Session, refnrs: list[str], directory, limit: int
) -> int:
    """Fetch full posting text for up to ``limit`` reference numbers."""
    detail_dir = directory / "details"
    detail_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for refnr in refnrs[:limit]:
        code = encode_refnr(refnr)
        payload = get_json(session, HOST + DETAIL_PATH.format(code=code), max_retries=2)
        if payload is None:
            continue
        write_json(detail_dir / f"{code}.json", {"refnr": refnr, "payload": payload})
        written += 1
        if written % 25 == 0:
            log.info("details fetched: %d", written)
        time.sleep(REQUEST_DELAY_SECONDS)

    log.info("details written: %d", written)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terms", nargs="*", default=SEARCH_TERMS)
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES)
    parser.add_argument("--with-details", action="store_true",
                        help="also fetch the full posting text for each result")
    parser.add_argument("--detail-limit", type=int, default=200)
    args = parser.parse_args()

    session = build_session()
    if not authenticate(session):
        log.error("could not authenticate against %s", TOKEN_URL)
        raise SystemExit(1)

    search_url = resolve_search_url(session)
    if search_url is None:
        log.error("no known search endpoint answered - the API path has moved")
        raise SystemExit(1)

    directory = run_dir(SOURCE)
    file_index = 0
    postings_seen = 0
    per_term: dict[str, int] = {}
    refnrs: list[str] = []

    for term in args.terms:
        term_count = 0
        for payload in fetch_term(session, search_url, term, args.max_pages):
            file_index += 1
            write_json(directory / f"page_{file_index:04d}.json",
                       {"search_term": term, "payload": payload})
            for posting in payload.get("stellenangebote") or []:
                term_count += 1
                refnr = posting.get("refnr")
                if refnr:
                    refnrs.append(refnr)
        per_term[term] = term_count
        postings_seen += term_count

    details_written = 0
    if args.with_details:
        unique = list(dict.fromkeys(refnrs))
        log.info("fetching details for %d unique postings (limit %d)",
                 len(unique), args.detail_limit)
        details_written = fetch_details(session, unique, directory, args.detail_limit)

    write_manifest(
        directory,
        source=SOURCE,
        search_url=search_url,
        search_terms=args.terms,
        files_written=file_index,
        postings_seen=postings_seen,
        postings_per_term=per_term,
        unique_refnrs=len(set(refnrs)),
        details_written=details_written,
    )
    log.info("done: %d postings across %d files", postings_seen, file_index)


if __name__ == "__main__":
    main()
