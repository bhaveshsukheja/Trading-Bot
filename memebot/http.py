"""Small HTTP helper: per-host throttling, retries, JSON decoding."""
import logging
import time
from urllib.parse import urlparse

import requests

log = logging.getLogger("memebot.http")

# Minimum seconds between calls to a host. Conservative guesses at free-tier
# limits; raise them if you see HTTP 429 in the log.
MIN_INTERVAL = {
    "api.geckoterminal.com": 8.0,   # shorter spacings produced HTTP 429 in testing
    "api.dexscreener.com": 0.5,
    "api.rugcheck.xyz": 1.0,
    "api.x.com": 1.0,
}

_session = requests.Session()
_session.headers["User-Agent"] = "memebot/0.1"
_last_call: dict[str, float] = {}


class HttpError(Exception):
    pass


def get_json(url, params=None, headers=None, retries=2, timeout=20):
    host = urlparse(url).netloc
    for attempt in range(retries + 1):
        wait = _last_call.get(host, 0) + MIN_INTERVAL.get(host, 0.2) - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()
        try:
            r = _session.get(url, params=params, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            err = str(e)
        else:
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    err = "invalid JSON"
            elif r.status_code == 429 or r.status_code >= 500:
                err = f"HTTP {r.status_code}"
                if r.status_code == 429:
                    time.sleep(20)  # rate limited: back off well beyond the normal spacing
            else:
                # 4xx other than 429 will not get better on retry.
                raise HttpError(f"{url}: HTTP {r.status_code} {r.text[:200]}")
        if attempt < retries:
            time.sleep(3 * (attempt + 1))
    raise HttpError(f"{url}: {err}")
