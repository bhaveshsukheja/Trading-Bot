import argparse
import json
import sys
import time

from .config import Config
from .mt5gw import DEMO_TRADE_MODE, Gateway, MT5Error


def main():
    ap = argparse.ArgumentParser(prog="goldbot", description="Gold trading bot for MetaTrader 5")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="test the connection; places no orders")
    sub.add_parser("symbols", help="list the broker's gold symbols")
    sub.add_parser("run", help="run one cycle")
    lp = sub.add_parser("loop", help="run cycles until stopped (Ctrl+C)")
    lp.add_argument("--every", type=int, default=300, help="seconds between cycles")
    sub.add_parser("backtest", help="backtest the technical signal on the broker's history")
    args = ap.parse_args()
    cfg = Config.load()
    try:
        if args.cmd == "symbols":
            gw = Gateway(cfg)
            gw.initialize()
            print("\n".join(gw.find_symbols()) or "no symbol containing XAU or GOLD")
        elif args.cmd == "check":
            gw = Gateway(cfg).connect(require_tradable=False)
            a, info, t = gw.account(), gw.symbol_info(), gw.tick()
            term = gw.m.terminal_info()
            bars = gw.bars(cfg.symbol, cfg.timeframe, cfg.bars)
            print(json.dumps({
                "server": a.server, "login": a.login,
                "account_type": "demo" if a.trade_mode == DEMO_TRADE_MODE else "NOT DEMO",
                "currency": a.currency, "balance": a.balance, "equity": a.equity,
                "algo_trading_enabled_in_terminal": getattr(term, "trade_allowed", "unknown"),
                "symbol": cfg.symbol, "bid": t.bid, "ask": t.ask,
                "contract_size": info.trade_contract_size, "min_lot": info.volume_min,
                "lot_step": info.volume_step, "profit_currency": info.currency_profit,
                "completed_bars": len(bars), "last_bar": str(bars.index[-1]),
                "last_close": float(bars["close"].iloc[-1])}, indent=1))
        elif args.cmd == "backtest":
            from .backtest import run_backtest
            gw = Gateway(cfg).connect(require_tradable=False)
            res = run_backtest(gw.bars(cfg.symbol, cfg.timeframe, cfg.backtest_bars), cfg)
            res.pop("equity_curve"), res.pop("trade_log")
            print(json.dumps(res, indent=1))
        else:
            from .bot import run_cycle
            gw = Gateway(cfg).connect()
            if args.cmd == "run":
                print(json.dumps(run_cycle(cfg, gw), indent=1, default=str))
            else:
                while True:
                    try:
                        r = run_cycle(cfg, gw)
                        print(r["time"], r["close"], r["action"], "equity", r["equity"],
                              *r["events"], flush=True)
                    except MT5Error as e:   # e.g. terminal closed: reconnect next time
                        print("cycle failed:", e, flush=True)
                        try:
                            gw.connect()
                        except MT5Error:
                            pass
                    time.sleep(args.every)
    except MT5Error as e:
        sys.exit(f"error: {e}")
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    main()
