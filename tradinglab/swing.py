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

async def daily(symbol: str, since: str) -> list[dict]:
    """Daily candles oldest first, cached for a day (one request per symbol covers years)."""
    p = CACHE / f"{symbol}_{since}.json.gz"
    if p.exists() and time.time() - p.stat().st_mtime < 86400:
        with gzip.open(p, "rt") as f:
            return json.load(f)
    url, key = data._env("INTRADAY_HISTORICAL_URL"), data._env("INTRADAY_HISTORICAL_API")
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url, params={"symbol": data.fmp_symbol(symbol), "from": since, "apikey": key})
    r.raise_for_status()
    rows = sorted(({k: x[k] for k in ("date", "open", "high", "low", "close", "volume")} for x in r.json()), key=lambda c: c["date"])
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt") as f:
        json.dump(rows, f)
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


def trades_for(market: str, rule: str, rows: list[dict], bench: dict[str, bool], amount: float, start: str) -> list[dict]:
    """Every trade one stock would have made under one rule, from `start` on."""
    closes = [r["close"] for r in rows]
    out, i = [], 0
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
        if exit_price is None:   # still open at the end of the data: leave it out
            break
        proceeds = qty * exit_price - delivery_charges(market, "sell", qty * exit_price, qty)
        out.append({"buy": e["date"], "sell": rows[exit_day]["date"], "days": exit_day - i, "pnl": round(proceeds - amount, 2),
                    "why": why, "buyPrice": price, "sellPrice": round(exit_price, 2)})
        i = exit_day + 1   # one position at a time: look again after selling
    return out


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
