"""
Swing-trading test: hold for days instead of minutes, on daily candles, so a trade aims at moves big
enough to pay its charges. Runs on this computer; the daily candles are cached in tradinglab/.cache/daily.

  cd apps/api && PYTHONPATH=../.. .venv/bin/python -m tradinglab.swing                # 5 years, ₹/$1,000 and 10,000 a trade
  cd apps/api && PYTHONPATH=../.. .venv/bin/python -m tradinglab.swing --publish      # and show it on the page

The rules were fixed before any result was seen (so the test isn't tuned to the past):
  A  Breakout + market: close above the highest close of the 20 days before, and the market ETF
     (NIFTYBEES / SPY) above its 50-day average
  B  Breakout only: the same breakout, no market check
  C  Pullback in an uptrend: close above the 50-day average, but RSI(14) under 35 (a dip)
  All: buy at the next day's open; sell at +5% (target), −3% (stop) or at the close of the 10th day held.
  If one day touches both the stop and the target, the stop is counted (the cautious way).
  One position per stock at a time; a fixed amount per trade; charges taken (Indian delivery charges
  include ₹15.93 DP per sale, which is why the trade size matters so much).
"""

import argparse
import asyncio
import gzip
import json
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

from . import data
from .rules import MARKETS

CACHE = Path(__file__).resolve().parent / ".cache" / "daily"
TARGET, STOP, MAX_DAYS = 5.0, 3.0, 10


# ── daily candles ────────────────────────────────────────────────────────────

_memory: dict[tuple[str, str], tuple[float, list[dict]]] = {}
FRESH_S = 3 * 3600   # daily candles change once a day; a few hours' reuse is plenty


async def daily(symbol: str, since: str) -> list[dict]:
    """Daily candles oldest first (one request per symbol covers years). Reused for a few hours: from
    memory, or from the laptop's cache folder (the server can't write one, so it keeps them in memory)."""
    hit = _memory.get((symbol, since))
    if hit and time.time() - hit[0] < FRESH_S:
        return hit[1]
    p = CACHE / f"{symbol}_{since}.json.gz"
    if p.exists() and time.time() - p.stat().st_mtime < FRESH_S:
        with gzip.open(p, "rt") as f:
            rows = json.load(f)
        _memory[(symbol, since)] = (time.time(), rows)
        return rows
    url, key = data._env("INTRADAY_HISTORICAL_URL"), data._env("INTRADAY_HISTORICAL_API")
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url, params={"symbol": data.fmp_symbol(symbol), "from": since, "apikey": key})
    r.raise_for_status()
    rows = sorted(({k: x[k] for k in ("date", "open", "high", "low", "close", "volume")} for x in r.json()), key=lambda c: c["date"])
    data._count()
    _memory[(symbol, since)] = (time.time(), rows)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(p, "wt") as f:
            json.dump(rows, f)
    except OSError:
        pass   # read-only (the server): memory is enough
    return rows


# ── charges for trades held overnight ────────────────────────────────────────

def delivery_charges(market: str, side: str, value: float, qty: float) -> float:
    """India, delivery at a zero-brokerage broker: STT 0.1% both sides, exchange 0.00297% + SEBI 0.0001%
    (+18% GST), stamp duty 0.015% on buys, DP ₹15.93 per sale. US: SEC fee + FINRA TAF on sales."""
    if market == "IN":
        fees = value * 0.0000297 + value * 0.000001
        total = value * 0.001 + fees * 1.18
        return round(total + (value * 0.00015 if side == "buy" else 15.93), 2)
    return round(value * 0.0000278 + min(qty * 0.000166, 8.30), 2) if side == "sell" else 0.0


# ── signals ──────────────────────────────────────────────────────────────────

def _sma(closes: list[float], i: int, n: int) -> float | None:
    return sum(closes[i - n + 1:i + 1]) / n if i >= n - 1 else None


