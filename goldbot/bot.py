"""One live cycle: fetch -> research -> score -> risk check -> paper execute -> journal."""
import json
import os

import pandas as pd

from . import research, tradingview
from .broker import PaperBroker
from .data import INTERVAL_SECONDS, DataError, fetch_bars, split_completed
from .strategy import blend, decide, technical_frame


def _try(fn, *a):
    try:
        return fn(*a)
    except DataError as e:
        return {"score": None, "error": str(e)}


def run_cycle(cfg, now: pd.Timestamp | None = None) -> dict:
    now = now or pd.Timestamp.now(tz="UTC")
    bk = PaperBroker.load(cfg)
    rec = {"time": now.isoformat(timespec="seconds"), "events": []}

    df = fetch_bars(cfg.symbol, cfg.interval, cfg.history_range)   # DataError aborts the cycle
    done, forming = split_completed(df, cfg.interval, now)
    price = float(forming["close"] if forming is not None else done["close"].iloc[-1])
    last_bar = done.index[-1]
    rec.update(price=price, last_bar=last_bar.isoformat())
    stale = now - last_bar > pd.Timedelta(seconds=3 * INTERVAL_SECONDS[cfg.interval])

    # 1) exits: completed bars that began after the position was opened, then the latest price
    pos = bk.s["position"]
    if pos:
        seen = pd.Timestamp(bk.s["last_bar"]) if bk.s["last_bar"] else last_bar
        for ts, b in done[(done.index > seen) & (done.index >= pd.Timestamp(pos["opened"]))].iterrows():
            t = bk.check_exits(b["open"], b["high"], b["low"], ts.isoformat())
            if t:
                rec["events"].append({"closed": t})
                break
        if bk.s["position"] and not stale:
            t = bk.check_exits(price, price, price, rec["time"])
            if t:
                rec["events"].append({"closed": t})

    # 2) new signal only when a new bar has completed and the market is trading
    if stale:
        rec["action"] = "skip: market closed or data stale"
    elif bk.s["last_bar"] == rec["last_bar"]:
        rec["action"] = "skip: no new completed bar"
    else:
        tf = technical_frame(done, cfg)
        tech, atr = float(tf["score"].iloc[-1]), float(tf["atr"].iloc[-1])
        tv = _try(tradingview.fetch_rating, cfg.tv_ticker, cfg.tv_market)
        macro = _try(research.macro_score, cfg)
        news = _try(research.news_score, cfg)
        scores = {"technical": tech, "tradingview": tv["score"],
                  "macro": macro["score"], "news": news["score"]}
        score = blend(scores, cfg.weights)
        action = decide(score, bk.direction, cfg)
        rec.update(score=round(score, 4), atr=round(atr, 2), action=action,
                   scores={k: (round(v, 4) if v is not None else None) for k, v in scores.items()},
                   research={"tradingview": tv, "macro": macro, "news": news})
        if action != "hold" and bk.direction:
            rec["events"].append({"closed": bk.close(price, rec["time"], "signal")})
        if action in ("long", "short"):
            ok, why = bk.can_open(rec["time"][:10])
            if ok:
                rec["events"].append({"opened": bk.open(1 if action == "long" else -1, price, atr, rec["time"])})
            else:
                rec["action"] = f"blocked: {why}"
        bk.s["last_bar"] = rec["last_bar"]

    rec.update(equity=bk.s["equity"], marked_equity=round(bk.mark_equity(price), 2),
               position=bk.s["position"])
    bk.save()
    os.makedirs(os.path.dirname(cfg.journal_file) or ".", exist_ok=True)
    with open(cfg.journal_file, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    return rec
