# Trading Lab

Day trading with pretend money, for learning. Jarvis trades 10 stocks (5 NSE, 5 US) with
1,000 each in the stock's own currency, and the dashboard (**Trading Lab** in the sidebar)
shows every buy and sell on the day's candles. No real money, no broker, no real orders.

## The strategy ([rules.py](rules.py)): opening-range breakout with a trailing profit lock
1. The first 15 minutes set the opening range (their high and low).
2. **Buy** at the next minute's open once a minute closes above the range high. One trade per stock per day, none in the last hour.
3. **Stop loss** at the range low, never more than 1.5% under the buy.
4. **Lock profit**: once up 1%, a trailing stop follows the best price 0.5% behind it.
5. **Close**: anything held is sold 15 minutes before the close.

Each stock has its own pot of ₹1,000 or $1,000. Profit is withdrawn after a win; a loss shrinks
the pot. Broker charges and taxes are taken. Shares can be fractional so every pot can trade.

## How it runs
Your FMP plan delivers NSE candles after the day ends, so each session is **replayed once it's
over**, minute by minute as if live, without looking ahead. The cron runs at 8 AM IST (Tue–Sat):
by then the previous NSE day and the US night session have finished. "Check for new days" on
the page does the same on demand.

## Files
| File | What it does |
|---|---|
| `rules.py` | Strategy numbers, markets and stocks, Indian and US charges |
| `data.py` | 1-minute candles from Financial Modeling Prep (one stock-day per request, cached) |
| `engine.py` | One stock, one session: the opening range, the trade, the result |
| `lab.py` | Which sessions are finished; replaying a market's day |
| `__main__.py` | Terminal: `yarn lab --from 2026-11-03` |
| `jarvis_api.py` | The only Jarvis hook: `/tradinglab` routes, the 8 AM job, Firestore, Telegram |

The page is in `apps/frontend/src/tradinglab/`.

## What's stored (money only)
- `users/{uid}/tradinglab/config`: start date, 1,000 per stock, each pot now, totals, last session replayed per market.
- `users/{uid}/tradinglab_days/{date}`: that day's pot, P&L and withdrawal per stock and per market.

Trades aren't stored. The page replays a day from its candles and the pots it began with, which
always gives the same trades.

Env vars: `INTRADAY_1MIN_URL`, `INTRADAY_1MIN_API`. A start date can be up to 30 days back
(each trading day costs 10 price requests).
