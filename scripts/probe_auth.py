"""Find the request shape the Jobsuche gateway actually accepts.

The gateway answers 403 with an empty body and a ``Vary: User-Agent``
header, which says the client identifier is what it discriminates on.
Rather than guess one at a time, sweep the combinations and print a
matrix. Throwaway diagnostic - delete once the answer is known.

    python scripts/probe_auth.py
"""

from __future__ import annotations

import requests

HOST = "https://rest.arbeitsagentur.de"
SEARCH_PATHS = [
    "/jobboerse/jobsuche-service/pc/v4/jobs",
    "/jobboerse/jobsuche-service/pc/v4/app/jobs",
    "/jobboerse/jobsuche-service/pc/v6/jobs",
]
TOKEN_URL = f"{HOST}/oauth/gettoken_cc"
CLIENT_ID = "c003a37f-024f-462a-b36d-b001be4cd24a"
CLIENT_SECRET = "32a39620-32b3-4307-9aa1-511e3d7f48a8"

USER_AGENTS = {
    "none": None,
    "curl-default": "curl/8.7.1",
    "safari-mac": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.4 Safari/605.1.15"
    ),
    "chrome-mac": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "ios-app-2.9.2": (
        "Jobsuche/2.9.2 (de.arbeitsagentur.jobboerse; build:1077; iOS 15.1.0) "
        "Alamofire/5.4.4"
    ),
    "android-app": "Jobboerse/3.0 (de.arbeitsagentur.jobboerse; Android 13)",
}

AUTH_VARIANTS = {
    "no-auth": {},
    "xapikey-literal": {"X-API-Key": "jobboerse-jobsuche"},
    "xapikey-clientid": {"X-API-Key": CLIENT_ID},
}


def probe(url: str, headers: dict[str, str], *, post: bool = False) -> str:
    try:
        if post:
            response = requests.post(
                url,
                headers=headers,
                data={
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "grant_type": "client_credentials",
                },
                timeout=20,
            )
        else:
            response = requests.get(
                url,
                headers=headers,
                params={"was": "data engineer", "page": 1, "size": 1},
                timeout=20,
            )
    except requests.RequestException as exc:
        return f"ERR  {type(exc).__name__}"

    body = response.text[:90].replace("\n", " ").strip()
    return f"{response.status_code}  {body}"


def headers_for(ua_name: str, auth_name: str) -> dict[str, str]:
    headers = {"Accept": "application/json", **AUTH_VARIANTS[auth_name]}
    ua = USER_AGENTS[ua_name]
    if ua:
        headers["User-Agent"] = ua
    return headers


def main() -> None:
    print("\n=== TOKEN ENDPOINT (POST) ===")
    for ua_name in USER_AGENTS:
        result = probe(TOKEN_URL, headers_for(ua_name, "no-auth"), post=True)
        print(f"{ua_name:<16} {result}")

    print("\n=== SEARCH ENDPOINTS (GET) ===")
    for path in SEARCH_PATHS:
        print(f"\n-- {path}")
        for ua_name in USER_AGENTS:
            for auth_name in AUTH_VARIANTS:
                result = probe(HOST + path, headers_for(ua_name, auth_name))
                if result.startswith(("200", "401")) or "ERR" in result:
                    flag = "  <<<"
                else:
                    flag = ""
                print(f"  {ua_name:<16} {auth_name:<17} {result}{flag}")


if __name__ == "__main__":
    main()
