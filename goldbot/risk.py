"""Account-level limits, evaluated on the broker-reported equity."""


class RiskGuard:
    def __init__(self, cfg, state: dict):
        self.cfg, self.s = cfg, state
        for k, v in (("peak_equity", None), ("day", None), ("day_start_equity", None), ("halted", False)):
            state.setdefault(k, v)

    def update(self, equity: float, day: str) -> None:
        s = self.s
        if s["day"] != day:
            s["day"], s["day_start_equity"] = day, equity
        s["peak_equity"] = max(s["peak_equity"] or equity, equity)
        if equity <= s["peak_equity"] * (1 - self.cfg.max_drawdown):
            s["halted"] = True

    def can_open(self, equity: float) -> tuple[bool, str]:
        if self.s["halted"]:
            return False, 'halted: max drawdown reached (set "halted": false in the state file to resume)'
        if equity <= self.s["day_start_equity"] * (1 - self.cfg.daily_loss_limit):
            return False, "daily loss limit reached"
        return True, ""


def size_lots(equity: float, stop_dist: float, price: float, info, cfg) -> float:
    """Lots such that hitting the stop loses risk_per_trade of equity, rounded DOWN to
    the broker's volume step. Returns 0.0 when even the minimum lot would risk more."""
    contract = info.trade_contract_size
    lots = min(cfg.risk_per_trade * equity / (stop_dist * contract),
               cfg.max_leverage * equity / (price * contract), info.volume_max)
    steps = int(lots / info.volume_step + 1e-9)
    lots = round(steps * info.volume_step, 8)
    return lots if lots >= info.volume_min else 0.0
