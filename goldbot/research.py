"""Context research: macro drivers and news headlines.

Both are deliberately simple heuristics, not forecasts.
- Macro: gold has historically tended to move against the US dollar and
  real yields; a rising dollar index / 10y yield counts against gold.
- News: keyword tally on Yahoo Finance RSS headlines. Crude by design, which
  is why it carries the smallest weight.
"""
import xml.etree.ElementTree as ET

from .data import DataError, fetch_bars, http_get

RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline"
RELEVANT = ("gold", "bullion", "precious metal", "fed", "inflation", "dollar", "yield",
            "treasury", "rate cut", "rate hike", "geopolit", "safe haven", "safe-haven",
            "central bank", "tariff", "recession")
BULLISH = ("gold rises", "gold gains", "gold jumps", "gold surges", "gold rallies",
           "gold climbs", "record high", "safe haven", "safe-haven", "rate cut",
           "dollar falls", "dollar weak", "dollar slips", "yields fall", "yields drop",
           "geopolit", "war", "recession", "central bank buying", "dovish", "tariff")
BEARISH = ("gold falls", "gold drops", "gold slips", "gold slides", "gold tumbles",
           "gold retreats", "gold sinks", "rate hike", "dollar rises", "dollar strength",
           "dollar gains", "strong dollar", "rising treasury yields", "yields rise",
           "yields climb", "yields jump", "hawkish", "risk-on", "profit-taking")


def _clip(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def macro_score(cfg) -> dict:
    out, parts = {}, []
    for name, sym, scale in (("dollar", cfg.dollar_symbol, 0.02), ("yield10y", cfg.yield_symbol, 0.05)):
        try:
            c = fetch_bars(sym, "1d", "3mo")["close"]
            chg = c.iloc[-1] / c.iloc[-11] - 1          # ~2 trading weeks
            out[f"{name}_10d_change"] = round(float(chg), 5)
            parts.append(_clip(-chg / scale))
        except (DataError, IndexError) as e:
            out[f"{name}_error"] = str(e)
    if not parts:
        raise DataError("no macro data available")
    out["score"] = sum(parts) / len(parts)
    return out


def score_headline(text: str) -> int:
    t = text.lower()
    return sum(k in t for k in BULLISH) - sum(k in t for k in BEARISH)


def news_score(cfg) -> dict:
    r = http_get(RSS, {"s": cfg.symbol, "region": "US", "lang": "en-US"})
    try:
        items = ET.fromstring(r.content).findall("./channel/item")
    except ET.ParseError as e:
        raise DataError(f"bad RSS: {e!r}") from e
    scored = []
    for it in items:
        title = it.findtext("title") or ""
        text = f"{title}. {it.findtext('description') or ''}"
        if any(k in text.lower() for k in RELEVANT):
            scored.append((score_headline(text), title))
    if not scored:
        raise DataError("no gold-relevant headlines")
    total = sum(s for s, _ in scored)
    return {"score": _clip(total / max(3, len(scored))), "headlines_used": len(scored),
            "top": [t for s, t in sorted(scored, key=lambda x: -abs(x[0]))[:3]]}
