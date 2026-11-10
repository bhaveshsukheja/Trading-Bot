# Trading-Bot

An automated **paper-trading** bot for Solana memecoins. It scans the market in a
loop, scores tokens, and opens and closes simulated positions with strict risk
limits. **It never sends a real order and never touches a wallet or private key.**

## Read this first

- **No bot can always make a profit.** Most memecoins go to zero, and most
  memecoin traders lose money. This bot is a disciplined way to test a strategy,
  not a money machine.
- The scoring weights and thresholds in `config.toml` are **untested heuristics**.
  They have not been backtested. Expect to tune or discard them.
- Paper results are optimistic. Real trading adds failed transactions, MEV
  sandwiching, and tokens whose liquidity is pulled before you can sell (in a
  real rug you get nothing, while the simulation still books a sale).
- Open positions are re-checked roughly every 10–60 seconds, depending on API
  rate limits. A memecoin can fall much further than the stop-loss level between
  checks.

## What it does each cycle

1. **Manages open positions** – fresh price from DexScreener, then stop loss,
   partial take profit, trailing stop, max hold time, liquidity-collapse exit.
2. **Discovers tokens** – DexScreener boosted / newly profiled tokens plus
   GeckoTerminal trending pools.
3. **Hard filters** – liquidity, 24h volume, market cap, pool age.
4. **Deep analysis** of the best few candidates:
   - **Safety** – RugCheck risk report; any "danger" risk is an automatic skip.
   - **Order flow** – last 300 trades: buy/sell pressure, unique buyers vs
     sellers, and a wash-trading check (one wallet dominating volume).
   - **Technical analysis** – EMA 9/21, RSI 14, VWAP and volume spike on
     5-minute candles.
   - **Wallet tracking** – see below.
   - **X research** – recent posts, unique authors and keyword sentiment
     (optional, needs an API token).
5. **Scores 0–100** and paper-buys anything at or above `entry_score`, subject to
   position size, max positions, daily loss limit and re-entry cooldown.

## Data sources and their limits

| Source | Used for | Notes |
| --- | --- | --- |
| DexScreener API | discovery, prices, liquidity, volume | free, no key |
| GeckoTerminal API | candles, trades, trending | free, no key; rate-limits hard (HTTP 429), which is why only 5 tokens get deep analysis per cycle |
| RugCheck API | token safety | free, no key; Solana only |
| X API v2 | social research | needs `X_BEARER_TOKEN`. **This code path has never been run against the live API** – verify it against the current X API docs and your access tier |
| TradingView | – | **Not used.** As far as we know TradingView offers no official public API for reading chart data (verify on their site; scraping it may breach their terms). The bot computes the same indicators itself from candles |

**Wallet tracking:** the bot records every trade it sees in pools it analyses and
rates a wallet "smart" once it has realised at least `smart_min_realized_pnl_usd`
profit across `smart_min_winning_tokens` tokens. This list starts empty and only
knows trades the bot has observed, so it takes time to become useful. You can add
wallets you already trust to `[wallets] watchlist` in `config.toml`. High-frequency
wallets are treated as bots and ignored.

## Running it

Requires Python 3.11+.

```bash
pip install -r requirements.txt
```

```bash
python -m memebot run
```

```bash
python -m memebot status
```

`python -m memebot run --once` runs a single cycle. State lives in
`data/bot.sqlite` and the log in `data/bot.log` (both git-ignored).

To enable X research, set the token before starting:

```bash
export X_BEARER_TOKEN=...
```

To keep it running unattended, run it on an always-on machine (a small VPS is
enough) under a process supervisor such as systemd, Docker with a restart
policy, or `tmux`. The bot survives restarts because all state is in SQLite.

## Tests

```bash
python -m unittest discover -s tests
```

## Going live

Not implemented, deliberately. Before considering real money: run paper mode for
weeks, check that it is profitable **after** simulated costs across a meaningful
number of trades, and understand why. Live execution would also need a swap
integration, a dedicated wallet holding only money you can afford to lose, and
handling for failed and front-run transactions.

Nothing here is financial advice.
