import time
import tomllib
import unittest

from memebot import db, strategy, ta, wallets
from memebot.portfolio import Portfolio

with open("config.toml", "rb") as f:
    CFG = tomllib.load(f)


def portfolio():
    return Portfolio(db.connect(":memory:"), CFG)


class TechnicalsTest(unittest.TestCase):
    def test_rsi_extremes(self):
        self.assertEqual(ta.rsi([float(i) for i in range(1, 40)]), 100.0)
        self.assertAlmostEqual(ta.rsi([float(i) for i in range(40, 1, -1)]), 0.0)

    def test_uptrend_is_bullish(self):
        candles = [(i, p, p, p, p, 100.0) for i, p in enumerate(1 + 0.01 * n for n in range(60))]
        a = ta.analyze(candles)
        self.assertTrue(a["ema_bullish"] and a["above_vwap"] and a["ema21_rising"])

    def test_too_few_candles(self):
        self.assertIsNone(ta.analyze([(0, 1, 1, 1, 1, 1)] * 10))


class WalletTest(unittest.TestCase):
    def trade(self, i, wallet, kind, tokens, usd, token="T"):
        return {"id": f"{token}{i}", "ts": "", "wallet": wallet, "kind": kind, "tokens": tokens, "usd": usd}

    def test_smart_wallet_needs_realised_profit_on_several_tokens(self):
        con = db.connect(":memory:")
        for token in ("A", "B"):
            wallets.record(con, token, [
                self.trade(1, "winner", "buy", 100, 1000, token),
                self.trade(2, "winner", "sell", 100, 1600, token),
                self.trade(3, "holder", "buy", 100, 1000, token),   # never sold: no realised profit
                self.trade(4, "loser", "buy", 100, 1000, token),
                self.trade(5, "loser", "sell", 100, 400, token),
            ], bot_max_trades=40)
        self.assertEqual(wallets.smart_wallets(con, 500, 2), {"winner"})

    def test_stats_flag_dominant_trader_and_followed_buyers(self):
        trades = [self.trade(1, "whale", "buy", 10, 900), self.trade(2, "other", "sell", 1, 100)]
        s = wallets.trade_stats(trades, {"whale"})
        self.assertAlmostEqual(s["top_trader_share"], 0.9)
        self.assertEqual(s["followed_buyers"], ["whale"])
        self.assertAlmostEqual(s["net_flow"], 0.8)


class StrategyTest(unittest.TestCase):
    def test_rejects_without_trade_data_or_on_danger(self):
        f = CFG["filters"]
        ok = {"score": 5, "danger": []}
        self.assertEqual(strategy.deep_reject(ok, None, f), "no trade data")
        self.assertIn("danger", strategy.deep_reject({"score": 5, "danger": ["Freeze"]}, None, f))
        self.assertIsNone(strategy.deep_reject(ok, {"top_trader_share": 0.1}, f))

    def test_missing_social_weight_is_redistributed(self):
        parts = {"momentum": 1.0, "flow": 1.0, "ta": 1.0, "wallets": 1.0, "social": None}
        self.assertAlmostEqual(strategy.score(parts, CFG["strategy"]), 100.0)


class PortfolioTest(unittest.TestCase):
    def test_round_trip_at_same_price_loses_the_costs(self):
        pf = portfolio()
        pf.buy("T", "TKN", "pool", 1.0, 1_000_000, 70)
        pf.sell(pf.open_positions()[0], 1.0, 1.0, 1_000_000, "test")
        self.assertLess(pf.cash, CFG["risk"]["starting_cash_usd"])
        self.assertGreater(pf.cash, CFG["risk"]["starting_cash_usd"] - 2)

    def test_stop_loss_closes_position(self):
        pf = portfolio()
        pf.buy("T", "TKN", "pool", 1.0, 1_000_000, 70)
        pf.manage(pf.open_positions()[0], 0.8, 1_000_000)
        self.assertEqual(pf.open_positions(), [])

    def test_take_profit_sells_part_then_trailing_stop_sells_rest(self):
        pf = portfolio()
        pf.buy("T", "TKN", "pool", 1.0, 1_000_000, 70)
        tokens = pf.open_positions()[0]["tokens"]
        pf.manage(pf.open_positions()[0], 1.5, 1_000_000)
        pos = pf.open_positions()[0]
        self.assertAlmostEqual(pos["tokens"], tokens * (1 - CFG["exits"]["take_profit_fraction"]))
        pf.manage(pos, 1.1, 1_000_000)   # >20% below the 1.5 peak
        self.assertEqual(pf.open_positions(), [])
        self.assertGreater(pf.cash, CFG["risk"]["starting_cash_usd"])

    def test_liquidity_collapse_forces_exit(self):
        pf = portfolio()
        pf.buy("T", "TKN", "pool", 1.0, 1_000_000, 70)
        pf.manage(pf.open_positions()[0], 1.0, 300_000)
        self.assertEqual(pf.open_positions(), [])

    def test_position_limit_and_cooldown(self):
        pf = portfolio()
        for i in range(CFG["risk"]["max_open_positions"]):
            pf.buy(f"T{i}", "TKN", "pool", 1.0, 1_000_000, 70)
        self.assertEqual(pf.can_open("NEW"), "max open positions")
        pf.sell(pf.open_positions()[0], 1.0, 1.0, 1_000_000, "test")
        self.assertEqual(pf.can_open("T0"), "re-entry cooldown")
        self.assertIsNone(pf.can_open("NEW"))


if __name__ == "__main__":
    unittest.main()
