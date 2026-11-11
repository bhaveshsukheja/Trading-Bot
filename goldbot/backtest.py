"""Backtest of the technical signal on historical bars.

The optional dollar-index input is not included. Signals are computed on a bar's
close and executed at the next bar's open, with per-side costs.
"""
import pandas as pd

from .broker import PaperBroker
from .strategy import decide, technical_frame


def run_backtest(df: pd.DataFrame, cfg) -> dict:
    tf = technical_frame(df, cfg)
    bars = df.loc[tf.index]
    bk = PaperBroker(cfg)
    pending, curve = None, []
    for (ts, bar), score, atr in zip(bars.iterrows(), tf["score"], tf["atr"]):
        t = ts.isoformat()
        if pending:
            action, sig_atr = pending
            if bk.direction and action in ("close", "long", "short"):
                bk.close(bar["open"], t, "signal")
            if action in ("long", "short") and bk.can_open(t[:10])[0]:
                bk.open(1 if action == "long" else -1, bar["open"], sig_atr, t)
            pending = None
        bk.check_exits(bar["open"], bar["high"], bar["low"], t)
        action = decide(score, bk.direction, cfg)
        if action != "hold":
            pending = (action, atr)
        curve.append(bk.mark_equity(bar["close"]))
    eq = pd.Series(curve, index=bars.index)
    tr = pd.DataFrame(bk.s["trades"])
    wins = tr[tr.pnl > 0].pnl.sum() if len(tr) else 0.0
    losses = -tr[tr.pnl <= 0].pnl.sum() if len(tr) else 0.0
    return {
        "from": str(bars.index[0]), "to": str(bars.index[-1]), "bars": len(bars),
        "return_pct": round((eq.iloc[-1] / cfg.starting_equity - 1) * 100, 2),
        "buy_hold_pct": round((bars["close"].iloc[-1] / bars["close"].iloc[0] - 1) * 100, 2),
        "max_drawdown_pct": round(((eq / eq.cummax()) - 1).min() * 100, 2),
        "trades": len(tr),
        "win_rate_pct": round((tr.pnl > 0).mean() * 100, 1) if len(tr) else None,
        "profit_factor": round(wins / losses, 2) if losses else None,
        "halted_by_kill_switch": bk.s["halted"],
        "equity_curve": eq, "trade_log": tr,
    }
