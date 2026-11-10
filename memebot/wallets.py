"""Wallet tracking.

The bot records every trade it sees in the pools it analyses, works out which
wallets have actually realised profits across those trades, and treats those
(plus the configured watchlist) as "smart" wallets. It only knows about trades
it has observed, so the list starts empty and improves the longer the bot runs.
"""
from collections import Counter, defaultdict


def record(con, token, trades, bot_max_trades):
    con.executemany(
        "INSERT OR IGNORE INTO wallet_trades VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(t["id"], token, t["wallet"], t["kind"], t["tokens"], t["usd"], t["ts"]) for t in trades],
    )
    # Wallets hammering one pool are market makers / arbitrage / sniper bots, not signal.
    counts = Counter(t["wallet"] for t in trades)
    con.executemany(
        "INSERT OR IGNORE INTO bot_wallets VALUES (?)",
        [(w,) for w, n in counts.items() if n > bot_max_trades],
    )
    con.commit()


def smart_wallets(con, min_pnl_usd, min_winning_tokens):
    """Wallets with realised profit across the trades observed so far."""
    rows = con.execute("""
        SELECT wallet, token,
               SUM(CASE WHEN kind='buy'  THEN tokens ELSE 0 END) AS bought,
               SUM(CASE WHEN kind='buy'  THEN usd    ELSE 0 END) AS bought_usd,
               SUM(CASE WHEN kind='sell' THEN tokens ELSE 0 END) AS sold,
               SUM(CASE WHEN kind='sell' THEN usd    ELSE 0 END) AS sold_usd
        FROM wallet_trades
        WHERE wallet NOT IN (SELECT wallet FROM bot_wallets)
        GROUP BY wallet, token
        HAVING bought > 0 AND sold > 0
    """).fetchall()
    pnl, wins = defaultdict(float), defaultdict(int)
    for r in rows:
        # Only count the cost of the tokens that were actually sold again.
        cost = r["bought_usd"] * min(1.0, r["sold"] / r["bought"])
        profit = r["sold_usd"] - cost
        pnl[r["wallet"]] += profit
        wins[r["wallet"]] += profit > 0
    return {w for w in pnl if pnl[w] >= min_pnl_usd and wins[w] >= min_winning_tokens}


def trade_stats(trades, followed):
    """Order-flow summary of a pool's recent trades.

    `followed` is the set of smart + watchlist wallets.
    """
    buy_usd = sell_usd = 0.0
    buyers, sellers = set(), set()
    volume, net_tokens = defaultdict(float), defaultdict(float)
    for t in trades:
        volume[t["wallet"]] += t["usd"]
        if t["kind"] == "buy":
            buy_usd += t["usd"]
            buyers.add(t["wallet"])
            net_tokens[t["wallet"]] += t["tokens"]
        else:
            sell_usd += t["usd"]
            sellers.add(t["wallet"])
            net_tokens[t["wallet"]] -= t["tokens"]
    total = buy_usd + sell_usd
    return {
        "trades": len(trades),
        "buyers": len(buyers),
        "sellers": len(sellers),
        "net_flow": (buy_usd - sell_usd) / total if total else 0.0,
        "top_trader_share": max(volume.values()) / total if total else 0.0,
        "followed_buyers": sorted(w for w in followed if net_tokens.get(w, 0) > 0),
        "followed_sellers": sorted(w for w in followed if net_tokens.get(w, 0) < 0),
    }
