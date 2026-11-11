"""
The day-trading replay: one stock, one session, minute by minute (rules in rules.py).

It never looks ahead. A decision made on a minute's close acts at the next minute's open,
and stops are checked against each minute's low before that minute's high can move them.
Given the same candles and the same pot it always gives the same trade, so only each day's
money is stored; the trade itself is replayed whenever the page shows that day.
"""

from datetime import datetime, timedelta

from .rules import MARKETS, RULES, Rules, charges


def _t(c: dict) -> str:
    return c["date"][11:16]   # "2026-11-09 10:02:00" -> "10:02"


def _shift(hhmm: str, minutes: int) -> str:
    return (datetime.strptime(hhmm, "%H:%M") + timedelta(minutes=minutes)).strftime("%H:%M")


def _r(x: float, digits: int = 2) -> float:
    return round(x, digits)


def _filters_pass(rules: Rules, candles: list[dict], upto: int, bench: dict[str, float] | None, bench_open: float | None) -> str:
    """"" if the optional buy filters allow a buy on candle `upto` (using candles up to it only), else why not."""
    c = candles[upto]
    if rules.min_volume_mult:
        avg = sum(x.get("volume", 0) for x in candles[:upto + 1]) / (upto + 1)
        if c.get("volume", 0) < rules.min_volume_mult * avg:
            return "volume too low"
    if rules.above_vwap:
        pv = sum((x["high"] + x["low"] + x["close"]) / 3 * x.get("volume", 0) for x in candles[:upto + 1])
        v = sum(x.get("volume", 0) for x in candles[:upto + 1])
        if v and c["close"] <= pv / v:
            return "below VWAP"
    if rules.market_up and bench is not None and bench_open:
        t = _t(c)
        level = None
        for bt in sorted(bench):
            if bt > t:
                break
            level = bench[bt]
        if level is None or level <= bench_open:
            return "market down"
    return ""


def _atr(candles: list[dict], upto: int, n: int = 14) -> float:
    rows = candles[max(1, upto - n + 1):upto + 1]
    trs = [max(r["high"] - r["low"], abs(r["high"] - candles[candles.index(r) - 1]["close"]),
               abs(r["low"] - candles[candles.index(r) - 1]["close"])) for r in rows]
    return sum(trs) / len(trs) if trs else 0.0


