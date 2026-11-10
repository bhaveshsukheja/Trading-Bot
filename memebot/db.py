"""SQLite state: paper portfolio, observed wallet trades, API caches."""
import json
import os
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, ts REAL, value TEXT);
CREATE TABLE IF NOT EXISTS wallet_trades (
    id TEXT PRIMARY KEY, token TEXT, wallet TEXT, kind TEXT, tokens REAL, usd REAL, ts TEXT);
CREATE INDEX IF NOT EXISTS wallet_trades_wallet ON wallet_trades (wallet, token);
CREATE TABLE IF NOT EXISTS bot_wallets (wallet TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT, symbol TEXT, pair TEXT,
    entry_ts REAL, entry_price REAL, tokens REAL, cost_usd REAL, proceeds_usd REAL DEFAULT 0,
    last_price REAL, peak_price REAL, entry_liquidity REAL, tp_done INTEGER DEFAULT 0,
    status TEXT DEFAULT 'open', exit_ts REAL, exit_reason TEXT, score REAL);
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, token TEXT, symbol TEXT, side TEXT,
    tokens REAL, price REAL, usd REAL, reason TEXT);
"""


def connect(path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def kv_get(con, key, default=None):
    row = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def kv_set(con, key, value):
    con.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (key, json.dumps(value)))
    con.commit()


def cached(con, key, max_age_seconds, fetch):
    """Return a cached value, or call fetch() and store its result."""
    row = con.execute("SELECT ts, value FROM cache WHERE key=?", (key,)).fetchone()
    if row and time.time() - row["ts"] < max_age_seconds:
        return json.loads(row["value"])
    value = fetch()
    con.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)", (key, time.time(), json.dumps(value)))
    con.commit()
    return value
