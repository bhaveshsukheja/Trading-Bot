# Trading-Bot — gold paper-trading bot

An automated bot that researches the gold market, scores it, and trades a
**simulated (paper) account**. It sends no real orders and holds no real money.

> **No strategy "always makes a profit".** This one has no demonstrated edge
> (see the backtest section). It is a research and paper-trading tool, not
> financial advice. Do not put real money behind it on the strength of this repo.

> **Data-source problem — read before running unattended.** The price, macro and news
> data all come from Yahoo Finance, whose Terms of Service (checked 2026-11-10, "Last
> updated: 1 November 2026") prohibit collecting data "using any automated means ... for
> any purpose without our express, prior permission". The hourly schedule is therefore
> switched **off** until the bot is moved to a licensed data source (for example a
> broker's official API). TradingView was removed entirely for the same reason — see below.

## What each cycle does

1. **Tracks price** — hourly COMEX gold futures bars (`GC=F`) from Yahoo Finance.
2. **Researches context** — 10-day change in the dollar index and US 10-year yield
   (both count against gold when rising), plus a keyword tally on recent Yahoo Finance
   gold-market headlines.
3. **Analyses** — its own technical score (EMA 50/200 trend, MACD, RSI) blended with the
   above: technical 65%, macro 20%, news 15%. Sources that fail are dropped
   and the rest re-weighted; if prices fail, the cycle aborts without trading.
4. **Executes on paper** — opens long/short when |score| ≥ 0.50, stop at 3×ATR, target at
   6×ATR, closes when the score turns against the position.
5. **Records** — account in `state/account.json`, every decision and its inputs in
   `state/journal.jsonl`.

Risk limits: 1% of equity risked per trade, notional capped at 5× equity, no new entries
after a 3% loss in a UTC day, and a kill switch that halts trading at a 15% drawdown
(clear `"halted"` in `state/account.json` to resume). All settings live in `goldbot/config.py`.

## Running it

```bash
pip install -r requirements.txt
python -m goldbot run        # one cycle
python -m goldbot loop       # a cycle every 10 minutes, forever
python -m goldbot status     # paper account summary
python -m goldbot backtest   # ~2 years of hourly data
python -m pytest             # tests (needs pytest)
```

**Automatic running:** `.github/workflows/bot.yml` runs one cycle on GitHub Actions and
commits `state/` back to the repo. Its hourly schedule is **commented out** because of the
data-source problem above. GitHub only runs or lets you manually start a workflow once its
file is on the **default branch**; the workflow has never actually been run.

## Why TradingView is not used

The first version read TradingView's technical ratings from the undocumented endpoint its
website uses. TradingView's Terms of Use (section 3 and the licence restrictions, checked
2026-11-10) license its data for "display-only use", list "automated trading ...
algorithmic decision-making" as prohibited, and forbid using "automated means ... to
access, monitor, copy, collect, or extract any content, data, or market data ... including
by accessing or querying internal or undocumented endpoints" without written consent.
That is exactly what the bot was doing, so the module was deleted. The bot's own technical
score covers similar ground (moving averages and oscillators).

## Backtest: what it does and does not show

Only the **technical** component can be backtested — there is no free history for the
macro and news inputs, so the live blended signal is untested. Signals are
taken on a bar's close and filled at the next open with $0.40/oz cost per side; when a
bar touches both stop and target, the stop is assumed first.

Hourly `GC=F`, 2024-07-02 to 2026-11-10, $10,000 start. Buy-and-hold over the same
period: **+72.8%**.

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

How to read this:

- The first row was the original design, chosen before any testing. **It lost money.**
- The bold row is the current default. It was picked *after* seeing this table, so its
  +71.8% is an in-sample, best-of-16 number — expect worse going forward.
- Results swing from −11% to +72% on small setting changes, half the settings hit the
  kill switch, and **none beat simply holding gold** in a period when gold rose 73%.
  That is what a strategy without a reliable edge looks like.

## Known limitations

- Yahoo's chart endpoint is **unofficial** and its use here is against Yahoo's terms (see
  the top of this file). It can also break, rate-limit or block cloud IPs at any time, and
  its futures quotes are delayed.
- Signals use futures (`GC=F`), which trade several dollars away from spot gold.
- Between hourly runs, stops and targets are checked against completed bars, so paper fills
  are approximations of what a real broker would give.
- The news score is a crude keyword count. On 2026-11-10 only 2 usable headlines were
  less than 3 days old and it scored 0, so in practice it often contributes nothing.
- No live broker is implemented. Going live would mean writing a broker class with the same
  `open` / `close` / `check_exits` surface as `PaperBroker`, against a real brokerage API.
