# Trading Lab

Day trading with pretend money, for learning. Jarvis trades 10 stocks (5 NSE, 5 US) with
1,000 each in the stock's own currency, and the dashboard (**Trading Lab** in the sidebar)
shows every buy and sell on the day's candles. No real money, no broker, no real orders.

## The strategy ([rules.py](rules.py)): opening-range breakout with a trailing profit lock
1. The first 15 minutes set the opening range (their high and low).
2. **Buy** at the next minute's open once a minute closes above the range high. No new buys in the last hour.
   Both markets now run **"Quick profits, up to 3 trades a day"** (`quick3` in rules.py): the first buy also needs the
   volume, VWAP and market-up filters; once a trade has been 0.5% up it sells on the first minute that closes lower,
   then buys again when a minute closes above the one before (up to 3 trades a stock a day).
3. **Stop loss** at the range low, never more than 1.5% under the buy.
4. **Lock profit**: once up 1%, a trailing stop follows the best price 0.5% behind it.
5. **Close**: anything held is sold 15 minutes before the close.

Each stock has its own pot of ₹1,000 or $1,000. Profit is withdrawn after a win; a loss shrinks
the pot. Broker charges and taxes are taken. Shares can be fractional so every pot can trade.

## How it runs
- **Live, during market hours.** A cron ping every 5 minutes on weekdays calls `/tradinglab/live`. The API
  checks each exchange's own clock (NSE 09:15–15:30 IST, US 09:30–16:00 New York time) and asks FMP for
  prices **only while that market is open**. Each check replays today's 1-minute candles so far with the
  same rules, so buys and sells happen on the exact minute; Telegram hears about each one within 5 minutes.
  A stock that has sold, or can't buy any more today, isn't asked for again; a market with no candles
  10 minutes after its open is treated as a holiday and skipped for the day.
- **Right after each close** the session is replayed in full and its money saved.
- **8 AM IST** (Tue–Sat) a catch-up job saves any session the live checks missed.
- Requests: at most 5 per market per 5-minute check, fewer as stocks finish, so roughly 400–800 on a day
  when both markets trade. Nothing at all on weekends, holidays or outside trading hours.

## Files
| File | What it does |
|---|---|
| `rules.py` | Strategy numbers, markets and stocks, Indian and US charges |
| `data.py` | 1-minute candles from Financial Modeling Prep (one stock-day per request, cached) |
| `engine.py` | One stock, one session: the opening range, the trade, the result |
| `lab.py` | Which sessions are finished; replaying a market's day |
| `live.py` | Live checks while a market is open |
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
