import numpy as np
import pandas as pd

from goldbot.backtest import run_backtest
from goldbot.broker import PaperBroker
from goldbot.config import Config
from goldbot.strategy import blend, decide, technical_frame


def cfg(tmp_path):
    return Config(stop_atr=2.0, target_atr=3.0, entry_threshold=0.35, state_file=str(tmp_path / "a.json"), journal_file=str(tmp_path / "j.jsonl"))


def bars(closes):
    c = pd.Series(closes, index=pd.date_range("2025-01-01", periods=len(closes), freq="h", tz="UTC"))
    return pd.DataFrame({"open": c.shift().fillna(c.iloc[0]), "high": c + 1, "low": c - 1,
                         "close": c, "volume": 1})


def test_sizing_risks_one_percent(tmp_path):
    bk = PaperBroker(cfg(tmp_path))
    p = bk.open(1, 2000.0, atr=10.0, time="t")
    assert abs((p["entry"] - p["stop"]) * p["oz"] - 100) < 0.5      # 1% of 10k
    t = bk.close(p["stop"] + 0.4, "t2", "x")                         # fill exactly at stop
    assert abs(t["pnl"] + 100) < 0.5


def test_leverage_cap(tmp_path):
    bk = PaperBroker(cfg(tmp_path))
    p = bk.open(1, 2000.0, atr=0.01, time="t")
    assert p["oz"] * p["entry"] <= 5 * 10_000 + 1


def test_stop_beats_target_in_same_bar_and_short_side(tmp_path):
    bk = PaperBroker(cfg(tmp_path))
    bk.open(1, 2000.0, 10.0, "t")
    assert bk.check_exits(2000, 2100, 1900, "t")["reason"] == "stop"
    bk.open(-1, 2000.0, 10.0, "t")
    assert bk.check_exits(2000, 2005, 1960, "t")["reason"] == "target"
    assert bk.s["trades"][-1]["pnl"] > 0
    bk.open(-1, 2000.0, 10.0, "t")
    assert bk.check_exits(2050, 2060, 2040, "t")["reason"] == "stop (gap)"


def test_kill_switch_and_daily_limit(tmp_path):
    c = cfg(tmp_path)
    bk = PaperBroker(c)
    assert bk.can_open("d1")[0]
    bk.s["equity"] = 9_600
    assert not bk.can_open("d1")[0]          # -4% on the day
    assert bk.can_open("d2")[0]              # new day
    bk.open(1, 2000.0, 10.0, "t")
    bk.s["position"]["oz"] = 10
    bk.close(1800.0, "t", "x")               # huge loss -> drawdown > 15%
    assert bk.s["halted"] and not bk.can_open("d3")[0]


def test_persistence_roundtrip(tmp_path):
    c = cfg(tmp_path)
    bk = PaperBroker(c)
    bk.open(-1, 2000.0, 10.0, "t")
    bk.save()
    assert PaperBroker.load(c).s == bk.s


def test_decide_and_blend(tmp_path):
    c = cfg(tmp_path)
    assert decide(0.4, 0, c) == "long" and decide(-0.4, 0, c) == "short"
    assert decide(0.2, 0, c) == "hold" and decide(-0.05, 1, c) == "hold"
    assert decide(-0.2, 1, c) == "close" and decide(-0.5, 1, c) == "short"
    assert decide(0.2, -1, c) == "close"
    c.allow_short = False
    assert decide(-0.5, 0, c) == "hold" and decide(-0.5, 1, c) == "close"
    assert abs(blend({"technical": 1.0, "macro": -1.0}, c.weights) - 0.6) < 1e-9
    assert abs(blend({"technical": 0.7, "macro": None}, c.weights) - 0.7) < 1e-9


def test_technical_score_follows_trend_without_lookahead(tmp_path):
    c = cfg(tmp_path)
    up = bars(np.linspace(2000, 2600, 600))
    assert technical_frame(up, c)["score"].iloc[-1] > 0.5
    assert technical_frame(bars(np.linspace(2600, 2000, 600)), c)["score"].iloc[-1] < -0.5
    full, part = technical_frame(up, c), technical_frame(up.iloc[:400], c)
    assert np.allclose(full.loc[part.index], part)


def test_backtest_profits_in_clean_uptrend_and_runs_on_noise(tmp_path):
    c = cfg(tmp_path)
    r = run_backtest(bars(np.linspace(2000, 3000, 1500)), c)
    assert r["return_pct"] > 0 and r["trades"] >= 1
    rng = np.random.default_rng(0)
    r = run_backtest(bars(2000 + rng.normal(0, 3, 1500).cumsum()), c)
    assert np.isfinite(r["return_pct"])