def simulate_day(market: str, candles: list[dict], pot: float, rules: Rules = RULES, live: bool = False,
                 bench: list[dict] | None = None, prev_close: float | None = None) -> dict:
    """-> {"range", "trade" (or None), "note", "pnl", "withdrawn", "potStart", "potEnd", "state"} for one session.
    `live`: the session is still going, so candles stop at "now". A position with no sell yet is still
    held (state "holding"), and no breakout yet only means "watching", not "no trade".
    state: "range" (first minutes), "watching", "holding", "sold", "no_trade", "closed"."""
    m = MARKETS[market]
    out = {"range": None, "trade": None, "note": "", "pnl": 0.0, "withdrawn": 0.0, "potStart": _r(pot), "potEnd": _r(pot), "state": "no_trade"}
    if not candles:
        out["note"], out["state"] = ("Waiting for the first prices", "range") if live else ("No trading that day", "closed")
        return out
    range_end = _shift(m.open, rules.range_minutes)
    last_entry = _shift(m.close, -rules.no_entry_last_minutes)
    if rules.latest_entry and rules.latest_entry < last_entry:
        last_entry = rules.latest_entry
    exit_at = _shift(m.close, -rules.exit_before_close_minutes)
    opening = [c for c in candles if _t(c) < range_end]
    if live and _t(candles[-1]) < range_end:
        out["note"], out["state"] = f"Setting the opening range until {range_end}", "range"
        return out
    if len(opening) < rules.range_minutes // 3:
        out["note"] = "Too few prices in the first minutes to set an opening range"
        return out
    hi, lo = max(c["high"] for c in opening), min(c["low"] for c in opening)
    out["range"] = {"high": hi, "low": lo, "until": range_end}
    rest = [c for c in candles if _t(c) >= range_end]
    if rules.max_gap_pct and prev_close and abs(candles[0]["open"] / prev_close - 1) * 100 > rules.max_gap_pct:
        out["note"] = (f"Skipped: opened {candles[0]['open'] / prev_close * 100 - 100:+.1f}% from yesterday's close "
                       f"(more than {rules.max_gap_pct:g}%)")
        out["state"] = "no_trade"
        return out
    bench_map = {_t(b): b["close"] for b in bench} if bench else None
    bench_open = bench[0]["open"] if bench else None
    offset = len(candles) - len(rest)   # rest[i] is candles[offset + i]
    blocked = ""

    # 1. find the breakout: a minute closing above the range high; buy at the next minute's open
    entry_i = None
    for i, c in enumerate(rest[:-1]):
        if _t(rest[i + 1]) >= last_entry:
            break
        if c["close"] > hi * (1 + rules.breakout_pct / 100):
            why_not = _filters_pass(rules, candles, offset + i, bench_map, bench_open) if (
                rules.min_volume_mult or rules.above_vwap or rules.market_up) else ""
            if why_not:
                blocked = why_not
                continue
            entry_i = i + 1
            break
    if entry_i is None:
        if live and (not rest or _t(rest[-1]) < last_entry):   # still time for a breakout today
            out["note"], out["state"] = f"Watching for a close above {hi:,.2f} (buys until {last_entry})", "watching"
            return out
        out["note"] = (f"Breakouts above {hi:,.2f} were skipped ({blocked}) before {last_entry}" if blocked else
                       f"No breakout: the price never closed above the opening-range high of {hi:,.2f} before {last_entry}")
        return out

    e = rest[entry_i]
    price = e["open"]
    buy_fee = charges(market, "buy", pot, pot / price, rules)
    qty = (pot - buy_fee) / price   # fractional shares, so every pot can trade
    stop = max(lo, price * (1 - rules.max_stop_pct / 100))
    best, trailing = price, False
    atr_gap = rules.trail_atr_mult * _atr(candles, offset + entry_i - 1) if rules.trail_atr_mult else 0.0
    exit_c, exit_price, why = None, None, ""

    # 2. manage the position minute by minute
    for c in rest[entry_i:]:
        if _t(c) >= exit_at:
            exit_c, exit_price, why = c, c["open"], f"sold {rules.exit_before_close_minutes} min before the close"
            break
        if c["open"] <= stop:
            exit_c, exit_price = c, c["open"]
            why = "trailing stop (price opened under it)" if trailing else "stop loss (price opened under it)"
            break
        target = price * (1 + rules.target_pct / 100) if rules.target_pct else None
        if target and c["open"] >= target:
            exit_c, exit_price, why = c, c["open"], f"profit target (opened above +{rules.target_pct:g}%)"
            break
        if c["low"] <= stop:
            exit_c, exit_price = c, stop
            why = (f"trailing stop: fell {(best - stop) / best * 100:.2f}% from the best price of {best:,.2f}" if trailing
                   else f"break-even stop at {stop:,.2f}" if stop >= price else f"stop loss at {stop:,.2f}")
            break
        if target and c["high"] >= target:   # checked after the stop: if a minute touched both, count the stop
            exit_c, exit_price, why = c, target, f"profit target at +{rules.target_pct:g}%"
            break
        best = max(best, c["high"])
        if rules.breakeven_at_pct and best >= price * (1 + rules.breakeven_at_pct / 100):
            stop = max(stop, price * 1.0005)   # the buy price plus a little for charges
        if best >= price * (1 + rules.trail_after_pct / 100):
            trailing = True
            stop = max(stop, best - max(best * rules.trail_pct / 100, atr_gap))   # ATR can only widen the trail
    if exit_c is None and live:   # still holding: show where it stands now
        last = rest[-1]["close"]
        value = qty * last - charges(market, "sell", qty * last, qty, rules)
        out.update(pnl=_r(value - pot), state="holding", note=f"Holding; sells at {stop:,.2f} or {exit_at}")
        out["trade"] = {
            "buyTime": _t(e), "buyPrice": _r(price, 4), "qty": _r(qty, 4), "sellTime": None, "sellPrice": None,
            "best": _r(best, 4), "charges": _r(buy_fee), "pnl": _r(value - pot), "pnlPct": _r((value - pot) / pot * 100),
            "reason": f"closed {rest[entry_i - 1]['close']:,.2f} at {_t(rest[entry_i - 1])}, above the opening-range high of {hi:,.2f}",
            "exit": "", "open": True, "last": last, "lastTime": _t(rest[-1]), "stop": _r(stop, 4), "trailing": trailing,
        }
        return out
    if exit_c is None:   # the data ended before the exit time (a short session)
        exit_c, exit_price, why = rest[-1], rest[-1]["close"], "sold at the last price of the day"

    sell_fee = charges(market, "sell", qty * exit_price, qty, rules)
    proceeds = qty * exit_price - sell_fee
    pnl = proceeds - pot
    withdrawn = max(pnl, 0.0)
    out.update(pnl=_r(pnl), withdrawn=_r(withdrawn), potEnd=_r(pot + min(pnl, 0.0)), note=why, state="sold")
    out["trade"] = {
        "buyTime": _t(e), "buyPrice": _r(price, 4), "qty": _r(qty, 4), "sellTime": _t(exit_c), "sellPrice": _r(exit_price, 4),
        "best": _r(best, 4), "charges": _r(buy_fee + sell_fee), "pnl": _r(pnl), "pnlPct": _r(pnl / pot * 100),
        "reason": f"closed {rest[entry_i - 1]['close']:,.2f} at {_t(rest[entry_i - 1])}, above the opening-range high of {hi:,.2f}",
        "exit": why,
    }
    return out


def candles_every(candles: list[dict], minutes: int = 5) -> list[dict]:
    """1-minute candles grouped into `minutes`-minute ones, for the chart."""
    out: list[dict] = []
    for c in candles:
        h, mi = int(c["date"][11:13]), int(c["date"][14:16])
        slot = f"{h:02d}:{mi - mi % minutes:02d}"
        if out and out[-1]["time"] == slot:
            b = out[-1]
            b["high"], b["low"], b["close"] = max(b["high"], c["high"]), min(b["low"], c["low"]), c["close"]
            b["volume"] += c.get("volume", 0)
        else:
            out.append({"time": slot, "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"],
                        "volume": c.get("volume", 0)})
    return out
