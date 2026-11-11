"""One cycle: read account and bars -> score -> risk check -> trade -> journal."""
import json
import os
from datetime import datetime, timezone

from .mt5gw import BUY, MT5Error
from .risk import RiskGuard
from .strategy import blend, decide, technical_frame


def load_state(cfg) -> dict:
    if os.path.exists(cfg.state_file):
        with open(cfg.state_file) as f:
            return json.load(f)
    return {"last_bar": None, "ticket": None}


def save_state(cfg, state: dict) -> None:
    os.makedirs(os.path.dirname(cfg.state_file) or ".", exist_ok=True)
    tmp = cfg.state_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, cfg.state_file)


def dollar_score(cfg, gw):
    """Gold has historically tended to move against the US dollar: a rising dollar
    index counts against gold. Off unless dollar_symbol is set. A heuristic, not a forecast."""
    if not cfg.dollar_symbol:
        return None, None
    try:
        c = gw.bars(cfg.dollar_symbol, "D1", 12)["close"]
        chg = float(c.iloc[-1] / c.iloc[-11] - 1)
        return max(-1.0, min(1.0, -chg / 0.02)), round(chg, 5)
    except (MT5Error, IndexError) as e:
        return None, str(e)


def run_cycle(cfg, gw, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    state = load_state(cfg)
    guard = RiskGuard(cfg, state)
    equity = float(gw.account().equity)
    done = gw.bars(cfg.symbol, cfg.timeframe, cfg.bars)
    last_bar = str(done.index[-1])
    pos = gw.position()
    rec = {"time": now.isoformat(timespec="seconds"), "equity": equity,
           "last_bar": last_bar, "close": float(done["close"].iloc[-1]), "events": []}

    # a position we opened that is gone was closed by its stop/target (or by hand)
    if state.get("ticket") and (pos is None or pos.ticket != state["ticket"]):
        rec["events"].append({"closed_by_broker": state["ticket"], "pnl": gw.closed_pnl(state["ticket"])})
        state["ticket"] = None
    guard.update(equity, now.strftime("%Y-%m-%d"))

    if state["last_bar"] == last_bar:
        rec["action"] = "skip: no new completed bar"
    else:
        tf = technical_frame(done, cfg)
        if tf.empty:
            raise MT5Error(f"only {len(done)} bars available; need more than {cfg.ema_slow}")
        tech, atr = float(tf["score"].iloc[-1]), float(tf["atr"].iloc[-1])
        macro, macro_detail = dollar_score(cfg, gw)
        scores = {"technical": tech, "macro": macro}
        score = blend(scores, cfg.weights)
        direction = 0 if pos is None else (1 if pos.type == BUY else -1)
        action = decide(score, direction, cfg)
        rec.update(score=round(score, 4), atr=round(atr, 2), action=action,
                   scores={k: (round(v, 4) if v is not None else None) for k, v in scores.items()},
                   dollar_10d_change=macro_detail)
        try:
            if action != "hold" and pos is not None:
                rec["events"].append({"closed": gw.close(pos)})
                state["ticket"] = None
            if action in ("long", "short"):
                ok, why = guard.can_open(equity)
                if ok:
                    opened = gw.open(1 if action == "long" else -1, atr, equity)
                    state["ticket"] = opened["ticket"]
                    rec["events"].append({"opened": opened})
                else:
                    rec["action"] = f"blocked: {why}"
        except MT5Error as e:
            rec["action"] = f"{action} failed: {e}"
        state["last_bar"] = last_bar

    rec["halted"] = state["halted"]
    save_state(cfg, state)
    os.makedirs(os.path.dirname(cfg.journal_file) or ".", exist_ok=True)
    with open(cfg.journal_file, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    return rec
