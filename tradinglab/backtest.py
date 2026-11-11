"""
The strategy tester: replays months of 1-minute candles with the current rules and with each
smarter variant, and compares them. Runs on this computer from the downloaded candles (history.py).

  cd apps/api && PYTHONPATH=../.. .venv/bin/python -m tradinglab.backtest            # print the comparison
  cd apps/api && PYTHONPATH=../.. .venv/bin/python -m tradinglab.backtest --publish  # and show it on the page

Fair testing:
- every trade uses a fixed 1,000 (no compounding), so variants are compared like for like
- the period is split: the first two thirds and the last third are scored separately. An idea that
  only helps in one of them is probably luck; one that helps in both is more likely to be real.
- charges are always taken
"""

import argparse
import asyncio
import dataclasses
from datetime import date, timedelta

from . import history
from .engine import simulate_day
from .lab import weekdays
from .rules import MARKETS, RULES, Rules

VARIANTS: list[tuple[str, str, str, Rules]] = [
    ("current", "Current rules", "Opening-range breakout, 0.5% trailing stop (what the live lab uses)", RULES),
    ("volume", "+ Volume check", "Buy only if the breakout minute's volume is 1.5× the day's average", dataclasses.replace(RULES, min_volume_mult=1.5)),
    ("vwap", "+ Above VWAP", "Buy only above the day's volume-weighted average price", dataclasses.replace(RULES, above_vwap=True)),
    ("market", "+ Market up", "Buy only while NIFTYBEES / SPY is above its opening price", dataclasses.replace(RULES, market_up=True)),
    ("early", "+ Buy before 11:00", "No new buys after 11:00 exchange time", dataclasses.replace(RULES, latest_entry="11:00")),
    ("gap", "+ Skip big gaps", "Skip a stock that opened over 1.5% away from yesterday's close", dataclasses.replace(RULES, max_gap_pct=1.5)),
    ("breakeven", "+ Break-even stop", "Once up 0.7%, the stop moves up to the buy price", dataclasses.replace(RULES, breakeven_at_pct=0.7)),
    ("atr", "+ ATR trailing stop", "Trailing stop at least 3 ATRs behind the best price (wider for jumpy stocks)", dataclasses.replace(RULES, trail_atr_mult=3.0)),
    ("wide", "+ 1.5% trailing stop", "Trailing stop 1.5% behind the best price instead of 0.5%", dataclasses.replace(RULES, trail_pct=1.5)),
    ("losses", "+ Max 2 losses a day", "Stop buying in a market after 2 losing trades that day", dataclasses.replace(RULES, max_losses_per_day=2)),
    ("filters", "Filters combined", "Volume check + above VWAP + market up", dataclasses.replace(RULES, min_volume_mult=1.5, above_vwap=True, market_up=True)),
    ("exits", "Exits combined", "Break-even stop + ATR trailing stop", dataclasses.replace(RULES, breakeven_at_pct=0.7, trail_atr_mult=3.0)),
    ("all", "Everything", "All filters, both exits, buy before 11:00, max 2 losses a day",
     dataclasses.replace(RULES, min_volume_mult=1.5, above_vwap=True, market_up=True, latest_entry="11:00",
                         breakeven_at_pct=0.7, trail_atr_mult=3.0, max_losses_per_day=2)),
]


def _day_results(key: str, day: str, rules: Rules, prev: dict[str, float | None]) -> list[dict]:
    """Every stock's trade on one day; with max_losses_per_day, later buys after that many losses are skipped."""
    m = MARKETS[key]
    bench = history.cached(m.benchmark, day) or None
    out = []
    for s in m.stocks:
        candles = history.cached(s, day)
        if not candles:
            continue
        r = simulate_day(key, candles, RULES.pot, rules, bench=bench, prev_close=prev.get(s))
        prev[s] = candles[-1]["close"]
        if r["trade"]:
            out.append({"symbol": s, "pnl": r["pnl"], "buy": r["trade"]["buyTime"], "sell": r["trade"]["sellTime"]})
    if rules.max_losses_per_day:
        kept, losses = [], []
        for t in sorted(out, key=lambda t: t["buy"]):
            if sum(1 for l in losses if l <= t["buy"]) >= rules.max_losses_per_day:
                continue
            kept.append(t)
            if t["pnl"] < 0:
                losses.append(t["sell"])
        out = kept
    return out


