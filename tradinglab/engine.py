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
    out = {"range": None, "trade": None, "trades": [], "note": "", "pnl": 0.0, "withdrawn": 0.0, "potStart": _r(pot), "potEnd": _r(pot), "state": "no_trade"}
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
    ctx = (rules, candles, offset, bench_map, bench_open)

    # one or more trades: buy, manage, sell; with max_trades > 1, buy again when the price turns back up
    trades: list[dict] = []
    blocked, start, cash = "", 0, pot
    while len(trades) < rules.max_trades:
        entry_i, reason, why_not = _find_entry(ctx, rest, start, hi, last_entry, again=bool(trades))
        blocked = why_not or blocked
        if entry_i is None:
            break
        invest = min(cash, pot)   # profit isn't reinvested the same day; a loss shrinks what's left
        t, exit_i = _hold(market, ctx, rest, entry_i, invest, lo, exit_at, live, reason)
        trades.append(t)
        if t.get("open"):
            break
        cash += t["pnl"]
        if (t["pnl"] < 0 and not rules.rebuy_after_loss) or exit_i is None or _t(rest[exit_i]) >= exit_at:
            break
        start = exit_i   # the minute it sold can already be the signal to buy again

    if not trades:
        if live and (not rest or _t(rest[-1]) < last_entry):   # still time for a breakout today
            out["note"], out["state"] = f"Watching for a close above {hi:,.2f} (buys until {last_entry})", "watching"
            return out
        out["note"] = (f"Breakouts above {hi:,.2f} were skipped ({blocked}) before {last_entry}" if blocked else
                       f"No breakout: the price never closed above the opening-range high of {hi:,.2f} before {last_entry}")
        return out

    pnl = sum(t["pnl"] for t in trades)
    last = trades[-1]
    out.update(trades=trades, trade=last, pnl=_r(pnl))
    if last.get("open"):   # still holding: show where it stands now
        out.update(state="holding", note=f"Holding; sells at {last['stop']:,.2f} or {exit_at}")
        return out
    more = (live and len(trades) < rules.max_trades and (last["pnl"] >= 0 or rules.rebuy_after_loss)
            and _t(rest[-1]) < last_entry)
    if more:   # sold, but it may buy again today
        out.update(state="watching", note=f"{last['exit'][:1].upper()}{last['exit'][1:]}; watching to buy again until {last_entry}")
        return out
    out.update(withdrawn=_r(max(pnl, 0.0)), potEnd=_r(pot + min(pnl, 0.0)), state="sold",
               note=last["exit"] if len(trades) == 1 else f"{len(trades)} trades; last: {last['exit']}")
    return out


def _find_entry(ctx, rest: list[dict], start: int, hi: float, last_entry: str, again: bool) -> tuple[int | None, str, str]:
    """The next buy at or after rest[start]: (index of the minute bought at its open, why, why a signal was skipped).
    First buy: a minute closes above the opening-range high. Again (after a sale): a minute closes above the
    previous minute's high while still above the range, i.e. the price has turned back up."""
    rules, candles, offset, bench_map, bench_open = ctx
    blocked = ""
    for i in range(max(start, 1 if again else 0), len(rest) - 1):
        c = rest[i]
        if _t(rest[i + 1]) >= last_entry:
            break
        if again:
            signal = c["close"] > rest[i - 1]["high"] and c["close"] > hi
        else:
            signal = c["close"] > hi * (1 + rules.breakout_pct / 100)
        if not signal:
            continue
        if (rules.min_volume_mult or rules.above_vwap or rules.market_up) and (not again or rules.rebuy_filters):
            why_not = _filters_pass(rules, candles, offset + i, bench_map, bench_open)
            if why_not:
                blocked = why_not
                continue
        reason = (f"back up: closed {c['close']:,.2f} at {_t(c)}, above the previous minute's high of {rest[i - 1]['high']:,.2f}" if again
                  else f"closed {c['close']:,.2f} at {_t(c)}, above the opening-range high of {hi:,.2f}")
        return i + 1, reason, blocked
    return None, "", blocked


