"""
Which sessions are finished, and replaying them in order with each stock's pot carried forward.
No storage here: jarvis_api.py saves the results, the terminal command just prints them.
"""

import asyncio
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import data
from .engine import simulate_day
from .rules import MARKETS, RULES, Rules


def weekdays(start: str, end: str) -> list[str]:
    d, last, out = date.fromisoformat(start), date.fromisoformat(end), []
    while d <= last:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def last_closed_session(market: str, now: datetime | None = None) -> str:
    """The newest weekday whose session has closed, by the exchange's own clock (no request needed).
    Holidays aren't known here; asking FMP then shows the session simply isn't there."""
    m = MARKETS[market]
    local = (now or datetime.now(ZoneInfo(m.tz))).astimezone(ZoneInfo(m.tz))
    d = local.date()
    if d.weekday() >= 5 or local.strftime("%H:%M") < m.close:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


RECHECK_SECONDS = 30 * 60   # FMP hasn't got a closed session yet: don't ask again for half an hour
_checked: dict[str, tuple[float, str | None, str]] = {}   # market -> (when, newest it had, session we hoped for)


async def newest_available(market: str, have: str | None) -> str | None:
    """The newest finished session worth replaying, asking FMP only when one can be new:
    no request if `have` (already replayed) is already the last closed session, and at most one
    request per half hour while FMP is still catching up with a closed session."""
    expected = last_closed_session(market)
    if have and have >= expected:
        return have                                   # nothing can be new: market closed since, or weekend
    hit = _checked.get(market)
    if hit and hit[2] == expected and time.monotonic() - hit[0] < RECHECK_SECONDS:
        return hit[1]
    newest = await newest_finished(market)
    _checked[market] = (time.monotonic(), newest, expected)
    return newest


async def newest_finished(market: str) -> str | None:
    """The newest session FMP has complete candles for, judged on the market's first stock.
    A session counts as finished once its candles reach the last half hour, or a later one exists."""
    m = MARKETS[market]
    rows = await data.latest(m.stocks[0])
    if not rows:
        return None
    last_day = rows[-1]["date"][:10]
    minutes = lambda hhmm: int(hhmm[:2]) * 60 + int(hhmm[3:5])   # noqa: E731
    if minutes(rows[-1]["date"][11:16]) >= minutes(m.close) - 30:
        return last_day
    earlier = sorted({r["date"][:10] for r in rows if r["date"][:10] < last_day})
    return earlier[-1] if earlier else None


async def replay_day(market: str, day: str, pots: dict[str, float], rules: Rules = RULES) -> dict[str, dict] | None:
    """Every stock of one market on one day -> {symbol: simulate_day result}; None if the market was closed."""
    m = MARKETS[market]
    candles = await asyncio.gather(*(data.day(s, day) for s in m.stocks))
    if not any(candles):
        return None
    return {s: simulate_day(market, c, pots.get(s, rules.pot), rules) for s, c in zip(m.stocks, candles)}