def _score(trades_by_day: list[tuple[str, list[dict]]]) -> dict:
    pnls = [t["pnl"] for _, ts in trades_by_day for t in ts]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    daily = [sum(t["pnl"] for t in ts) for _, ts in trades_by_day]
    run = peak = drawdown = 0.0
    for d in daily:
        run += d
        peak = max(peak, run)
        drawdown = min(drawdown, run - peak)
    return {
        "trades": len(pnls), "wins": len(wins), "winRate": round(len(wins) / len(pnls) * 100, 1) if pnls else 0.0,
        "pnl": round(sum(pnls), 2), "pnlPct": round(sum(pnls) / (RULES.pot * 5) * 100, 2),
        "avgWin": round(sum(wins) / len(wins), 2) if wins else 0.0, "avgLoss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "profitFactor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
        "worstDay": round(min(daily), 2) if daily else 0.0, "maxDrawdown": round(drawdown, 2), "days": len(daily),
    }


def run(start: str, end: str) -> dict:
    days = weekdays(start, end)
    traded = {k: [d for d in days if history.cached(MARKETS[k].stocks[0], d)] for k in MARKETS}
    results = []
    for key, name, about, rules in VARIANTS:
        row = {"key": key, "name": name, "about": about, "markets": {}}
        for k in MARKETS:
            prev: dict[str, float | None] = {}
            per_day = [(d, _day_results(k, d, rules, prev)) for d in traded[k]]
            cut = len(per_day) * 2 // 3
            row["markets"][k] = {"first": _score(per_day[:cut]), "last": _score(per_day[cut:]), "all": _score(per_day)}
        results.append(row)
    base = results[0]["markets"]
    for row in results:   # an idea is "consistent" if it beats the current rules in both periods, in that market
        for k, m in row["markets"].items():
            m["beatsCurrentInBoth"] = row["key"] != "current" and m["first"]["pnl"] > base[k]["first"]["pnl"] and m["last"]["pnl"] > base[k]["last"]["pnl"]
    split = {k: {"first": f"{traded[k][0]} to {traded[k][len(traded[k]) * 2 // 3 - 1]}",
                 "last": f"{traded[k][len(traded[k]) * 2 // 3]} to {traded[k][-1]}"} for k in MARKETS if traded[k]}
    return {"from": start, "to": end, "split": split, "sessions": {k: len(v) for k, v in traded.items()}, "variants": results,
            "best": {k: max(results, key=lambda r: (r["markets"][k]["beatsCurrentInBoth"], r["markets"][k]["all"]["pnl"]))["key"] for k in MARKETS}}


def show(res: dict) -> None:
    for k, m in MARKETS.items():
        sym = "₹" if m.currency == "INR" else "$"
        print(f"\n══ {m.name}: {res['sessions'][k]} sessions, {res['from']} to {res['to']} · 5 stocks × {sym}1,000 a trade ══")
        print(f"{'':24}{'first ' + str(res['split'][k]['first']):>30}  {'last ' + str(res['split'][k]['last']):>30}   trades  win%  worst day  both?")
        for r in res["variants"]:
            x = r["markets"][k]
            print(f"{r['name']:24}{x['first']['pnl']:>+28.2f}  {x['last']['pnl']:>+31.2f}   {x['all']['trades']:>6}  {x['all']['winRate']:>4.0f}  {x['all']['worstDay']:>+9.2f}  "
                  f"{'✓' if x['beatsCurrentInBoth'] else ''}")
        best = next(r for r in res["variants"] if r["key"] == res["best"][k])
        print(f"→ best for {m.name}: {best['name']} ({best['about']})")


def publish(res: dict) -> None:
    from app.firebase import col   # only when publishing, so the tester also runs without Jarvis
    from app.timeutil import now_utc
    col("tradinglab").document("backtest").set({**res, "ranAt": now_utc().isoformat()})
    print("\nPublished: the Trading Lab page and Jarvis now show this comparison.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Compare the lab's rules with smarter variants on past candles")
    ap.add_argument("--from", dest="start", default="2026-05-11")
    ap.add_argument("--to", dest="end", default=(date.today() - timedelta(days=1)).isoformat())
    ap.add_argument("--download", action="store_true", help="download any missing candles first (paced)")
    ap.add_argument("--publish", action="store_true", help="save the comparison for the page and Jarvis")
    a = ap.parse_args()
    if a.download:
        syms = [s for m in MARKETS.values() for s in (*m.stocks, m.benchmark)]
        asyncio.run(history.download(syms, weekdays(a.start, a.end)))
    res = run(a.start, a.end)
    show(res)
    if a.publish:
        publish(res)
