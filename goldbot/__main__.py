import argparse
import json
import sys
import time

from .config import Config
from .data import DataError, fetch_bars, split_completed


def main():
    ap = argparse.ArgumentParser(prog="goldbot", description="Gold paper-trading bot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="run one cycle")
    lp = sub.add_parser("loop", help="run cycles forever")
    lp.add_argument("--every", type=int, default=600, help="seconds between cycles")
    bt = sub.add_parser("backtest", help="backtest the technical component")
    bt.add_argument("--range", default="730d", help="Yahoo range string, e.g. 730d")
    sub.add_parser("status", help="show the paper account")
    args = ap.parse_args()
    cfg = Config()

    if args.cmd == "run":
        from .bot import run_cycle
        try:
            print(json.dumps(run_cycle(cfg), indent=1, default=str))
        except DataError as e:
            sys.exit(f"cycle aborted, nothing traded: {e}")
    elif args.cmd == "loop":
        from .bot import run_cycle
        while True:
            try:
                r = run_cycle(cfg)
                print(r["time"], r["price"], r["action"], "equity", r["marked_equity"], flush=True)
            except Exception as e:  # keep the loop alive; the next cycle retries
                print("cycle failed:", repr(e), flush=True)
            time.sleep(args.every)
    elif args.cmd == "backtest":
        from .backtest import run_backtest
        df, _ = split_completed(fetch_bars(cfg.symbol, cfg.interval, args.range), cfg.interval)
        res = run_backtest(df, cfg)
        res.pop("equity_curve"), res.pop("trade_log")
        print(json.dumps(res, indent=1))
    elif args.cmd == "status":
        from .broker import PaperBroker
        s = PaperBroker.load(cfg).s
        print(json.dumps({**{k: v for k, v in s.items() if k != "trades"},
                          "closed_trades": len(s["trades"]),
                          "realised_pnl": round(sum(t["pnl"] for t in s["trades"]), 2)}, indent=1))


if __name__ == "__main__":
    main()
