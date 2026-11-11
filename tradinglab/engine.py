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


def simulate_day(market: str, candles: list[dict], pot: float, rules: Rules = RULES, live: bool = False) -> dict:
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

    # 1. find the breakout: a minute closing above the range high; buy at the next minute's open
    entry_i = None
    for i, c in enumerate(rest[:-1]):
        if _t(rest[i + 1]) >= last_entry:
            break
        if c["close"] > hi:
            entry_i = i + 1
            break
    if entry_i is None:
        if live and (not rest or _t(rest[-1]) < last_entry):   # still time for a breakout today
            out["note"], out["state"] = f"Watching for a close above {hi:,.2f} (buys until {last_entry})", "watching"
            return out
        out["note"] = f"No breakout: the price never closed above the opening-range high of {hi:,.2f} before {last_entry}"
        return out

    e = rest[entry_i]
    price = e["open"]
    buy_fee = charges(market, "buy", pot, pot / price, rules)
    qty = (pot - buy_fee) / price   # fractional shares, so every pot can trade
    stop = max(lo, price * (1 - rules.max_stop_pct / 100))
    best, trailing = price, False
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
        if c["low"] <= stop:
            exit_c, exit_price = c, stop
            why = (f"trailing stop: fell {rules.trail_pct:g}% from the best price of {best:,.2f}" if trailing
                   else f"stop loss at {stop:,.2f}")
            break
        best = max(best, c["high"])
        if best >= price * (1 + rules.trail_after_pct / 100):
            trailing = True
            stop = max(stop, best * (1 - rules.trail_pct / 100))
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
