"""
Stock prices from Financial Modeling Prep (FMP).

Env vars (Render → Environment, or apps/api/.env locally):
  INTRADAY_1MIN_URL / INTRADAY_1MIN_API               1-minute candles (what the strategy trades on)
  INTRADAY_HISTORICAL_URL / INTRADAY_HISTORICAL_API   daily candles (not used by the strategy yet)

One request returns at most two sessions of 1-minute candles, so the lab asks for one stock and
one day at a time. A finished day never changes, so it's kept in memory after the first fetch.
On the current plan NSE candles arrive after the market day ends, so the lab replays each
session once it's over instead of trading live.
"""

import asyncio
import os
from collections import OrderedDict
from pathlib import Path

import httpx

from .rules import STOCKS

_ENV_FILES = [Path(__file__).resolve().parent.parent / "apps" / "api" / ".env"]
_days: OrderedDict[tuple[str, str], list[dict]] = OrderedDict()   # (symbol, day) -> candles; finished days only
MAX_CACHED_DAYS = 400
_sem = asyncio.Semaphore(5)
_calls = {"day": "", "count": 0}   # requests sent to FMP today (UTC day), shown on the page


def calls_today() -> int:
    from datetime import datetime, timezone
    return _calls["count"] if _calls["day"] == datetime.now(timezone.utc).date().isoformat() else 0


def _count() -> None:
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    if _calls["day"] != today:
        _calls.update(day=today, count=0)
    _calls["count"] += 1


class DataError(Exception):
    """FMP couldn't give us prices; the message says why, in a sentence."""


def _env(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name]
    for f in _ENV_FILES:   # local runs: the API's .env isn't loaded into os.environ
        if f.exists():
            for line in f.read_text().splitlines():
                key, _, value = line.partition("=")
                if key.strip() == name:
                    return value.strip().strip('"').strip("'")
    return ""


def configured() -> bool:
    return bool(_env("INTRADAY_1MIN_URL") and _env("INTRADAY_1MIN_API"))


async def _get(params: dict) -> list[dict]:
    url, key = _env("INTRADAY_1MIN_URL"), _env("INTRADAY_1MIN_API")
    if not url or not key:
        raise DataError("INTRADAY_1MIN_URL and INTRADAY_1MIN_API aren't set, so there are no prices to trade on.")
    async with _sem:
        _count()
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.get(url, params={**params, "apikey": key})
    if r.status_code in (401, 402, 403, 429):
        raise DataError(f"Financial Modeling Prep refused the request ({r.status_code}): the API key, the plan or today's call limit.")
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise DataError(f"Financial Modeling Prep didn't return prices: {str(data)[:160]}")
    return sorted(({k: row[k] for k in ("date", "open", "high", "low", "close", "volume") if k in row} for row in data),
                  key=lambda c: c["date"])


def fmp_symbol(symbol: str) -> str:
    return symbol + STOCKS[symbol].suffix


async def latest(symbol: str) -> list[dict]:
    """The most recent sessions FMP has (about two), oldest first. Not cached: it moves."""
    return await _get({"symbol": fmp_symbol(symbol)})


async def day(symbol: str, date: str, finished: bool = True) -> list[dict]:
    """One session's 1-minute candles (exchange local time), oldest first; [] for a holiday.
    `finished` days are cached: their candles don't change any more."""
    hit = _days.get((symbol, date))
    if hit is not None:
        _days.move_to_end((symbol, date))
        return hit
    rows = [c for c in await _get({"symbol": fmp_symbol(symbol), "from": date, "to": date}) if c["date"].startswith(date)]
    if finished:
        _days[(symbol, date)] = rows
        while len(_days) > MAX_CACHED_DAYS:
            _days.popitem(last=False)
    return rows
