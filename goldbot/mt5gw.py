"""Gateway to a running MetaTrader 5 terminal through the official `MetaTrader5`
Python package (Windows only; the terminal must be installed and logged in).

Function names and request fields follow the MetaQuotes reference at
https://www.mql5.com/en/docs/python_metatrader5 (read 2026-11-11). This module has
only been exercised against a stand-in, never a real terminal: see README.
"""
import pandas as pd

from .risk import size_lots

DEMO_TRADE_MODE = 0   # account_info().trade_mode: 0 demo, 1 contest, 2 real (MQL5 ENUM_ACCOUNT_TRADE_MODE)
BUY = 0               # positions_get()[i].type: 0 buy, 1 sell


class MT5Error(RuntimeError):
    pass


class Gateway:
    def __init__(self, cfg, mt5=None):
        if mt5 is None:
            try:
                import MetaTrader5 as mt5
            except ImportError as e:
                raise MT5Error("the MetaTrader5 package is not installed (it exists for "
                               "Windows only): pip install -r requirements.txt") from e
        self.m, self.cfg = mt5, cfg

    def _need(self, value, what):
        if value is None:
            raise MT5Error(f"{what} failed: {self.m.last_error()}")
        return value

    # ---- connection ----
    def initialize(self):
        """Attach to the terminal. The password is never passed: the terminal uses the
        one it has saved for the account."""
        c = self.cfg
        args = [c.terminal_path] if c.terminal_path else []
        kw = {k: v for k, v in (("login", c.login), ("server", c.server)) if v}
        if not self.m.initialize(*args, **kw):
            raise MT5Error(f"cannot connect to the MetaTrader 5 terminal: {self.m.last_error()}")

    def connect(self, require_tradable: bool = True):
        self.initialize()
        info = self.m.symbol_info(self.cfg.symbol)
        if info is None:
            raise MT5Error(f"symbol {self.cfg.symbol!r} not found at this broker; run "
                           "`python -m goldbot symbols` and put the right name in settings.json")
        if not info.visible and not self.m.symbol_select(self.cfg.symbol, True):
            raise MT5Error(f"cannot add {self.cfg.symbol} to Market Watch: {self.m.last_error()}")
        if require_tradable:
            a = self.account()
            if a.trade_mode != DEMO_TRADE_MODE and not self.cfg.allow_live_account:
                raise MT5Error("this is not a demo account; refusing to trade "
                               "(allow_live_account is false)")
            if a.currency != "USD" or info.currency_profit != "USD":
                raise MT5Error("position sizing assumes a USD account and a USD-quoted symbol; "
                               f"got account {a.currency}, symbol profit currency {info.currency_profit}")
        return self

    def shutdown(self):
        self.m.shutdown()

    # ---- reads ----
    def account(self):
        return self._need(self.m.account_info(), "account_info")

    def symbol_info(self):
        return self._need(self.m.symbol_info(self.cfg.symbol), "symbol_info")

    def tick(self):
        return self._need(self.m.symbol_info_tick(self.cfg.symbol), "symbol_info_tick")

    def find_symbols(self, mask: str = "*XAU*,*GOLD*"):
        return [s.name for s in self._need(self.m.symbols_get(group=mask), "symbols_get")]

    def bars(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        """Completed bars only: index 0 is the bar still forming, so start at 1.
        Bar times are whatever clock the broker's server uses, not necessarily UTC."""
        tf = getattr(self.m, f"TIMEFRAME_{timeframe}")
        rates = self.m.copy_rates_from_pos(symbol, tf, 1, count)
        if rates is None or len(rates) == 0:
            raise MT5Error(f"no bars for {symbol} {timeframe}: {self.m.last_error()}")
        df = pd.DataFrame(rates)
        df.index = pd.to_datetime(df["time"], unit="s")
        return df[["open", "high", "low", "close"]].astype(float)

    def position(self):
        """This bot's open position on the symbol (matched by magic number), or None."""
        ps = self._need(self.m.positions_get(symbol=self.cfg.symbol), "positions_get")
        mine = [p for p in ps if p.magic == self.cfg.magic]
        return mine[0] if mine else None

    def closed_pnl(self, ticket: int):
        """Realised result of a closed position, or None if history is unavailable."""
        deals = self.m.history_deals_get(position=ticket)
        if not deals:
            return None
        return round(sum(d.profit + getattr(d, "commission", 0.0) + getattr(d, "swap", 0.0)
                         for d in deals), 2)

    # ---- orders ----
    def _filling(self, info):
        # symbol_info().filling_mode is a bit mask (1 = fill-or-kill, 2 = immediate-or-cancel)
        if info.filling_mode & 2:
            return self.m.ORDER_FILLING_IOC
        if info.filling_mode & 1:
            return self.m.ORDER_FILLING_FOK
        return self.m.ORDER_FILLING_RETURN

    def _send(self, request: dict):
        res = self.m.order_send(request)
        if res is None:
            raise MT5Error(f"order_send failed: {self.m.last_error()}")
        if res.retcode != self.m.TRADE_RETCODE_DONE:
            raise MT5Error(f"order rejected: retcode {res.retcode} ({getattr(res, 'comment', '')})")
        return res

    def open(self, direction: int, atr: float, equity: float) -> dict:
        info, tick, c = self.symbol_info(), self.tick(), self.cfg
        price = tick.ask if direction > 0 else tick.bid
        stop_dist = c.stop_atr * atr
        lots = size_lots(equity, stop_dist, price, info, c)
        if lots <= 0:
            raise MT5Error("account too small: the broker's minimum lot would risk more than "
                           f"{c.risk_per_trade:.1%} of equity on this trade")
        req = {"action": self.m.TRADE_ACTION_DEAL, "symbol": c.symbol, "volume": lots,
               "type": self.m.ORDER_TYPE_BUY if direction > 0 else self.m.ORDER_TYPE_SELL,
               "price": price,
               "sl": round(price - direction * stop_dist, info.digits),
               "tp": round(price + direction * c.target_atr * atr, info.digits),
               "deviation": c.deviation_points, "magic": c.magic, "comment": "goldbot open",
               "type_time": self.m.ORDER_TIME_GTC, "type_filling": self._filling(info)}
        res = self._send(req)
        return {"ticket": res.order, "dir": direction, "lots": lots, "price": res.price,
                "sl": req["sl"], "tp": req["tp"]}

    def close(self, pos) -> dict:
        info, tick, c = self.symbol_info(), self.tick(), self.cfg
        is_buy = pos.type == BUY
        req = {"action": self.m.TRADE_ACTION_DEAL, "symbol": c.symbol, "volume": pos.volume,
               "type": self.m.ORDER_TYPE_SELL if is_buy else self.m.ORDER_TYPE_BUY,
               "position": pos.ticket, "price": tick.bid if is_buy else tick.ask,
               "deviation": c.deviation_points, "magic": c.magic, "comment": "goldbot close",
               "type_time": self.m.ORDER_TIME_GTC, "type_filling": self._filling(info)}
        res = self._send(req)
        return {"ticket": pos.ticket, "price": res.price, "pnl": self.closed_pnl(pos.ticket)}
