"""Ingest job postings from the Bundesagentur für Arbeit Jobsuche API.

This is Germany's official federal job database and the largest single source
of German vacancies. Spec: https://github.com/bundesAPI/jobsuche-api

What the gateway actually accepts, established by sweeping the combinations
in scripts/probe_auth.py rather than trusting the docs:

  * ``/pc/v6/jobs`` answers; the v4 paths return 403 for every client.
  * ``X-API-Key: jobboerse-jobsuche`` is required and sufficient. The OAuth
    client-credentials flow the documentation describes is not needed, and
    its token endpoint answers 403 regardless.
  * The User-Agent is irrelevant, despite the 403 carrying Vary: User-Agent.

v6 returns its results in ``ergebnisliste``; v4 used ``stellenangebote``. We
accept either, because pinning the success check to one field name is exactly
what made a working endpoint look dead.

Usage:
    python ingest/arbeitsagentur.py --max-pages 2
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import time

import requests

from common import (
    MAX_PAGES,
    RAW_DIR,
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
API_KEY = "jobboerse-jobsuche"
PAGE_SIZE = 100

SEARCH_PATHS = ["/pc/v6/jobs", "/pc/v4/app/jobs", "/pc/v4/jobs"]

# The listing carries no posting text, and the text is where tool names live.
# The detail path has moved between versions and the id may or may not be
# base64-encoded, so resolve both against a real posting instead of assuming.
DETAIL_PATHS = [
    "/pc/v6/jobdetails/{code}",
    "/pc/v4/jobdetails/{code}",
    "/pc/v2/jobdetails/{code}",
]
ID_FIELDS = ["referenznummer", "refnr", "hashId"]

# Field carrying the postings array, newest naming first.
RESULT_KEYS = ["ergebnisliste", "stellenangebote"]
# Field carrying the total match count, ditto.
TOTAL_KEYS = ["maxErgebnisse", "maxErgebnisseGesamt", "gesamtAnzahl"]


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"X-API-Key": API_KEY, "Accept": "application/json"})
    return session


def extract(payload: dict, candidates: list[str]):
    """Return the first present key's value, and the key that matched."""
    for key in candidates:
        if key in payload:
            return payload[key], key
    return None, None


def resolve_search_url(session: requests.Session) -> tuple[str, str] | None:
    """Return (url, results_key) for the first path that returns postings."""
    for path in SEARCH_PATHS:
        url = HOST + path
        payload = get_json(
            session, url, params={"was": "data engineer", "page": 1, "size": 1},
            max_retries=2,
        )
        if not isinstance(payload, dict):
            log.info("endpoint %s returned no usable payload", path)
            continue

        postings, key = extract(payload, RESULT_KEYS)
        if postings is None:
            log.info("endpoint %s answered but carried no known results field "
                     "(keys: %s)", path, sorted(payload)[:8])
            continue

        log.info("using endpoint %s, results in '%s'", path, key)
        return url, key

    return None


def fetch_term(
    session: requests.Session, url: str, results_key: str, term: str, max_pages: int
) -> tuple[list[dict], int | None]:
    """Every page for one term, and the total the API says the term matches."""
    pages: list[dict] = []
    total = None
    for page in range(1, max_pages + 1):
        payload = get_json(
            session, url, params={"was": term, "page": page, "size": PAGE_SIZE}
        )
        if not isinstance(payload, dict):
            break

        postings = payload.get(results_key) or []
        total, _ = extract(payload, TOTAL_KEYS)
        log.info("%-20s page %-3d -> %3d postings (total reported: %s)",
                 term, page, len(postings), total)
        pages.append(payload)

        if len(postings) < PAGE_SIZE:
            break
        time.sleep(REQUEST_DELAY_SECONDS)

    return pages, (int(total) if total is not None else None)


def posting_id(posting: dict) -> str | None:
    for field in ID_FIELDS:
        value = posting.get(field)
        if value:
            return str(value)
    return None


def detail_answers(
    session: requests.Session, template: str, use_base64: bool, sample_id: str
) -> dict | None:
    """One request: does this template and encoding return a posting?"""
    code = (
        base64.b64encode(sample_id.encode("utf-8")).decode("ascii")
        if use_base64
        else sample_id
    )
    payload = get_json(session, HOST + template.format(code=code), max_retries=1)
    return payload if isinstance(payload, dict) and payload else None


def cached_detail_config() -> tuple[str, bool] | None:
    """The path and encoding a previous run recorded, most recent first."""
    manifests = sorted((RAW_DIR / SOURCE).glob("*/_manifest.json"), reverse=True)
    for path in manifests:
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        template = data.get("detail_path")
        if template:
            return template, bool(data.get("detail_base64", True))
    return None


