"""Shared helpers for the ingest scripts.

Every ingest writes untouched API responses to
``data/raw/<source>/<run_date>/page_XXXX.json`` plus a ``_manifest.json``
describing the run. Nothing is cleaned here on purpose: the raw layer is the
audit trail, and every later stage must be reproducible from it.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"

REQUEST_DELAY_SECONDS = float(os.getenv("REQUEST_DELAY_SECONDS", "0.5"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "40"))
# The federal search terms, in code rather than in the environment. They were
# an environment variable with a default, and the laptop's .env named three
# terms while the daily job, which sets nothing, searched one. Both wrote to
# the same warehouse. Postings only the laptop's wider search could find were
# counted until they had gone unseen for seven days, then aged out together --
# 202 of them in one morning, 22 of 25 sampled still advertised. The terms
# decide what a posting's absence means, so there is one list, and a run that
# wants another says so with --terms, which the manifest records.
#
# "data engineering" was one of the three. It matches over two thousand
# postings, mostly other roles, and would not fit the page cap either.
SEARCH_TERMS = ["data engineer", "analytics engineer"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ingest")


def run_dir(source: str, run_date: str | None = None) -> Path:
    """Directory for one ingest run, created if missing."""
    run_date = run_date or date.today().isoformat()
    path = RAW_DIR / source / run_date
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_manifest(directory: Path, **fields: Any) -> None:
    """Record what a run actually did, so a later load can be trusted."""
    write_manifest_payload = {"written_at": time.strftime("%Y-%m-%dT%H:%M:%S"), **fields}
    write_json(directory / "_manifest.json", write_manifest_payload)
    log.info("manifest written to %s", directory / "_manifest.json")


def get_json(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    max_retries: int = 4,
) -> dict[str, Any] | None:
    """GET with exponential backoff. Returns None when the page is unusable.

    Returning None instead of raising keeps a single bad page from throwing
    away every page already fetched in this run.
    """
    delay = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url, params=params, timeout=30)
        except requests.RequestException as exc:
            log.warning("request failed (%s/%s): %s", attempt, max_retries, exc)
        else:
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError:
                    log.warning("response was not JSON: %s", response.text[:200])
                    return None
            if response.status_code == 404:
                log.info("HTTP 404 for %s", response.url)
                return None
            log.warning(
                "HTTP %s (%s/%s) for %s :: %s",
                response.status_code,
                attempt,
                max_retries,
                response.url,
                response.text[:300].replace("\n", " ") or "<empty body>",
            )
        time.sleep(delay)
        delay *= 2
    log.error("giving up on %s", url)
    return None
