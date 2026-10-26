"""Polite, cached HTTP GET.

Every response is written under data/raw/<host>/<path> the first time it is
fetched and read from disk afterwards, so a rerun makes no network calls and
the exact bytes behind every document stay inspectable.
"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from .config import RAW

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
PAUSE_SECONDS = 0.4

_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT
_last_call = [0.0]


def cache_path(url: str) -> Path:
    parts = urlparse(url)
    path = parts.path.strip("/") or "index"
    if parts.query:
        path += "__" + hashlib.sha1(parts.query.encode()).hexdigest()[:12]
    return RAW / parts.netloc / re.sub(r"[^A-Za-z0-9._/-]", "_", path)


def get(url: str, *, refresh: bool = False, timeout: int = 60) -> bytes:
    """Return the body of `url`; raise FileNotFoundError on 404."""
    path = cache_path(url)
    if path.exists() and not refresh:
        return path.read_bytes()
    for attempt in range(4):
        wait = PAUSE_SECONDS - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        try:
            resp = _session.get(url, timeout=timeout)
            _last_call[0] = time.monotonic()
            if resp.status_code == 404:
                raise FileNotFoundError(url)
            resp.raise_for_status()
            break
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError):
            if attempt == 3:
                raise
            time.sleep(2**attempt)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    return resp.content