def resolve_detail_url(
    session: requests.Session, sample_id: str
) -> tuple[str, bool] | None:
    """Return (path_template, encode_base64) that returns a posting detail.

    Probing all six combinations costs five failed requests before the
    working one, every run, to rediscover an answer the last run already
    wrote down. So try the cached answer first -- but *verify* it with one
    real request rather than trusting it.

    Caching without verification would be the worse bug: the endpoint moves,
    the cached path keeps being used, every detail request fails, and the run
    reports zero descriptions with nothing in the log explaining why. One
    request is a cheap price for the cache being self-correcting.
    """
    cached = cached_detail_config()
    if cached:
        template, use_base64 = cached
        if detail_answers(session, template, use_base64, sample_id):
            log.info("using cached detail path %s (base64=%s)", template, use_base64)
            return template, use_base64
        log.info("cached detail path %s no longer answers - probing", template)

    for template in DETAIL_PATHS:
        for use_base64 in (True, False):
            payload = detail_answers(session, template, use_base64, sample_id)
            if payload:
                log.info("using detail path %s (base64=%s), fields: %s",
                         template, use_base64, sorted(payload)[:10])
                return template, use_base64
    return None


def fetch_details(
    session: requests.Session,
    template: str,
    use_base64: bool,
    ids: list[str],
    directory,
    limit: int,
) -> int:
    detail_dir = directory / "details"
    detail_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for raw_id in ids[:limit]:
        code = (
            base64.b64encode(raw_id.encode("utf-8")).decode("ascii")
            if use_base64
            else raw_id
        )
        payload = get_json(session, HOST + template.format(code=code), max_retries=2)
        if not isinstance(payload, dict):
            continue
        # base64 of the id is filesystem-safe; the raw id is not.
        safe = base64.urlsafe_b64encode(raw_id.encode("utf-8")).decode("ascii")
        write_json(detail_dir / f"{safe}.json", {"id": raw_id, "payload": payload})
        written += 1
        if written % 50 == 0:
            log.info("details fetched: %d", written)
        time.sleep(REQUEST_DELAY_SECONDS)

    log.info("details written: %d", written)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terms", nargs="*", default=SEARCH_TERMS)
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES)
    parser.add_argument("--with-details", action="store_true",
                        help="also fetch posting text, where the tool names are")
    parser.add_argument("--detail-limit", type=int, default=200)
    args = parser.parse_args()

    session = build_session()
    resolved = resolve_search_url(session)
    if resolved is None:
        log.error("no known search endpoint returned postings")
        raise SystemExit(1)
    search_url, results_key = resolved

    directory = run_dir(SOURCE)
    file_index = 0
    postings_seen = 0
    per_term: dict[str, int] = {}

    ids: list[str] = []

    reported: dict[str, int | None] = {}
    truncated: list[str] = []

    for term in args.terms:
        term_count = 0
        pages, total = fetch_term(session, search_url, results_key, term, args.max_pages)
        for payload in pages:
            file_index += 1
            write_json(directory / f"page_{file_index:04d}.json",
                       {"search_term": term, "results_key": results_key,
                        "payload": payload})
            for posting in payload.get(results_key) or []:
                term_count += 1
                found = posting_id(posting)
                if found:
                    ids.append(found)
        per_term[term] = term_count
        reported[term] = total
        postings_seen += term_count

        # A search cut off by --max-pages is a sample, not the market. Every
        # posting past the cap goes unseen, and once it has been unseen for
        # the freshness window the models read it as withdrawn -- nothing
        # downstream can tell the two apart, so it is said here and recorded.
        # Only a cap that was actually reached counts: the API's total is an
        # estimate, and a short last page means the list simply ended.
        if total is not None and term_count < total and len(pages) == args.max_pages:
            truncated.append(term)
            log.warning("%s: fetched %d of %d reported; --max-pages %d cuts it off, "
                        "and postings past the cap will age out as if withdrawn",
                        term, term_count, total, args.max_pages)

    unique_ids = list(dict.fromkeys(ids))

    # Shuffle before --detail-limit truncates. Ids arrive in search-term
    # order, so taking the first n takes one search term's results almost
    # exclusively -- and those terms differ in how tool-dense they are, which
    # skews every downstream percentage in the same direction. A limit that
    # truncates an ordered list is a sampling decision, not a throttle.
    #
    # Seeded by run date so a re-run of the same day fetches the same subset
    # and the run stays reproducible.
    random.Random(directory.name).shuffle(unique_ids)

    details_written = 0
    detail_template = None
    detail_base64 = None

    if args.with_details and unique_ids:
        resolved_detail = resolve_detail_url(session, unique_ids[0])
        if resolved_detail is None:
            log.warning("no detail path answered - skipping posting text")
        else:
            detail_template, detail_base64 = resolved_detail
            log.info("fetching details for %d unique postings (limit %d)",
                     len(unique_ids), args.detail_limit)
            details_written = fetch_details(
                session, detail_template, detail_base64, unique_ids,
                directory, args.detail_limit,
            )

    write_manifest(
        directory,
        source=SOURCE,
        search_url=search_url,
        results_key=results_key,
        search_terms=args.terms,
        files_written=file_index,
        postings_seen=postings_seen,
        postings_per_term=per_term,
        postings_reported_per_term=reported,
        max_pages=args.max_pages,
        truncated_terms=truncated,
        unique_ids=len(unique_ids),
        detail_path=detail_template,
        detail_base64=detail_base64,
        details_written=details_written,
        detail_limit=args.detail_limit if args.with_details else None,
        detail_sampling="random, seeded by run date",
    )
    log.info("done: %d postings across %d files", postings_seen, file_index)


if __name__ == "__main__":
    main()
