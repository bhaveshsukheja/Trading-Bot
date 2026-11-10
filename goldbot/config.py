from dataclasses import dataclass, field


@dataclass
class Config:
    # --- market data (Yahoo Finance chart endpoint, unofficial) ---
    symbol: str = "GC=F"            # COMEX gold futures, front contract
    interval: str = "1h"
    history_range: str = "60d"      # history pulled each live cycle
    dollar_symbol: str = "DX-Y.NYB"  # US dollar index
    yield_symbol: str = "^TNX"      # US 10-year yield
    # --- TradingView (unofficial scanner endpoint) ---
    tv_ticker: str = "OANDA:XAUUSD"
    tv_market: str = "cfd"
    # --- signal blending: weights are renormalised over sources that responded ---
    weights: dict = field(default_factory=lambda: {
        "technical": 0.45, "tradingview": 0.30, "macro": 0.15, "news": 0.10})
    entry_threshold: float = 0.50   # |score| needed to open a position
    exit_threshold: float = 0.10    # score this far against a position closes it
    allow_short: bool = True
    ema_fast: int = 50
    ema_slow: int = 200
    # NOTE: entry_threshold / stop_atr / target_atr were picked AFTER seeing the backtest
    # grid in the README (in-sample), so their backtest result is not evidence of an edge.
    # --- risk ---
    starting_equity: float = 10_000.0
    risk_per_trade: float = 0.01    # fraction of equity lost if the stop is hit
    stop_atr: float = 3.0
    target_atr: float = 6.0
    max_leverage: float = 5.0       # cap on notional / equity
    daily_loss_limit: float = 0.03  # no new entries after losing this much in a UTC day
    max_drawdown: float = 0.15      # kill switch: halt until manually reset
    cost_per_oz: float = 0.40       # assumed spread + slippage per side, USD/oz
    # --- files ---
    state_file: str = "state/account.json"
    journal_file: str = "state/journal.jsonl"