def _rsi(closes: list[float], i: int, n: int = 14) -> float | None:
    if i < n:
        return None
    gains = [max(0.0, closes[j] - closes[j - 1]) for j in range(i - n + 1, i + 1)]
    losses = [max(0.0, closes[j - 1] - closes[j]) for j in range(i - n + 1, i + 1)]
    g, l = sum(gains) / n, sum(losses) / n
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)


def signal(rule: str, closes: list[float], i: int, bench_up: bool | None) -> bool:
    """Does the rule say buy at the next open, judged on day i's close (no later data)?"""
    if rule in ("A", "B"):
        if i < 20 or closes[i] <= max(closes[i - 20:i]):
            return False
        return rule == "B" or bool(bench_up)
    if rule == "C":
        sma50, rsi = _sma(closes, i, 50), _rsi(closes, i)
        return sma50 is not None and rsi is not None and closes[i] > sma50 and rsi < 35
    return False


def replay(market: str, rule: str, rows: list[dict], bench: dict[str, bool], amount: float, start: str) -> dict:
    """One stock under one rule from `start`: closed trades, the position still open at the end of the data
    (with where it stands), and whether the last close signalled a buy at the next open."""
    closes = [r["close"] for r in rows]
    trades, held, i = [], None, 0
    while i < len(rows) - 1:
        if rows[i]["date"] < start or not signal(rule, closes, i, bench.get(rows[i]["date"])):
            i += 1
            continue
        e = rows[i + 1]
        price = e["open"]
        qty = (amount - delivery_charges(market, "buy", amount, amount / price)) / price
        target, stop = price * (1 + TARGET / 100), price * (1 - STOP / 100)
        exit_price = exit_day = why = None
        for j in range(i + 1, min(i + 1 + MAX_DAYS, len(rows))):
            d = rows[j]
            if d["open"] <= stop or d["low"] <= stop:          # stop first when a day touches both
                exit_price, why = min(d["open"], stop), "stop −3%"
            elif d["open"] >= target or d["high"] >= target:
                exit_price, why = max(d["open"], target), "target +5%"
            elif j == i + MAX_DAYS:
                exit_price, why = d["close"], f"{MAX_DAYS} days held"
            if exit_price is not None:
                exit_day = j
                break
        if exit_price is None:   # still held at the end of the data
            last = rows[-1]
            value = qty * last["close"] - delivery_charges(market, "sell", qty * last["close"], qty)
            held = {"buy": e["date"], "buyPrice": price, "qty": round(qty, 4), "last": last["close"], "lastDate": last["date"],
                    "daysHeld": len(rows) - 1 - i, "target": round(target, 2), "stop": round(stop, 2),
                    "pnl": round(value - amount, 2), "pnlPct": round((last["close"] / price - 1) * 100, 2)}
            return {"trades": trades, "held": held, "buyNext": False}
        proceeds = qty * exit_price - delivery_charges(market, "sell", qty * exit_price, qty)
        trades.append({"buy": e["date"], "sell": rows[exit_day]["date"], "days": exit_day - i, "pnl": round(proceeds - amount, 2),
                       "why": why, "buyPrice": price, "sellPrice": round(exit_price, 2)})
        i = exit_day + 1   # one position at a time: look again after selling
    last_i = len(rows) - 1
    buy_next = bool(rows) and rows[last_i]["date"] >= start and signal(rule, closes, last_i, bench.get(rows[last_i]["date"]))
    return {"trades": trades, "held": None, "buyNext": buy_next}


def trades_for(market: str, rule: str, rows: list[dict], bench: dict[str, bool], amount: float, start: str) -> list[dict]:
    """Every closed trade one stock would have made under one rule, from `start` on."""
    return replay(market, rule, rows, bench, amount, start)["trades"]


def bench_up(rows: list[dict]) -> dict[str, bool]:
    """date -> was the market ETF above its 50-day average at that close."""
    c = [r["close"] for r in rows]
    return {r["date"]: (_sma(c, i, 50) is not None and c[i] > _sma(c, i, 50)) for i, r in enumerate(rows)}


