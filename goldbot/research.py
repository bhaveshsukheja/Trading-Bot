"""Context research: macro drivers and news headlines.

Both are deliberately simple heuristics, not forecasts.
- Macro: gold has historically tended to move against the US dollar and
  real yields; a rising dollar index / 10y yield counts against gold.
- News: whole-word keyword tally on recent Yahoo Finance RSS headlines about the
  gold market (company news is filtered out). Crude by design, which is why it
  carries the smallest weight.
"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .data import DataError, fetch_bars, http_get

RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline"
_w = lambda words: re.compile(r"\b(?:" + words + r")\b", re.I)
GOLD = _w(r"gold|bullion|precious metals?")
MACRO = _w(r"fed|federal reserve|inflation|dollar|yields?|treasur(?:y|ies)|rate cuts?|rate hikes?|central banks?")
COMPANY = _w(r"q[1-4]|quarter|earnings|results|drill\w*|exploration|royalt\w+|dividend|mine project|"
             r"shares|stock|asx|tsx|ipo|ira|etf investing|inc|corp|ltd")
UP = _w(r"rises?|gains?|jumps?|surges?|rall(?:y|ies)|climbs?|soars?|rebounds?|best (?:day|week|month)|"
        r"record highs?|all-time highs?|rush(?:es|ing)?|bought more|safe[- ]haven demand|"
        r"rate cuts?|dovish")
DOWN = _w(r"falls?|fell|drops?|slips?|slides?|tumbles?|retreats?|sinks?|plunges?|crash(?:es)?|"
          r"worst (?:day|week|month)|\d+-(?:week|month) lows?|outflows|profit-taking|"
          r"rate hikes?|hawkish|strong dollar|(?:rising|higher) (?:treasury )?yields")
_DOLLAR_DOWN = _w(r"dollar (?:falls|tanks|slips|slides|weakens|drops)|yields (?:fall|drop|slide)")
_DOLLAR_UP = _w(r"dollar (?:rises|gains|strengthens|climbs|jumps)|yields (?:rise|climb|jump)")


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


def is_market_headline(title: str) -> bool:
    """About the gold market or its macro drivers, and not single-company news."""
    return bool(GOLD.search(title) or MACRO.search(title)) and not COMPANY.search(title)


def score_headline(title: str) -> int:
    """+ is supportive of gold, - is negative. Whole-word matches on the title only."""
    # a falling dollar / falling yields count FOR gold, so score those phrases
    # first and strip them before counting plain up/down verbs
    up, down = len(_DOLLAR_DOWN.findall(title)), len(_DOLLAR_UP.findall(title))
    rest = _DOLLAR_UP.sub(" ", _DOLLAR_DOWN.sub(" ", title))
    return up + len(UP.findall(rest)) - down - len(DOWN.findall(rest))


def news_score(cfg, now: datetime | None = None) -> dict:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=cfg.news_max_age_days)
    seen, scored, errors = set(), [], []
    for sym in cfg.news_symbols:
        try:
            r = http_get(RSS, {"s": sym, "region": "US", "lang": "en-US"})
            items = ET.fromstring(r.content).findall("./channel/item")
        except (DataError, ET.ParseError) as e:
            errors.append(f"{sym}: {e!r}")
            continue
        for it in items:
            title = (it.findtext("title") or "").strip()
            try:
                fresh = parsedate_to_datetime(it.findtext("pubDate") or "") >= cutoff
            except (TypeError, ValueError):
                fresh = False
            if fresh and title not in seen and is_market_headline(title):
                seen.add(title)
                scored.append((score_headline(title), title))
    if not scored:
        raise DataError("no recent gold-market headlines" + (f" ({'; '.join(errors)})" if errors else ""))
    total = sum(s for s, _ in scored)
    return {"score": _clip(total / max(3, len(scored))), "headlines_used": len(scored),
            "scored": [f"{s:+d} {t}" for s, t in sorted(scored, key=lambda x: -abs(x[0]))[:5]]}