def _hold(market: str, ctx, rest: list[dict], entry_i: int, pot: float, lo: float, exit_at: str, live: bool, reason: str) -> tuple[dict, int | None]:
    """Buy at rest[entry_i]'s open and manage the position minute by minute. -> (trade, index of the minute it sold;
    None while still held)."""
    rules, candles, offset, _, _ = ctx
    e = rest[entry_i]
    price = e["open"]
    buy_fee = charges(market, "buy", pot, pot / price, rules)
    qty = (pot - buy_fee) / price   # fractional shares, so every pot can trade
    stop = max(lo, price * (1 - rules.max_stop_pct / 100))
    best, trailing = price, False
    atr_gap = rules.trail_atr_mult * _atr(candles, offset + entry_i - 1) if rules.trail_atr_mult else 0.0
    exit_i, exit_price, why, sell_next = None, None, "", ""

    for j in range(entry_i, len(rest)):
        c = rest[j]
        if _t(c) >= exit_at:
            exit_i, exit_price, why = j, c["open"], f"sold {rules.exit_before_close_minutes} min before the close"
            break
        if sell_next:   # decided on the last minute's close: sell at this one's open
            exit_i, exit_price, why = j, c["open"], sell_next
            break
        if c["open"] <= stop:
            exit_i, exit_price = j, c["open"]
            why = "trailing stop (price opened under it)" if trailing else "stop loss (price opened under it)"
            break
        target = price * (1 + rules.target_pct / 100) if rules.target_pct else None
        if target and c["open"] >= target:
            exit_i, exit_price, why = j, c["open"], f"profit target (opened above +{rules.target_pct:g}%)"
            break
        if c["low"] <= stop:
            exit_i, exit_price = j, stop
            why = (f"trailing stop: fell {(best - stop) / best * 100:.2f}% from the best price of {best:,.2f}" if trailing
                   else f"break-even stop at {stop:,.2f}" if stop >= price else f"stop loss at {stop:,.2f}")
            break
        if target and c["high"] >= target:   # checked after the stop: if a minute touched both, count the stop
            exit_i, exit_price, why = j, target, f"profit target at +{rules.target_pct:g}%"
            break
        best = max(best, c["high"])
        if rules.breakeven_at_pct and best >= price * (1 + rules.breakeven_at_pct / 100):
            stop = max(stop, price * 1.0005)   # the buy price plus a little for charges
        if best >= price * (1 + rules.trail_after_pct / 100):
            trailing = True
            stop = max(stop, best - max(best * rules.trail_pct / 100, atr_gap))   # ATR can only widen the trail
        # quick profit: once it has been up enough, sell when a minute turns down (while still in profit)
        if rules.quick_exit_pct and best >= price * (1 + rules.quick_exit_pct / 100) and c["close"] > price * 1.001 and j > 0:
            p = rest[j - 1]
            turned = c["close"] < p["low"] if rules.quick_exit_on == "low" else c["close"] < p["close"]
            if turned:
                sell_next = (f"took the profit: up {(best / price - 1) * 100:.2f}% at best, then {_t(c)} closed "
                             f"{c['close']:,.2f}, below the previous minute's {'low' if rules.quick_exit_on == 'low' else 'close'}")
    base = {"buyTime": _t(e), "buyPrice": _r(price, 4), "qty": _r(qty, 4), "best": _r(best, 4), "reason": reason, "pot": _r(pot)}
    if exit_i is None and live:   # still holding
        last = rest[-1]["close"]
        value = qty * last - charges(market, "sell", qty * last, qty, rules)
        return {**base, "sellTime": None, "sellPrice": None, "charges": _r(buy_fee), "pnl": _r(value - pot),
                "pnlPct": _r((value - pot) / pot * 100), "exit": "", "open": True, "last": last, "lastTime": _t(rest[-1]),
                "stop": _r(stop, 4), "trailing": trailing}, None
    if exit_i is None:   # the data ended before the exit time (a short session)
        exit_i, exit_price, why = len(rest) - 1, rest[-1]["close"], "sold at the last price of the day"
    sell_fee = charges(market, "sell", qty * exit_price, qty, rules)
    pnl = qty * exit_price - sell_fee - pot
    return {**base, "sellTime": _t(rest[exit_i]), "sellPrice": _r(exit_price, 4), "charges": _r(buy_fee + sell_fee),
            "pnl": _r(pnl), "pnlPct": _r(pnl / pot * 100), "exit": why}, exit_i


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