def _score(trades: list[dict], amount: float, stocks: int) -> dict:
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    run = peak = dd = 0.0
    for t in sorted(trades, key=lambda t: t["sell"]):
        run += t["pnl"]; peak = max(peak, run); dd = min(dd, run - peak)
    return {"trades": len(pnls), "winRate": round(len(wins) / len(pnls) * 100, 1) if pnls else 0.0, "pnl": round(sum(pnls), 2),
            "pnlPct": round(sum(pnls) / (amount * stocks) * 100, 1), "avgDays": round(sum(t["days"] for t in trades) / len(trades), 1) if trades else 0,
            "maxDrawdown": round(dd, 2), "worstTrade": round(min(pnls), 2) if pnls else 0.0}


async def run(start: str, amounts: tuple[float, ...] = (1000.0, 10000.0)) -> dict:
    warmup = (date.fromisoformat(start) - timedelta(days=120)).isoformat()   # room for the 50-day average
    out = {"from": start, "to": None, "rules": {"A": "Breakout + market", "B": "Breakout only", "C": "Pullback in an uptrend"},
           "markets": {}}
    for key, m in MARKETS.items():
        bench_rows = await daily(m.benchmark, warmup)
        bc = [r["close"] for r in bench_rows]
        bench_up = {r["date"]: (_sma(bc, i, 50) is not None and bc[i] > _sma(bc, i, 50)) for i, r in enumerate(bench_rows)}
        rows = {s: await daily(s, warmup) for s in m.stocks}
        days = sorted({r["date"] for rs in rows.values() for r in rs if r["date"] >= start})
        cut = days[len(days) * 2 // 3]
        out["to"] = days[-1]
        res = {"split": {"first": f"{days[0]} to {days[len(days) * 2 // 3 - 1]}", "last": f"{cut} to {days[-1]}"}, "amounts": {}}
        for amount in amounts:
            per = {}
            for rule in ("A", "B", "C"):
                ts = [t for s in m.stocks for t in trades_for(key, rule, rows[s], bench_up, amount, start)]
                per[rule] = {"first": _score([t for t in ts if t["buy"] < cut], amount, len(m.stocks)),
                             "last": _score([t for t in ts if t["buy"] >= cut], amount, len(m.stocks)),
                             "all": _score(ts, amount, len(m.stocks))}
            hold = 0.0   # the yardstick: buy every stock at the start and simply keep it
            for s in m.stocks:
                rs = [r for r in rows[s] if r["date"] >= start]
                q = (amount - delivery_charges(key, "buy", amount, amount / rs[0]["open"])) / rs[0]["open"]
                hold += q * rs[-1]["close"] - delivery_charges(key, "sell", q * rs[-1]["close"], q) - amount
            per["hold"] = {"all": {"pnl": round(hold, 2), "pnlPct": round(hold / (amount * len(m.stocks)) * 100, 1)}}
            res["amounts"][str(int(amount))] = per
        out["markets"][key] = res
    return out


# ── for the live lab ─────────────────────────────────────────────────────────

LIVE_RULE, LIVE_MARKET = "A", "US"   # the one swing strategy the lab runs: breakout + market, US stocks


async def _finished_rows(symbol: str, since: str, before: str | None) -> list[dict]:
    rows = await daily(symbol, since)
    return [r for r in rows if not before or r["date"] < before]


async def lab_state(start: str, amount: float = 1000.0, unfinished: str | None = None) -> dict:
    """The live lab's US swing strategy since `start`: closed trades, open positions and buys due at the
    next open. `unfinished`: a session still trading today, left out so a half day can't trigger anything."""
    m = MARKETS[LIVE_MARKET]
    warm = (date.fromisoformat(start) - timedelta(days=120)).isoformat()
    up = bench_up(await _finished_rows(m.benchmark, warm, unfinished))
    stocks, closed, held, buy_next, as_of = {}, [], [], [], ""
    for s in m.stocks:
        rows = await _finished_rows(s, warm, unfinished)
        r = replay(LIVE_MARKET, LIVE_RULE, rows, up, amount, start)
        as_of = max(as_of, rows[-1]["date"]) if rows else as_of
        closed += [{**t, "symbol": s} for t in r["trades"]]
        if r["held"]:
            held.append({**r["held"], "symbol": s})
        if r["buyNext"]:
            buy_next.append(s)
    realised = round(sum(t["pnl"] for t in closed), 2)
    unrealised = round(sum(h["pnl"] for h in held), 2)
    return {"rule": "Breakout + market (rule A)", "market": LIVE_MARKET, "start": start, "amount": amount, "asOf": as_of,
            "realised": realised, "unrealised": unrealised, "total": round(realised + unrealised, 2),
            "trades": len(closed), "wins": sum(1 for t in closed if t["pnl"] > 0),
            "closed": sorted(closed, key=lambda t: t["sell"], reverse=True), "held": held, "buyNext": buy_next,
            "about": f"Buy at the next open after a close above the 20-day high while SPY is above its 50-day average; "
                     f"sell at +{TARGET:g}%, −{STOP:g}% or after {MAX_DAYS} days. {amount:,.0f} a trade."}


async def hold_since(key: str, start: str, amount: float = 1000.0, unfinished: str | None = None) -> dict:
    """The yardstick: buy each of the market's 5 stocks with `amount` at the first open on or after `start`
    and simply keep them. Value at the last finished close, as if sold then (charges included)."""
    m = MARKETS[key]
    warm = (date.fromisoformat(start) - timedelta(days=120)).isoformat()   # same request as lab_state's
    total, per = 0.0, {}
    for s in m.stocks:
        rows = [r for r in await _finished_rows(s, warm, unfinished) if r["date"] >= start]
        if not rows:
            continue
        first, last = rows[0], rows[-1]
        q = (amount - delivery_charges(key, "buy", amount, amount / first["open"])) / first["open"]
        pnl = q * last["close"] - delivery_charges(key, "sell", q * last["close"], q) - amount
        per[s] = {"buy": first["open"], "last": last["close"], "pnl": round(pnl, 2)}
        total += pnl
    return {"pnl": round(total, 2), "pnlPct": round(total / (amount * len(m.stocks)) * 100, 2), "start": start, "stocks": per}


def show(res: dict) -> None:
    for key, m in MARKETS.items():
        r = res["markets"][key]
        sym = "₹" if m.currency == "INR" else "$"
        print(f"\n══ {m.name} swing test, {res['from']} to {res['to']} · first {r['split']['first']} · last {r['split']['last']} ══")
        for amount, per in r["amounts"].items():
            print(f"  {sym}{int(amount):,} a trade, 5 stocks:")
            for rule, name in res["rules"].items():
                x = per[rule]
                print(f"    {rule} {name:24} first {x['first']['pnl']:>+10,.2f}  last {x['last']['pnl']:>+10,.2f}  total {x['all']['pnl']:>+10,.2f} "
                      f"({x['all']['pnlPct']:+.1f}%)  trades {x['all']['trades']:3}  won {x['all']['winRate']:.0f}%  "
                      f"avg {x['all']['avgDays']} days  worst drop {x['all']['maxDrawdown']:+,.2f}")
            print(f"    Buy and hold all 5          total {per['hold']['all']['pnl']:>+10,.2f} ({per['hold']['all']['pnlPct']:+.1f}%)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Swing-trading test on daily candles")
    ap.add_argument("--from", dest="start", default=(date.today() - timedelta(days=5 * 365 - 150)).isoformat())
    ap.add_argument("--publish", action="store_true")
    a = ap.parse_args()
    result = asyncio.run(run(a.start))
    show(result)
    if a.publish:
        from app.firebase import col
        from app.timeutil import now_utc
        col("tradinglab").document("swing").set({**result, "ranAt": now_utc().isoformat()})
        print("\nPublished for the page and Jarvis.")
