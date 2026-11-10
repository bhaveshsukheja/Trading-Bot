"""Paper-trading portfolio with simulated fees, slippage and price impact.

No real orders are sent. Real fills will be worse than these in fast markets
(failed transactions, MEV, and pools that are drained before you can sell).
"""
import logging
import time

from . import db

log = logging.getLogger("memebot.portfolio")


class Portfolio:
    def __init__(self, con, cfg):
        self.con = con
        self.costs = cfg["costs"]
        self.risk = cfg["risk"]
        self.exits = cfg["exits"]
        if db.kv_get(con, "cash") is None:
            db.kv_set(con, "cash", self.risk["starting_cash_usd"])

    # --- state ---------------------------------------------------------
    @property
    def cash(self):
        return db.kv_get(self.con, "cash")

    def open_positions(self):
        return self.con.execute("SELECT * FROM positions WHERE status='open'").fetchall()

    def equity(self):
        held = sum(p["tokens"] * p["last_price"] for p in self.open_positions())
        return self.cash + held

    def _day_start_equity(self):
        today = time.strftime("%Y-%m-%d", time.gmtime())
        day = db.kv_get(self.con, "day")
        if not day or day["date"] != today:
            day = {"date": today, "equity": self.equity()}
            db.kv_set(self.con, "day", day)
        return day["equity"]

    def can_open(self, token):
        """Returns None if a new position is allowed, else the reason it is not."""
        start = self._day_start_equity()
        if self.equity() <= start * (1 - self.risk["daily_loss_limit_pct"]):
            return "daily loss limit reached"
        positions = self.open_positions()
        if len(positions) >= self.risk["max_open_positions"]:
            return "max open positions"
        if any(p["token"] == token for p in positions):
            return "already held"
        last = self.con.execute(
            "SELECT MAX(exit_ts) AS ts FROM positions WHERE token=?", (token,)).fetchone()["ts"]
        if last and time.time() - last < self.risk["reentry_cooldown_hours"] * 3600:
            return "re-entry cooldown"
        return None

    # --- execution -----------------------------------------------------
    def _impact(self, usd, liquidity_usd):
        # Constant-product pool: roughly trade size over one side of the pool.
        return usd / (liquidity_usd / 2) if liquidity_usd else 1.0

    def buy(self, token, symbol, pair, price, liquidity_usd, score):
        usd = min(self.equity() * self.risk["position_pct"], self.cash)
        if usd < 5:
            return False
        fill = price * (1 + self._impact(usd, liquidity_usd) + self.costs["base_slippage_pct"])
        spendable = usd * (1 - self.costs["fee_pct"]) - self.costs["network_fee_usd"]
        tokens = spendable / fill
        now = time.time()
        self.con.execute(
            "INSERT INTO positions (token, symbol, pair, entry_ts, entry_price, tokens, cost_usd,"
            " last_price, peak_price, entry_liquidity, score) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (token, symbol, pair, now, fill, tokens, usd, price, price, liquidity_usd, score))
        self.con.execute(
            "INSERT INTO fills (ts, token, symbol, side, tokens, price, usd, reason)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (now, token, symbol, "buy", tokens, fill, usd, f"score {score:.0f}"))
        db.kv_set(self.con, "cash", self.cash - usd)
        log.info("BUY  %s $%.2f @ %.8g (score %.0f)", symbol, usd, fill, score)
        return True

    def sell(self, pos, fraction, price, liquidity_usd, reason):
        tokens = pos["tokens"] * fraction
        gross = tokens * price
        fill = price * max(0.0, 1 - self._impact(gross, liquidity_usd) - self.costs["base_slippage_pct"])
        proceeds = max(0.0, tokens * fill * (1 - self.costs["fee_pct"]) - self.costs["network_fee_usd"])
        now = time.time()
        left = pos["tokens"] - tokens
        closed = fraction >= 1
        self.con.execute(
            "UPDATE positions SET tokens=?, proceeds_usd=proceeds_usd+?, tp_done=?, status=?,"
            " exit_ts=?, exit_reason=? WHERE id=?",
            (left, proceeds, 1 if not closed else pos["tp_done"], "closed" if closed else "open",
             now if closed else None, reason if closed else None, pos["id"]))
        self.con.execute(
            "INSERT INTO fills (ts, token, symbol, side, tokens, price, usd, reason)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (now, pos["token"], pos["symbol"], "sell", tokens, fill, proceeds, reason))
        db.kv_set(self.con, "cash", self.cash + proceeds)
        log.info("SELL %s %.0f%% $%.2f @ %.8g (%s)", pos["symbol"], fraction * 100, proceeds, fill, reason)

    # --- exits ---------------------------------------------------------
    def manage(self, pos, price, liquidity_usd):
        """Update a position with the latest price and apply the exit rules."""
        peak = max(pos["peak_price"], price)
        self.con.execute("UPDATE positions SET last_price=?, peak_price=? WHERE id=?",
                         (price, peak, pos["id"]))
        self.con.commit()
        e = self.exits
        change = price / pos["entry_price"] - 1
        held_hours = (time.time() - pos["entry_ts"]) / 3600

        if liquidity_usd < pos["entry_liquidity"] * (1 - e["liquidity_drop_exit_pct"]):
            reason = "liquidity dropped"
        elif change <= -e["stop_loss_pct"]:
            reason = "stop loss"
        elif (peak / pos["entry_price"] - 1 >= e["trailing_activate_pct"]
              and price <= peak * (1 - e["trailing_stop_pct"])):
            reason = "trailing stop"
        elif held_hours >= e["max_hold_hours"]:
            reason = "max hold time"
        elif change >= e["take_profit_pct"] and not pos["tp_done"]:
            self.sell(pos, e["take_profit_fraction"], price, liquidity_usd, "take profit")
            return
        else:
            return
        self.sell(pos, 1.0, price, liquidity_usd, reason)
