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

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import data
from .engine import simulate_day
from .rules import MARKETS, RULES

HOLIDAY_AFTER_MINUTES = 10
BUSY_PAUSE_MINUTES = 10              # FMP said "too many requests": wait this long before asking again
ONE_STOCK_EVERY_S = 55               # the stock on screen is fetched at most this often
_today: dict[str, list[dict]] = {}   # symbol -> today's candles from the last check (for the chart)
_fetched_at: dict[str, float] = {}   # symbol -> when its candles were last fetched (monotonic)


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


def _paused(state: dict) -> bool:
    return bool(state.get("pausedUntil")) and datetime.now().astimezone().isoformat() < state["pausedUntil"]


def _first_refusal(state: dict, e: "data.DataError") -> bool:
    """Tell Telegram once per kind of refusal per day, not on every check."""
    return state.get("refusedAs") != ("busy" if e.busy else "stop")


def _refused(key: str, state: dict, e: "data.DataError") -> dict:
    """"Too many requests" pauses this market for a few minutes; anything else stops it for the day."""
    if e.busy:
        state["pausedUntil"] = (datetime.now().astimezone() + timedelta(minutes=BUSY_PAUSE_MINUTES)).isoformat()
    else:
        state["stopped"] = str(e)
    state["refusedAs"] = "busy" if e.busy else "stop"
    return state


def _refused_line(key: str, state: dict, e: "data.DataError") -> str:
    name = MARKETS[key].name
    return (f"⏸ {name} live checks paused for {BUSY_PAUSE_MINUTES} min: {e}. They carry on by themselves." if e.busy
            else f"⏸ {name} live checks stopped for today: {e}")


def candles_today(symbol: str) -> list[dict] | None:
    return _today.get(symbol)


def remember(symbol: str, candles: list[dict]) -> None:
    """Keep candles fetched outside a check (after a restart), so they aren't fetched again right away."""
    _today[symbol] = candles
    _fetched_at[symbol] = time.monotonic()


async def _bench(key: str, rules, day: str) -> list[dict] | None:
    """The market's benchmark candles today, for rules that watch the market's direction; fetched at most
    once a minute (one request), else None."""
    if not rules.market_up:
        return None
    b = MARKETS[key].benchmark
    if b not in _today or time.monotonic() - _fetched_at.get(b, 0.0) >= ONE_STOCK_EVERY_S:
        remember(b, await data.day(b, day, finished=False))
    return _today[b]


async def check(key: str, state: dict, pots: dict[str, float], rules=RULES) -> tuple[dict, list[str]]:
    """One check of an open market. `state` is the market's live record from the last check (or {}).
    -> (the new record, Telegram lines for trades that happened since the last check)."""
    m = MARKETS[key]
    day = session_date(key)
    if state.get("day") != day:
        state = {"day": day, "stocks": {}, "holiday": False, "stopped": ""}
    if state["holiday"] or state["stopped"] or _paused(state):
        return state, []
    todo = [s for s in m.stocks if not state["stocks"].get(s, {}).get("done")]
    if not todo:
        return state, []

    fetched: dict[str, list[dict]] = {}
    try:
        for s in todo:
            fetched[s] = await data.day(s, day, finished=False)
    except data.DataError as e:
        return _refused(key, state, e), [_refused_line(key, state, e)] if _first_refusal(state, e) else []

    now = market_now(key)
    if not any(fetched.values()):
        opened = now.replace(hour=int(m.open[:2]), minute=int(m.open[3:]), second=0, microsecond=0)
        if now >= opened + timedelta(minutes=HOLIDAY_AFTER_MINUTES):
            state["holiday"] = True
        return state, []

    lines: list[str] = []
    try:
        bench = await _bench(key, rules, day)
    except data.DataError as e:
        return _refused(key, state, e), [_refused_line(key, state, e)] if _first_refusal(state, e) else []
    for s, candles in fetched.items():
        _update(key, s, candles, pots.get(s, RULES.pot), state, lines, rules, bench)
    state["checkedAt"] = now.strftime("%H:%M")
    return state, lines


def _update(key: str, s: str, candles: list[dict], pot: float, state: dict, lines: list[str], rules=RULES, bench=None) -> None:
    """Replay one stock's candles so far into the market's live record; note a new buy or sell for Telegram."""
    _today[s] = candles
    _fetched_at[s] = time.monotonic()
    r = simulate_day(key, candles, pot, rules, live=True, bench=bench)
    before = state["stocks"].get(s, {})
    # what was already announced: how many buys, and how many sells (older records only had one trade)
    bought = before.get("bought", 1 if before.get("trade") else 0)
    sold = before.get("soldCount", 1 if before.get("state") == "sold" else 0)
    trades = r["trades"]
    state["stocks"][s] = {"state": r["state"], "note": r["note"], "pnl": r["pnl"],
                          "price": candles[-1]["close"] if candles else None,
                          "time": candles[-1]["date"][11:16] if candles else None, "range": r["range"],
                          "done": r["state"] in ("sold", "no_trade"), "trade": r["trade"], "trades": trades,
                          "bought": len(trades), "soldCount": sum(1 for t in trades if t.get("sellTime"))}
    sym = "₹" if MARKETS[key].currency == "INR" else "$"
    for n, t in enumerate(trades):
        again = " again" if n else ""
        if n >= bought:
            lines.append(f"🟢 Bought {s}{again} at {t['buyTime']}: {sym}{t['buyPrice']:,.2f} ({t['reason']})")
        if t.get("sellTime") and n >= sold:
            lines.append(f"{'✅' if t['pnl'] > 0 else '🔻'} Sold {s} at {t['sellTime']}: {sym}{t['sellPrice']:,.2f}, "
                         f"{t['exit']}. Result {'+' if t['pnl'] >= 0 else '−'}{sym}{abs(t['pnl']):,.2f}")


async def check_one(key: str, symbol: str, state: dict, pot: float, rules=RULES) -> tuple[dict, list[str], bool]:
    """Refresh just one stock (the one on screen) if its market is open and it wasn't fetched in the last
    55 seconds. -> (record, Telegram lines, whether a request was made)."""
    day = session_date(key)
    if state.get("day") != day:
        state = {"day": day, "stocks": {}, "holiday": False, "stopped": ""}
    if not is_open(key) or state["holiday"] or state["stopped"] or _paused(state):
        return state, [], False
    if state["stocks"].get(symbol, {}).get("done"):   # sold, or too late to buy: its trade can't change today
        return state, [], False
    if time.monotonic() - _fetched_at.get(symbol, 0.0) < ONE_STOCK_EVERY_S:
        return state, [], False
    try:
        candles = await data.day(symbol, day, finished=False)
        bench = await _bench(key, rules, day)
    except data.DataError as e:
        lines = [_refused_line(key, state, e)] if _first_refusal(state, e) else []
        return _refused(key, state, e), lines, True
    lines: list[str] = []
    if candles:
        _update(key, symbol, candles, pot, state, lines, rules, bench)
    else:
        _fetched_at[symbol] = time.monotonic()
    return state, lines, True
