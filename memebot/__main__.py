"""Entry point: `python -m memebot run` / `python -m memebot status`."""
import argparse
import logging
import os
import time
import tomllib

from . import db, strategy, ta, wallets
from .http import HttpError
from .portfolio import Portfolio
from .sources import dexscreener, geckoterminal, rugcheck, x

log = logging.getLogger("memebot")


def load_config(path):
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    if cfg["general"]["mode"] != "paper":
        raise SystemExit("Only mode = \"paper\" is implemented; this bot cannot place real orders.")
    return cfg


def attempt(what, fn, *args):
    """Run a data fetch; log and return None on failure so one bad API call
    never stops the cycle."""
    try:
        return fn(*args)
    except (HttpError, KeyError, ValueError, TypeError) as e:
        log.warning("%s failed: %s", what, e)
        return None


def manage_positions(con, cfg, pf):
    positions = pf.open_positions()
    if not positions:
        return
    pairs = attempt("position prices", dexscreener.pairs_for_tokens,
                    cfg["general"]["chain"], [p["token"] for p in positions])
    if pairs is None:
        return
    for pos in positions:
        pair = pairs.get(pos["token"])
        if not pair or not pair.get("priceUsd"):
            # No price means we cannot tell what the position is worth. Keep the
            # last known price and say so rather than inventing an exit.
            log.warning("no price for open position %s; leaving it unchanged", pos["symbol"])
            continue
        pf.manage(pos, float(pair["priceUsd"]), strategy._num(pair, "liquidity", "usd"))


def scan(con, cfg, pf):
    g, f, s, w = cfg["general"], cfg["filters"], cfg["strategy"], cfg["wallets"]
    chain = g["chain"]

    found = attempt("dexscreener discovery", dexscreener.discover, chain) or {}
    for addr in attempt("geckoterminal trending", geckoterminal.trending_tokens, chain) or []:
        found.setdefault(addr, 0)
    pairs = attempt("pair data", dexscreener.pairs_for_tokens, chain, found) or {}

    held = {p["token"] for p in pf.open_positions()}
    shortlist = []
    for addr, pair in pairs.items():
        # Tokens already held are managed by the exit rules, not re-scored.
        if addr not in held and strategy.basic_reject(pair, f) is None:
            quick = strategy.momentum(pair) + strategy.flow(pair, None)
            shortlist.append((quick, addr, pair))
    shortlist.sort(key=lambda c: c[0], reverse=True)
    log.info("discovered %d tokens, %d with pair data, %d passed basic filters",
             len(found), len(pairs), len(shortlist))

    followed = wallets.smart_wallets(con, w["smart_min_realized_pnl_usd"],
                                     w["smart_min_winning_tokens"]) | set(w["watchlist"])
    x_on = cfg["x"]["enabled"] and bool(x.token())
    x_left = cfg["x"]["max_lookups_per_cycle"]

    for _, addr, pair in shortlist[:g["max_deep_candidates"]]:
        # Deep analysis is slow (GeckoTerminal rate limits), so re-check exits
        # before every candidate instead of once per cycle.
        manage_positions(con, cfg, pf)
        symbol = pair["baseToken"]["symbol"]
        pool = pair["pairAddress"]
        trades = attempt(f"{symbol} trades", geckoterminal.trades, chain, pool)
        stats = None
        if trades:
            wallets.record(con, addr, trades, w["bot_max_trades_per_window"])
            stats = wallets.trade_stats(trades, followed)
        rug = attempt(f"{symbol} rugcheck", db.cached, con, f"rug:{addr}", 3600,
                      lambda: rugcheck.summary(addr))
        reason = strategy.deep_reject(rug, stats, f)
        if reason:
            log.info("skip %-10s %s", symbol, reason)
            continue

        candles = attempt(f"{symbol} candles", geckoterminal.candles, chain, pool)
        components = {
            "momentum": strategy.momentum(pair),
            "flow": strategy.flow(pair, stats),
            "ta": strategy.technicals(ta.analyze(candles) if candles else None),
            "wallets": strategy.wallet_signal(stats),
            "social": None,
        }
        total = strategy.score(components, s)
        # X quota is scarce: only look up tokens that are already close to an entry.
        if x_on and x_left > 0 and total >= s["entry_score"] - 15:
            x_left -= 1
            xr = attempt(f"{symbol} X research", db.cached, con, f"x:{addr}",
                         cfg["x"]["cache_minutes"] * 60, lambda: x.research(addr, symbol))
            components["social"] = strategy.social(xr)
            total = strategy.score(components, s)

        parts = " ".join(f"{k}={v:.2f}" for k, v in components.items() if v is not None)
        log.info("score %-10s %5.1f  %s", symbol, total, parts)
        if total < s["entry_score"]:
            continue
        blocked = pf.can_open(addr)
        if blocked:
            log.info("no entry for %s: %s", symbol, blocked)
            continue
        pf.buy(addr, symbol, pool, float(pair["priceUsd"]),
               strategy._num(pair, "liquidity", "usd"), total)


