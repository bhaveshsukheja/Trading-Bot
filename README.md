# Trading-Bot — gold bot for MetaTrader 5

An automated bot that reads gold prices from a MetaTrader 5 (MT5) terminal, scores the
market, and places trades through that terminal with a stop-loss and take-profit on
every order. It is built to run on a **demo account** and refuses to trade on a real one
unless you change a setting.

> **No strategy "always makes a profit".** This one has no demonstrated edge (see the
> backtest section). It is a research tool, not financial advice. Do not put real money
> behind it on the strength of this repo.

> **Untested against a real terminal.** The MT5 connection was written from MetaQuotes'
> official Python reference and tested only against a stand-in, because the `MetaTrader5`
> package runs on Windows only. Expect to fix something on the first real run.

## What each cycle does

1. **Tracks price** — pulls the last 600 completed hourly gold bars from the terminal.
2. **Analyses** — a technical score from EMA 50/200 trend, MACD and RSI. Optionally blended
   (80/20) with the 10-day change in a US dollar index symbol, if your broker has one and
   you set `dollar_symbol`.
3. **Executes** — opens long/short when |score| ≥ 0.50 with a stop at 3×ATR and a target at
   6×ATR attached to the order, so the broker enforces them even if the bot is off. Closes
   when the score turns against the position.
4. **Records** — every decision in `state/journal.jsonl`.

Risk limits: at most 1% of equity lost if the stop is hit (lot size is rounded *down*; if
the broker's minimum lot would risk more, the trade is skipped), notional capped at 5×
equity, no new entries after a 3% loss in a day, and a kill switch that blocks new entries
at a 15% drawdown from the equity peak. The bot only ever touches positions it opened
itself (matched by its magic number).

There is no news or TradingView input: both TradingView's and Yahoo's terms prohibit
automated collection (checked 2026-11-10), so those parts of the first version were removed.

## Setup on Windows

1. Install the MT5 terminal from your broker, log in to a **demo** account, and leave it running.
2. In the terminal, enable algorithmic trading (the "Algo Trading" toolbar button; also
   under Tools → Options → Expert Advisors). Menu names may differ by terminal version.
3. Install 64-bit Python 3.10 or newer, then in this folder:

```bash
pip install -r requirements.txt
```

4. Find your broker's gold symbol (brokers often add a suffix to `XAUUSD`):

```bash
python -m goldbot symbols
```

5. If it is not exactly `XAUUSD`, copy `settings.example.json` to `settings.json` and put
   the name there. Any field of `goldbot/config.py` can be overridden in that file.
6. Test the connection. This places no orders:

```bash
python -m goldbot check
```

7. Run one cycle, then leave it running (or double-click `start_bot.bat`):

```bash
python -m goldbot run
```

```bash
python -m goldbot loop
```

The bot only works while the PC is on, the terminal is open and logged in, and the loop
is running. Stops and targets already placed stay active at the broker regardless.

Other commands: `python -m goldbot backtest` (uses the broker's own history) and
`python -m pytest` (needs `pip install pytest`).

To resume after the kill switch, set `"halted": false` in `state/account.json`.

## Backtest: what it does and does not show

These numbers are from 2026-11-10 on hourly COMEX gold futures from Yahoo (before that
source was removed), 2024-07-02 to 2026-11-10, $10,000 start, $0.40/oz cost per side,
technical signal only. **Rerun `python -m goldbot backtest` on your broker's data** — spot
gold, the broker's spread and its trading hours will give different results.
Buy-and-hold over the same period: **+72.8%**.

| shorts | stop×ATR | target×ATR | threshold | return | max DD | trades | kill switch hit |
|---|---|---|---|---|---|---|---|
| yes | 2 | 3 | 0.35 | −10.7% | −15.4% | 285 | yes |
| yes | 2 | 3 | 0.50 | −8.7% | −15.9% | 219 | yes |
| yes | 2 | 6 | 0.35 | +11.0% | −17.4% | 134 | yes |
| yes | 2 | 6 | 0.50 | +8.7% | −17.1% | 111 | yes |
| yes | 3 | 3 | 0.35 | +18.4% | −14.8% | 508 | no |
| yes | 3 | 3 | 0.50 | +31.2% | −11.2% | 427 | no |
| yes | 3 | 6 | 0.35 | +2.0% | −16.7% | 121 | yes |
| **yes** | **3** | **6** | **0.50** | **+71.8%** | **−14.0%** | **224** | **no** |
| no | 2 | 3 | 0.35 | −5.5% | −15.8% | 235 | yes |
| no | 2 | 3 | 0.50 | −5.4% | −16.0% | 177 | yes |
| no | 2 | 6 | 0.35 | +63.7% | −17.4% | 193 | yes |
| no | 2 | 6 | 0.50 | +13.8% | −17.0% | 90 | yes |
| no | 3 | 3 | 0.35 | +25.7% | −12.8% | 335 | no |
| no | 3 | 3 | 0.50 | +29.4% | −14.4% | 286 | no |
| no | 3 | 6 | 0.35 | +51.1% | −13.6% | 174 | no |
| no | 3 | 6 | 0.50 | +61.1% | −14.0% | 143 | no |

- The first row was the original design, chosen before any testing. **It lost money.**
- The bold row is the current default. It was picked *after* seeing this table, so its
  +71.8% is an in-sample, best-of-16 number — expect worse going forward.
- Results swing from −11% to +72% on small setting changes, half the settings hit the
  kill switch, and **none beat simply holding gold**. That is what a strategy without a
  reliable edge looks like.

## Known limitations

- Never run against a real MT5 terminal (see top). Things most likely to need adjusting:
  the order filling mode, the symbol name, and how the terminal reports closed trades.
- Position sizing assumes a USD account and a USD-quoted gold symbol; the bot refuses to
  trade otherwise.
- Swap (overnight financing) and commission are not modelled in the backtest.
- The live blend with a dollar index, if enabled, is not what the backtest tests.
- Check your broker's client agreement for your region before automating, and whether
  leveraged gold trading with that broker is permitted where you live.
