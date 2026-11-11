import json
import os
from dataclasses import dataclass, field, fields


@dataclass
class Config:
    # --- broker / MetaTrader 5 ---
    symbol: str = "XAUUSD"          # brokers often add a suffix; run `python -m goldbot symbols`
    timeframe: str = "H1"           # MetaTrader timeframe name: M15, M30, H1, H4, D1
    bars: int = 600                 # completed bars pulled each cycle (needs > ema_slow)
    backtest_bars: int = 12000
    dollar_symbol: str = ""         # optional: broker's US dollar index symbol; "" = off
    terminal_path: str = ""         # full path to terminal64.exe; "" = let the package find it
    login: int = 0                  # account number; 0 = whichever account the terminal last used
    server: str = ""                # trade server name as shown in the terminal; "" = saved one
    magic: int = 20261111           # tags this bot's orders so it never touches yours
    deviation_points: int = 30      # max slippage accepted on market orders
    allow_live_account: bool = False  # safety: refuse to trade unless the account is a demo
    # --- signal ---
    weights: dict = field(default_factory=lambda: {"technical": 0.8, "macro": 0.2})
    entry_threshold: float = 0.50   # |score| needed to open a position
    exit_threshold: float = 0.10    # score this far against a position closes it
    allow_short: bool = True
    ema_fast: int = 50
    ema_slow: int = 200
    # NOTE: entry_threshold / stop_atr / target_atr were picked AFTER seeing the backtest
    # grid in the README (in-sample), so their backtest result is not evidence of an edge.
    # --- risk ---
    starting_equity: float = 10_000.0   # backtest only; live uses the account's equity
    risk_per_trade: float = 0.01    # fraction of equity lost if the stop is hit
    stop_atr: float = 3.0
    target_atr: float = 6.0
    max_leverage: float = 5.0       # cap on notional / equity
    daily_loss_limit: float = 0.03  # no new entries after losing this much in a UTC day
    max_drawdown: float = 0.15      # kill switch: halt until manually reset
    cost_per_oz: float = 0.40       # backtest only: assumed spread + slippage per side
    # --- files ---
    state_file: str = "state/account.json"
    journal_file: str = "state/journal.jsonl"

    @classmethod
    def load(cls, path: str = "settings.json") -> "Config":
        """Defaults, overridden by any keys present in settings.json."""
        if not os.path.exists(path):
            return cls()
        with open(path) as f:
            over = json.load(f)
        unknown = set(over) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"unknown keys in {path}: {sorted(unknown)}")
        return cls(**over)