def cycle(con, cfg, pf):
    manage_positions(con, cfg, pf)
    scan(con, cfg, pf)
    log.info("equity $%.2f | cash $%.2f | open positions %d",
             pf.equity(), pf.cash, len(pf.open_positions()))


def run(cfg, once):
    con = db.connect(cfg["general"]["db_path"])
    pf = Portfolio(con, cfg)
    if cfg["x"]["enabled"] and not x.token():
        log.info("X research disabled: X_BEARER_TOKEN is not set")
    while True:
        started = time.time()
        try:
            cycle(con, cfg, pf)
        except Exception:
            log.exception("cycle failed")
        if once:
            return
        time.sleep(max(5, cfg["general"]["cycle_seconds"] - (time.time() - started)))


def status(cfg):
    con = db.connect(cfg["general"]["db_path"])
    pf = Portfolio(con, cfg)
    start = cfg["risk"]["starting_cash_usd"]
    equity = pf.equity()
    print(f"PAPER TRADING (simulated)  equity ${equity:,.2f}  cash ${pf.cash:,.2f}  "
          f"P&L {equity - start:+,.2f} ({equity / start - 1:+.1%})")
    print("\nOpen positions:")
    for p in pf.open_positions():
        value = p["tokens"] * p["last_price"]
        print(f"  {p['symbol']:<10} value ${value:8.2f}  entry {p['entry_price']:.8g}  "
              f"last {p['last_price']:.8g}  {p['last_price'] / p['entry_price'] - 1:+.1%}")
    closed = con.execute("SELECT * FROM positions WHERE status='closed' ORDER BY exit_ts").fetchall()
    wins = sum(p["proceeds_usd"] > p["cost_usd"] for p in closed)
    print(f"\nClosed positions: {len(closed)} ({wins} profitable)")
    for p in closed[-15:]:
        print(f"  {p['symbol']:<10} {p['proceeds_usd'] - p['cost_usd']:+8.2f} USD  {p['exit_reason']}")
    n = con.execute("SELECT COUNT(DISTINCT wallet) AS n FROM wallet_trades").fetchone()["n"]
    smart = wallets.smart_wallets(con, cfg["wallets"]["smart_min_realized_pnl_usd"],
                                  cfg["wallets"]["smart_min_winning_tokens"])
    print(f"\nWallets observed: {n}  |  currently rated smart: {len(smart)}")
    for wlt in sorted(smart)[:20]:
        print(f"  {wlt}")


def main():
    ap = argparse.ArgumentParser(prog="memebot")
    ap.add_argument("command", choices=["run", "status"])
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--once", action="store_true", help="run a single cycle and exit")
    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.command == "status":
        return status(cfg)
    os.makedirs(os.path.dirname(cfg["general"]["log_path"]) or ".", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(cfg["general"]["log_path"])])
    run(cfg, args.once)


if __name__ == "__main__":
    main()
