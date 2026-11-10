"""Technical indicators computed from OHLCV candles (the same maths a
TradingView chart shows; TradingView has no public data API to read them from)."""


def ema(values, period):
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes, period=14):
    """Wilder's RSI of the last close, or None with too little data."""
    if len(closes) <= period:
        return None
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    avg_gain, avg_loss = gains / period, losses / period
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(d, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0)) / period
    if avg_loss == 0:
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def analyze(candles):
    """Indicator snapshot from oldest-first (ts, o, h, l, c, vol) candles."""
    if len(candles) < 30:
        return None
    closes = [c[4] for c in candles]
    vols = [c[5] for c in candles]
    ema9, ema21 = ema(closes, 9), ema(closes, 21)
    # The newest candle is still forming, so compare the last closed one.
    avg_vol = sum(vols[-22:-2]) / 20
    total_vol = sum(vols)
    vwap = sum(((c[2] + c[3] + c[4]) / 3) * c[5] for c in candles) / total_vol if total_vol else closes[-1]
    return {
        "price": closes[-1],
        "ema9": ema9[-1],
        "ema21": ema21[-1],
        "ema_bullish": ema9[-1] > ema21[-1],
        "ema21_rising": ema21[-1] > ema21[-4],
        "rsi": rsi(closes),
        "vwap": vwap,
        "above_vwap": closes[-1] > vwap,
        "volume_spike": vols[-2] / avg_vol if avg_vol else 0.0,
    }
