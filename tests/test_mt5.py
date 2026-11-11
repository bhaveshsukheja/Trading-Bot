"""Exercises the gateway and cycle against a stand-in for the MetaTrader5 module.
This checks the bot's own logic; it cannot prove a real terminal behaves the same."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import numpy as np
import pytest

from goldbot.bot import run_cycle
from goldbot.config import Config
from goldbot.mt5gw import Gateway, MT5Error
from goldbot.risk import RiskGuard, size_lots


class FakeMT5:
    TIMEFRAME_H1, TIMEFRAME_D1 = 16385, 16408
    TRADE_ACTION_DEAL, ORDER_TYPE_BUY, ORDER_TYPE_SELL = 1, 0, 1
    ORDER_TIME_GTC, ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 0, 1, 2
    TRADE_RETCODE_DONE = 10009

    def __init__(self, closes, equity=10_000.0, trade_mode=0):
        self.closes, self.requests, self.positions, self.next_ticket = list(closes), [], [], 100
        self.acct = NS(equity=equity, balance=equity, trade_mode=trade_mode, currency="USD",
                       server="Fake-Demo", login=1)
        self.info = NS(visible=True, trade_contract_size=100.0, volume_min=0.01, volume_step=0.01,
                       volume_max=50.0, digits=2, filling_mode=2, currency_profit="USD")
        self.reject = False

    def initialize(self, *args, **kw):
        self.init_call = (args, kw)
        return True
    def shutdown(self): pass
    def last_error(self): return (-1, "fake")
    def account_info(self): return self.acct
    def symbol_info(self, s): return self.info if s == "XAUUSD" else None
    def symbol_select(self, s, on): return True
    def symbol_info_tick(self, s): return NS(bid=self.closes[-1] - 0.1, ask=self.closes[-1] + 0.1)
    def positions_get(self, symbol=None): return tuple(self.positions)
    def history_deals_get(self, position=None): return (NS(profit=12.5, commission=-0.5, swap=0.0),)

    def copy_rates_from_pos(self, symbol, tf, start, count):
        assert start == 1                      # never the forming bar
        c = self.closes[-count:]
        return [{"time": 1_700_000_000 + 3600 * i, "open": x, "high": x + 1, "low": x - 1,
                 "close": x} for i, x in enumerate(c, len(self.closes) - len(c))]

    def order_send(self, req):
        self.requests.append(req)
        if self.reject:
            return NS(retcode=10027, comment="AutoTrading disabled by client")
        if "position" in req:
            self.positions = [p for p in self.positions if p.ticket != req["position"]]
        else:
            self.next_ticket += 1
            self.positions.append(NS(ticket=self.next_ticket, type=req["type"], volume=req["volume"],
                                     magic=req["magic"]))
        return NS(retcode=10009, order=self.next_ticket, price=req["price"], comment="done")


def make(tmp_path, closes, **kw):
    cfg = Config(state_file=str(tmp_path / "a.json"), journal_file=str(tmp_path / "j.jsonl"))
    fake = FakeMT5(closes, **kw)
    return cfg, fake, Gateway(cfg, fake).connect()


UP = list(np.linspace(3000, 4000, 700))
DOWN = UP[::-1]


def test_sizing_rounds_down_and_respects_min_lot_and_leverage():
    cfg, info = Config(), FakeMT5([1]).info
    assert size_lots(10_000, 48.0, 4000.0, info, cfg) == 0.02     # 2.08 oz -> 0.0208 lots -> 0.02
    assert size_lots(1_000, 120.0, 4000.0, info, cfg) == 0.0      # min lot would risk > 1%
    assert size_lots(10_000, 0.5, 4000.0, info, cfg) == 0.12      # capped at 5x leverage


def test_opens_long_with_stop_and_target_then_holds(tmp_path):
    cfg, fake, gw = make(tmp_path, UP)
    r = run_cycle(cfg, gw)
    assert r["action"] == "long"
    req = fake.requests[0]
    assert req["type"] == fake.ORDER_TYPE_BUY and req["magic"] == cfg.magic
    assert req["sl"] < req["price"] < req["tp"]
    assert abs((req["tp"] - req["price"]) / (req["price"] - req["sl"]) - 2) < 0.01
    risk = (req["price"] - req["sl"]) * req["volume"] * 100
    assert 0 < risk <= 100.0                                       # at most 1% of 10k
    assert run_cycle(cfg, gw)["action"] == "skip: no new completed bar"
    assert len(fake.requests) == 1


def test_reverses_to_short_on_downtrend(tmp_path):
    cfg, fake, gw = make(tmp_path, UP)
    run_cycle(cfg, gw)
    fake.closes = UP + DOWN                    # later bars: the trend has turned down
    r = run_cycle(cfg, gw)
    assert r["action"] == "short" and [list(e)[0] for e in r["events"]] == ["closed", "opened"]
    assert fake.requests[1]["position"] == 101 and fake.requests[2]["type"] == fake.ORDER_TYPE_SELL
    assert fake.requests[2]["sl"] > fake.requests[2]["price"] > fake.requests[2]["tp"]


def test_detects_stop_hit_by_broker_and_ignores_foreign_positions(tmp_path):
    cfg, fake, gw = make(tmp_path, UP)
    run_cycle(cfg, gw)
    fake.positions = [NS(ticket=7, type=1, volume=1.0, magic=0)]   # user's own manual trade
    r = run_cycle(cfg, gw)
    assert r["events"] == [{"closed_by_broker": 101, "pnl": 12.0}]
    assert gw.position() is None and all(q.get("position") != 7 for q in fake.requests)


def test_refuses_live_account_and_unknown_symbol(tmp_path):
    with pytest.raises(MT5Error, match="not a demo"):
        make(tmp_path, UP, trade_mode=2)
    cfg = Config(symbol="GOLD.x")
    with pytest.raises(MT5Error, match="not found"):
        Gateway(cfg, FakeMT5(UP)).connect()


def test_terminal_path_and_login_are_passed_without_password(tmp_path):
    cfg = Config(terminal_path=r"C:\\MT5\\terminal64.exe", login=123, server="Demo-1")
    fake = FakeMT5(UP)
    Gateway(cfg, fake).connect()
    assert fake.init_call == ((r"C:\\MT5\\terminal64.exe",), {"login": 123, "server": "Demo-1"})
    Gateway(Config(), fake).connect()
    assert fake.init_call == ((), {})


def test_rejected_order_is_reported_not_crashed(tmp_path):
    cfg, fake, gw = make(tmp_path, UP)
    fake.reject = True
    r = run_cycle(cfg, gw)
    assert "failed" in r["action"] and "10027" in r["action"]
    assert json.loads(open(cfg.state_file).read())["ticket"] is None


def test_kill_switch_and_daily_limit_block_entries(tmp_path):
    cfg, fake, gw = make(tmp_path, list(3500 + np.sin(np.arange(650))))   # flat: no signal, sets the baseline
    day1 = datetime(2026, 11, 11, 9, tzinfo=timezone.utc)
    assert run_cycle(cfg, gw, day1)["action"] == "hold"
    fake.acct.equity, fake.closes = 9_600.0, UP           # -4% same day
    assert run_cycle(cfg, gw, day1)["action"] == "blocked: daily loss limit reached"
    fake.acct.equity, fake.closes = 8_400.0, UP + [4001]  # -16% from peak
    r = run_cycle(cfg, gw, datetime(2026, 11, 12, 9, tzinfo=timezone.utc))
    assert r["halted"] and r["action"].startswith("blocked: halted")
    assert fake.requests == []


def test_risk_guard_new_day_resets_baseline():
    s = {}
    g = RiskGuard(Config(), s)
    g.update(10_000, "d1"); g.update(9_650, "d1")
    assert not g.can_open(9_650)[0]
    g.update(9_650, "d2")
    assert g.can_open(9_650)[0]
