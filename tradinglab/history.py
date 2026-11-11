"""
Months of 1-minute candles for the strategy tester, kept on this computer (never in Firestore):
tradinglab/.cache/candles/<SYMBOL>/<YYYY-MM-DD>.json.gz. Each stock-day is downloaded once.

FMP limits how many requests arrive in a burst, so downloads are paced (about 30 a minute by default)
and back off for a minute whenever FMP answers "too many requests". That also leaves room for the
live lab's own checks, which use the same key.
"""

import asyncio
import gzip
import json
import time
from datetime import date
from pathlib import Path

from . import data

CACHE = Path(__file__).resolve().parent / ".cache" / "candles"


def _path(symbol: str, day: str) -> Path:
    return CACHE / symbol / f"{day}.json.gz"


def cached(symbol: str, day: str) -> list[dict] | None:
    p = _path(symbol, day)
    if not p.exists():
        return None
    with gzip.open(p, "rt") as f:
        return json.load(f)


def _save(symbol: str, day: str, rows: list[dict]) -> None:
    p = _path(symbol, day)
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt") as f:
        json.dump(rows, f, separators=(",", ":"))


async def download(symbols: list[str], days: list[str], per_minute: int = 30, say=print) -> dict:
    """Fill the cache for every (symbol, day) not there yet. Days already finished only: never today.
    FMP returns up to two sessions per request, so two missing weekdays in a row share one request."""
    todo: list[tuple[str, list[str]]] = []   # (symbol, [day] or [day, next day])
    for s in symbols:
        missing = [d for d in days if cached(s, d) is None]
        i = 0
        while i < len(missing):
            pair = missing[i:i + 2]
            # only days next to each other on the calendar: FMP counts calendar days, so a Friday-to-Monday
            # request returns just Monday (the Friday would be lost)
            if len(pair) == 2 and (date.fromisoformat(pair[1]) - date.fromisoformat(pair[0])).days != 1:
                pair = pair[:1]
            todo.append((s, pair))
            i += len(pair)
    left = sum(len(p) for _, p in todo)
    say(f"{len(symbols) * len(days) - left} stock-days already downloaded, {left} to go in {len(todo)} requests "
        f"(about {len(todo) / per_minute:.0f} min at {per_minute} a minute)")
    gap, waits = 60 / per_minute, 0
    start = time.monotonic()
    for i, (s, pair) in enumerate(todo, 1):
        t0 = time.monotonic()
        while True:
            try:
                rows = await data._get({"symbol": data.fmp_symbol(s), "from": pair[0], "to": pair[-1]})
                break
            except data.DataError as e:
                if not e.busy:
                    raise
                waits += 1
                say(f"  FMP says too many requests; waiting a minute (pause {waits})")
                await asyncio.sleep(60)
        for d in pair:   # [] for a holiday is saved too, so it isn't asked again
            _save(s, d, [c for c in rows if c["date"].startswith(d)])
        if i % 50 == 0 or i == len(todo):
            say(f"  {i}/{len(todo)} requests done ({(time.monotonic() - start) / 60:.0f} min)")
        await asyncio.sleep(max(0.0, gap - (time.monotonic() - t0)))
    return {"requests": len(todo), "pauses": waits}
