"""Price history from Yahoo Finance's chart endpoint.

This endpoint is unofficial and undocumented: it can change, rate-limit or
disappear without notice, and futures quotes on it are typically delayed.

WARNING: Yahoo's Terms of Service (checked 2026-11-10, "Last updated: 1 November
2026") prohibit collecting data from its services by automated means without
express prior permission. Replace this module with a licensed data source
before running the bot unattended.
"""
import time
from urllib.parse import quote

import pandas as pd
import requests

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
HEADERS = {"User-Agent": "Mozilla/5.0"}
INTERVAL_SECONDS = {"15m": 900, "30m": 1800, "1h": 3600, "1d": 86400}


class DataError(RuntimeError):
    pass


def http_get(url, params=None, tries=3, **kw):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=20, **kw)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last = repr(e)
        time.sleep(2 ** i)
    raise DataError(f"GET {url} failed: {last}")


def fetch_bars(symbol: str, interval: str = "1h", range_: str = "60d") -> pd.DataFrame:
    """OHLCV bars indexed by UTC bar-open time. May include the bar still forming."""
    r = http_get(URL.format(sym=quote(symbol)), {"interval": interval, "range": range_})
    try:
        res = r.json()["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        df = pd.DataFrame(
            {k: q[k] for k in ("open", "high", "low", "close", "volume")},
            index=pd.to_datetime(res["timestamp"], unit="s", utc=True))
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise DataError(f"unexpected Yahoo response for {symbol}: {e!r}") from e
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    if df.empty:
        raise DataError(f"no bars returned for {symbol}")
    return df


def split_completed(df: pd.DataFrame, interval: str, now: pd.Timestamp | None = None):
    """Return (completed bars, forming bar or None)."""
    now = now or pd.Timestamp.now(tz="UTC")
    step = pd.Timedelta(seconds=INTERVAL_SECONDS[interval])
    if df.index[-1] + step > now:
        return df.iloc[:-1], df.iloc[-1]
    return df, None
