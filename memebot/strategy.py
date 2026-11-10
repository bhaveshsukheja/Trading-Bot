"""Hard filters and the composite entry score.

Every number here is a heuristic that has NOT been backtested. Treat the score
as a way of ranking candidates, not as a prediction.
"""
import time


def _ramp(x, lo, hi):
    """0 at/below lo, 1 at/above hi, linear in between."""
    if x is None:
        return 0.0
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))


def _num(d, *keys):
    for k in keys:
        d = (d or {}).get(k)
    return d or 0


def basic_reject(pair, f):
    """Cheap filters using only DexScreener pair data. Returns a reason or None."""
    liq = _num(pair, "liquidity", "usd")
    mcap = pair.get("marketCap") or pair.get("fdv") or 0
    created = pair.get("pairCreatedAt")
    if liq < f["min_liquidity_usd"]:
        return f"liquidity ${liq:,.0f}"
    if _num(pair, "volume", "h24") < f["min_volume_h24_usd"]:
        return "24h volume too low"
    if not f["min_market_cap_usd"] <= mcap <= f["max_market_cap_usd"]:
        return f"market cap ${mcap:,.0f}"
    if not created:
        return "unknown age"
    age_h = (time.time() - created / 1000) / 3600
    if age_h < f["min_age_hours"] or age_h > f["max_age_days"] * 24:
        return f"age {age_h:.1f}h"
    return None


def deep_reject(rug, stats, f):
    """Filters needing RugCheck and trade data. Returns a reason or None."""
    if rug is None:
        return "no safety report"
    if rug["danger"]:
        return "rugcheck danger: " + ", ".join(rug["danger"])
    if rug["score"] is None or rug["score"] > f["max_rug_score_normalised"]:
        return f"rugcheck score {rug['score']}"
    if not stats:
        # Without trades we cannot check for wash trading, so do not buy blind.
        return "no trade data"
    if stats["top_trader_share"] > f["max_top_trader_volume_share"]:
        return f"one wallet is {stats['top_trader_share']:.0%} of volume"
    return None


def momentum(pair):
    h1 = _num(pair, "priceChange", "h1")
    m5 = _num(pair, "priceChange", "m5")
    h6 = _num(pair, "priceChange", "h6")
    # Reward a healthy hourly move, fade it out once the move looks parabolic.
    s_h1 = _ramp(h1, 0, 15) * (1 - _ramp(h1, 80, 200))
    s_m5 = 1.0 if m5 > 0 else 0.3 if m5 > -3 else 0.0
    return 0.6 * s_h1 + 0.25 * s_m5 + 0.15 * (h6 > 0)


def flow(pair, stats):
    buys, sells = _num(pair, "txns", "h1", "buys"), _num(pair, "txns", "h1", "sells")
    ratio = buys / (buys + sells) if buys + sells else 0
    liq = _num(pair, "liquidity", "usd")
    turnover = _num(pair, "volume", "h1") / liq if liq else 0
    parts = [_ramp(ratio, 0.45, 0.65), _ramp(turnover, 0.1, 1.0)]
    if stats:
        parts.append(_ramp(stats["net_flow"], 0.0, 0.3))
        parts.append(1.0 if stats["buyers"] > stats["sellers"] else 0.0)
    return sum(parts) / len(parts)


def technicals(ta):
    if not ta:
        return 0.0
    s = 0.3 * ta["ema_bullish"] + 0.15 * ta["ema21_rising"] + 0.2 * ta["above_vwap"]
    rsi = ta["rsi"]
    if rsi is not None:
        if 50 <= rsi <= 75:
            s += 0.2
        elif rsi > 85:      # overbought: likely late
            s -= 0.2
    s += 0.15 * _ramp(ta["volume_spike"], 1.0, 2.0)
    return max(0.0, s)


def wallet_signal(stats):
    if not stats:
        return 0.0
    n = len(stats["followed_buyers"]) - len(stats["followed_sellers"])
    return 0.0 if n <= 0 else 0.6 if n == 1 else 1.0


def social(x):
    """None when X data is unavailable, so its weight can be redistributed."""
    if x is None:
        return None
    return 0.6 * _ramp(x["authors"], 5, 50) + 0.4 * (x["sentiment"] + 1) / 2


def score(components, s):
    """Weighted 0-100 score over the components that are available."""
    total = weight = 0.0
    for name, value in components.items():
        if value is not None:
            w = s[f"weight_{name}"]
            total += w * value
            weight += w
    return 100 * total / weight if weight else 0.0
