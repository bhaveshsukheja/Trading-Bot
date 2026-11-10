"""TradingView technical ratings via the scanner endpoint the website itself uses.

TradingView offers no official public API for this. The endpoint is
undocumented, may break, and automated use may be restricted by
TradingView's terms of use - check them before relying on it.
"""
import requests

from .data import HEADERS, DataError

URL = "https://scanner.tradingview.com/{market}/scan"
COLUMNS = ["Recommend.All|60", "Recommend.All|240", "Recommend.All", "close", "RSI|60"]


def fetch_rating(ticker: str, market: str = "cfd") -> dict:
    """Ratings are in [-1, 1]: below -0.5 strong sell ... above 0.5 strong buy."""
    body = {"symbols": {"tickers": [ticker], "query": {"types": []}}, "columns": COLUMNS}
    try:
        r = requests.post(URL.format(market=market), json=body, headers=HEADERS, timeout=20)
        r.raise_for_status()
        d = r.json()["data"][0]["d"]
        h1, h4, d1, close, rsi = d
        vals = [float(h1), float(h4), float(d1)]
    except Exception as e:  # network, shape or null values
        raise DataError(f"TradingView rating unavailable: {e!r}") from e
    score = 0.4 * vals[0] + 0.4 * vals[1] + 0.2 * vals[2]
    return {"score": max(-1.0, min(1.0, score)), "rating_1h": vals[0],
            "rating_4h": vals[1], "rating_1d": vals[2], "tv_close": close, "tv_rsi_1h": rsi}
