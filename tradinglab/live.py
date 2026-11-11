"""
Live paper trading during market hours.

The cron pings every 5 minutes on weekdays; this decides what (if anything) to fetch:
- a market that isn't open right now (by its own exchange clock) gets no request at all
- an open market's stocks are fetched only while they can still change today: a stock that
  has sold, or has passed the last buying time without a breakout, isn't asked for again
- a market with no candles 10 minutes after its open is a holiday: no more requests that day
Each check replays today's 1-minute candles so far with the same rules (engine.simulate_day,
live=True), so the buy and sell minutes are exact; the check just reports them within minutes.
Nothing here stores trades: the end-of-day replay (jarvis_api.process) saves the day's money.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import data
from .engine import simulate_day
from .rules import MARKETS, RULES

HOLIDAY_AFTER_MINUTES = 10
_today: dict[str, list[dict]] = {}   # symbol -> today's candles from the last check (for the chart)


def market_now(key: str) -> datetime:
    return datetime.now(ZoneInfo(MARKETS[key].tz))


def is_open(key: str, now: datetime | None = None) -> bool:
    m = MARKETS[key]
    t = (now or market_now(key)).astimezone(ZoneInfo(m.tz))
    return t.weekday() < 5 and m.open <= t.strftime("%H:%M") < m.close


def session_date(key: str) -> str:
    return market_now(key).date().isoformat()


def next_open(key: str) -> str:
    """When the market next opens, e.g. "Thu 09:15" (exchange time), for the page."""
    m = MARKETS[key]
    t = market_now(key)
    d = t.date()
    if t.strftime("%H:%M") >= m.open:
        d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return f"{d.strftime('%a %d %b')} {m.open}"


def candles_today(symbol: str) -> list[dict] | None:
    return _today.get(symbol)


async def check(key: str, state: dict, pots: dict[str, float]) -> tuple[dict, list[str]]:
    """One check of an open market. `state` is the market's live record from the last check (or {}).
    -> (the new record, Telegram lines for trades that happened since the last check)."""
    m = MARKETS[key]
    day = session_date(key)
    if state.get("day") != day:
        state = {"day": day, "stocks": {}, "holiday": False, "stopped": ""}
    if state["holiday"] or state["stopped"]:
        return state, []
    todo = [s for s in m.stocks if not state["stocks"].get(s, {}).get("done")]
    if not todo:
        return state, []

    fetched: dict[str, list[dict]] = {}
    try:
        for s in todo:
            fetched[s] = await data.day(s, day, finished=False)
    except data.DataError as e:
        state["stopped"] = str(e)
        return state, [f"⏸ {m.name} live checks stopped for today: {e}"]

    now = market_now(key)
    if not any(fetched.values()):
        opened = now.replace(hour=int(m.open[:2]), minute=int(m.open[3:]), second=0, microsecond=0)
        if now >= opened + timedelta(minutes=HOLIDAY_AFTER_MINUTES):
            state["holiday"] = True
        return state, []

    lines = []
    sym = "₹" if m.currency == "INR" else "$"
    for s, candles in fetched.items():
        _today[s] = candles
        r = simulate_day(key, candles, pots.get(s, RULES.pot), live=True)
        t = r["trade"]
        prev = state["stocks"].get(s, {}).get("state")
        rec = {"state": r["state"], "note": r["note"], "pnl": r["pnl"], "price": candles[-1]["close"] if candles else None,
               "time": candles[-1]["date"][11:16] if candles else None, "range": r["range"],
               "done": r["state"] in ("sold", "no_trade"), "trade": t}
        state["stocks"][s] = rec
        if t and prev not in ("holding", "sold"):
            lines.append(f"🟢 Bought {s} at {t['buyTime']}: {sym}{t['buyPrice']:,.2f} ({t['reason']})")
        if r["state"] == "sold" and prev != "sold":
            lines.append(f"{'✅' if r['pnl'] > 0 else '🔻'} Sold {s} at {t['sellTime']}: {sym}{t['sellPrice']:,.2f}, "
                         f"{t['exit']}. Result {'+' if r['pnl'] >= 0 else '−'}{sym}{abs(r['pnl']):,.2f}")
    state["checkedAt"] = now.strftime("%H:%M")
    return state, lines
