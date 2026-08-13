"""Shared HTTP session.

One session with retries for the whole process: these are free public endpoints
and hammering them on transient failure is both rude and counterproductive.
"""

from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "job-alert-etl/0.1 (+https://github.com/)"
DEFAULT_TIMEOUT = 30


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=1.5,          # 0s, 1.5s, 3s, 6s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return session


_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = build_session()
    return _session


def get_json(url: str, **kwargs: Any) -> Any:
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    response = session().get(url, **kwargs)
    response.raise_for_status()
    # Several of these feeds omit or misdeclare charset; the payloads are UTF-8.
    response.encoding = response.encoding or "utf-8"
    return response.json()
