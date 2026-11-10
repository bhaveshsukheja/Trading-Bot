"""Paper broker: simulated account with ATR stops, targets and risk limits.

No real orders are ever sent. A live broker would implement the same
open/close/check_exits surface against a real brokerage API.
"""
import json
import os


class PaperBroker:
    def __init__(self, cfg, state: dict | None = None):
        self.cfg = cfg
        self.s = state or {"equity": cfg.starting_equity, "peak_equity": cfg.starting_equity,
                           "position": None, "trades": [], "halted": False,
                           "day": None, "day_start_equity": cfg.starting_equity,
                           "last_bar": None}

    # ---- persistence ----
    @classmethod
    def load(cls, cfg):
        if os.path.exists(cfg.state_file):
            with open(cfg.state_file) as f:
                return cls(cfg, json.load(f))
        return cls(cfg)

    def save(self):
        os.makedirs(os.path.dirname(self.cfg.state_file) or ".", exist_ok=True)
        tmp = self.cfg.state_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.s, f, indent=1)
        os.replace(tmp, self.cfg.state_file)

    # ---- helpers ----
    @property
    def direction(self) -> int:
        return self.s["position"]["dir"] if self.s["position"] else 0

    def mark_equity(self, price: float) -> float:
        p = self.s["position"]
        return self.s["equity"] + ((price - p["entry"]) * p["dir"] * p["oz"] if p else 0.0)

    def can_open(self, day: str) -> tuple[bool, str]:
        s = self.s
        if s["day"] != day:
            s["day"], s["day_start_equity"] = day, s["equity"]
        if s["halted"]:
            return False, "halted: max drawdown reached (reset manually in state file)"
        if s["equity"] <= s["day_start_equity"] * (1 - self.cfg.daily_loss_limit):
            return False, "daily loss limit reached"
        return True, ""

    # ---- orders ----
    def open(self, direction: int, price: float, atr: float, time: str) -> dict:
        assert self.s["position"] is None and direction in (1, -1) and atr > 0
        c = self.cfg
        fill = price + direction * c.cost_per_oz
        stop_dist = c.stop_atr * atr
        oz = min(c.risk_per_trade * self.s["equity"] / stop_dist,
                 c.max_leverage * self.s["equity"] / fill)
        self.s["position"] = {"dir": direction, "oz": round(oz, 4), "entry": round(fill, 2),
                              "stop": round(fill - direction * stop_dist, 2),
                              "target": round(fill + direction * c.target_atr * atr, 2),
                              "opened": time}
        return self.s["position"]

    def close(self, price: float, time: str, reason: str) -> dict:
        p = self.s["position"]
        fill = price - p["dir"] * self.cfg.cost_per_oz
        pnl = (fill - p["entry"]) * p["dir"] * p["oz"]
        s = self.s
        s["equity"] = round(s["equity"] + pnl, 2)
        s["peak_equity"] = max(s["peak_equity"], s["equity"])
        if s["equity"] <= s["peak_equity"] * (1 - self.cfg.max_drawdown):
            s["halted"] = True
        trade = {**p, "exit": round(fill, 2), "closed": time, "pnl": round(pnl, 2), "reason": reason}
        s["trades"].append(trade)
        s["position"] = None
        return trade

    def check_exits(self, o: float, h: float, l: float, time: str) -> dict | None:
        """Apply one bar to the open position. If stop and target both fall inside
        the bar, the stop is assumed to have been hit first (the pessimistic case).
        A bar that opens beyond a level fills at the open (gap)."""
        p = self.s["position"]
        if not p:
            return None
        d = p["dir"]
        if (o - p["stop"]) * d <= 0:
            return self.close(o, time, "stop (gap)")
        if (o - p["target"]) * d >= 0:
            return self.close(o, time, "target (gap)")
        if (l if d > 0 else h) * d <= p["stop"] * d:
            return self.close(p["stop"], time, "stop")
        if (h if d > 0 else l) * d >= p["target"] * d:
            return self.close(p["target"], time, "target")
        return None
