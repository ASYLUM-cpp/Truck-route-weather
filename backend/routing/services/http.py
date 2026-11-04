"""Pooled HTTP sessions with retries for transient upstream failures."""

from __future__ import annotations

import threading

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_local = threading.local()


def session() -> requests.Session:
    """One session per thread; sessions are reused for connection pooling."""
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        retry = Retry(
            total=2,
            backoff_factor=0.4,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        s.mount("https://", adapter)
        s.headers["User-Agent"] = "truck-route-weather/1.0"
        _local.session = s
    return s
