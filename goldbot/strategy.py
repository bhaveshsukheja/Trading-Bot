import pandas as pd

from . import indicators as ind


def technical_frame(df: pd.DataFrame, cfg) -> pd.DataFrame:
    """Per-bar technical score in [-1, 1] plus ATR. Uses only data up to each bar."""
    a = ind.atr(df)
    trend = ((ind.ema(df["close"], cfg.ema_fast) - ind.ema(df["close"], cfg.ema_slow)) / (2 * a)).clip(-1, 1)
    mom = (ind.macd_hist(df["close"]) / (0.25 * a)).clip(-1, 1)
    rsi = ((ind.rsi(df["close"]) - 50) / 20).clip(-1, 1)
    return pd.DataFrame({"score": 0.5 * trend + 0.3 * mom + 0.2 * rsi, "atr": a}).dropna()


def blend(scores: dict, weights: dict) -> float:
    """Weighted average over the sources that actually produced a score."""
    used = {k: v for k, v in scores.items() if v is not None and k in weights}
    w = sum(weights[k] for k in used)
    return sum(weights[k] * v for k, v in used.items()) / w if w else 0.0


def decide(score: float, position_dir: int, cfg) -> str:
    """Returns 'long', 'short', 'close' or 'hold'."""
    action = _decide(score, position_dir, cfg)
    if action == "short" and not cfg.allow_short:
        return "close" if position_dir > 0 else "hold"
    return action


def _decide(score: float, position_dir: int, cfg) -> str:
    if position_dir > 0 and score <= -cfg.exit_threshold:
        return "short" if score <= -cfg.entry_threshold else "close"
    if position_dir < 0 and score >= cfg.exit_threshold:
        return "long" if score >= cfg.entry_threshold else "close"
    if position_dir == 0:
        if score >= cfg.entry_threshold:
            return "long"
        if score <= -cfg.entry_threshold:
            return "short"
    return "hold"
