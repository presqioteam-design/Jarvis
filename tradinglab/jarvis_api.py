"""
The Trading Lab inside Jarvis: the only file in tradinglab/ that knows about Jarvis.
apps/api/app/main.py includes this router; everything else here runs on its own.

Firestore (under users/{uid}/), money only:
  tradinglab/config              start date, 1,000 per stock, each stock's pot now, totals,
                                 and the last session replayed per market
  tradinglab_days/{YYYY-MM-DD}   that day's money per stock and per market
Trades aren't stored: a day's trades are replayed from its candles and the pots it started with.
"""

import asyncio
import logging
import time
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.deps import require_cron, require_user
from app.firebase import col, db
from app.services import keepalive, telegram
from app.timeutil import now_utc

from . import data, live, swing
from .engine import candles_every, simulate_day
from .lab import last_closed_session, newest_available, replay_day, weekdays
from .rules import DEFAULT_STRATEGY, MARKETS, RULES, STRATEGIES, strategy

log = logging.getLogger(__name__)
router = APIRouter(prefix="/tradinglab", tags=["tradinglab"])
VERSION = 2                 # v1 was the daily-candle swing lab; its config is ignored
MAX_START_DAYS = 30         # how far back a start date may go (each session costs 10 FMP calls)
MAX_DAYS_PER_RUN = 25

_task: asyncio.Task | None = None
_last_error = ""


def _cfg_ref():
    return col("tradinglab").document("config")


def _config() -> dict | None:
    snap = _cfg_ref().get()
    cfg = snap.to_dict() if snap.exists else None
    return cfg if cfg and cfg.get("version") == VERSION else None


def strategy_key(cfg: dict, key: str, day: str | None = None) -> str:
    """The rule set a market runs (on `day`, if given): sessions before the market's switch date keep the
    rules they ran with."""
    since = (cfg.get("strategySince") or {}).get(key)
    if day and since and day < since:
        return "current"
    return (cfg.get("strategy") or {}).get(key, "current")


def rules_for(cfg: dict, key: str, day: str | None = None):
    return strategy(strategy_key(cfg, key, day))[1]


def busy() -> bool:
    return _task is not None and not _task.done()


def _blank_totals() -> dict:
    return {"pnl": 0.0, "withdrawn": 0.0, "trades": 0, "wins": 0, "days": 0}


# ── replaying finished sessions ──────────────────────────────────────────────

async def process(notify: bool = False) -> list[str]:
    """Replay every finished session not replayed yet, oldest first, saving each day as it goes.
    Returns one Telegram-ready line per market-day replayed."""
    global _last_error
    _last_error = ""
    cfg = _config()
    if not cfg:
        return []
    lines: list[str] = []
    try:
        async with keepalive.awake():
            for key, m in MARKETS.items():
                done = cfg["progress"].get(key)
                newest = await newest_available(key, done)   # no request when nothing can be new
                first = (date.fromisoformat(done) + timedelta(days=1)).isoformat() if done else cfg["startDate"]
                if not newest or newest < first:
                    continue
                for day in weekdays(first, newest)[:MAX_DAYS_PER_RUN]:
                    pots = cfg["pots"][key]
                    res = await replay_day(key, day, pots, rules_for(cfg, key, day))
                    if res is not None:
                        lines.append(_save_day(cfg, key, day, res))
                    cfg["progress"][key] = day
                    _cfg_ref().set(cfg)
    except data.DataError as e:
        _last_error = str(e)
        log.warning("Trading Lab stopped: %s", e)
    except Exception as e:
        _last_error = f"{type(e).__name__}: {e}"
        log.exception("Trading Lab replay failed")
    if notify and lines:
        try:
            await telegram.send("📈 Trading Lab (paper money)\n" + "\n".join(lines))
        except Exception:
            log.exception("Couldn't send the Trading Lab update")
    try:
        await _swing_update(notify)
    except Exception:
        log.exception("US swing update failed")
    return lines


def _save_day(cfg: dict, key: str, day: str, res: dict) -> str:
    m = MARKETS[key]
    t = cfg["totals"][key]
    stocks, pnl, withdrawn, trades, wins = {}, 0.0, 0.0, 0, 0
    for s, r in res.items():
        stocks[s] = {"market": key, "potStart": r["potStart"], "potEnd": r["potEnd"], "pnl": r["pnl"],
                     "withdrawn": r["withdrawn"], "traded": r["trade"] is not None}
        cfg["pots"][key][s] = r["potEnd"]
        pnl += r["pnl"]
        withdrawn += r["withdrawn"]
        trades += r["trade"] is not None
        wins += r["pnl"] > 0
    t.update(pnl=round(t["pnl"] + pnl, 2), withdrawn=round(t["withdrawn"] + withdrawn, 2),
             trades=t["trades"] + trades, wins=t["wins"] + wins, days=t["days"] + 1)
    summary = {"currency": m.currency, "strategy": strategy_key(cfg, key, day), "pnl": round(pnl, 2), "withdrawn": round(withdrawn, 2), "trades": trades, "wins": wins,
               "pots": round(sum(cfg["pots"][key].values()), 2), "cumPnl": t["pnl"], "cumWithdrawn": t["withdrawn"]}
    col("tradinglab_days").document(day).set({"date": day, "markets": {key: summary}, "stocks": stocks}, merge=True)
    sym = "₹" if m.currency == "INR" else "$"
    return (f"{m.name} {day}: {trades} trade{'s' if trades != 1 else ''}, {wins} won, "
            f"day {'+' if pnl >= 0 else '−'}{sym}{abs(pnl):,.2f} · total {'+' if t['pnl'] >= 0 else '−'}{sym}{abs(t['pnl']):,.2f}")


def _kick(notify: bool = False) -> bool:
    global _task
    if busy():
        return False
    _task = asyncio.create_task(process(notify))
    return True


# ── routes ───────────────────────────────────────────────────────────────────

def _markets_view() -> dict:
    return {k: {"name": m.name, "currency": m.currency, "open": m.open, "close": m.close, "stocks": list(m.stocks)}
            for k, m in MARKETS.items()}


@router.get("", dependencies=[Depends(require_user)])
async def view() -> dict:
    cfg = _config()
    base = {"rules": RULES.as_dict(), "markets": _markets_view(), "configured": data.configured(),
            "defaultStart": (date.today() - timedelta(days=14)).isoformat(),
            "minStart": (date.today() - timedelta(days=MAX_START_DAYS)).isoformat(),
            "busy": busy(), "error": _last_error, "priceCallsToday": data.calls_today(),
            "lastClosed": {k: last_closed_session(k) for k in MARKETS}}
    if not cfg:
        return {**base, "started": False}
    days = sorted((d.to_dict() for d in col("tradinglab_days").stream()), key=lambda d: d["date"])
    names = {k: STRATEGIES[strategy_key(cfg, k)][0] for k in MARKETS}
    return {**base, "started": True, "config": cfg, "days": days, "strategy": names}


class StartIn(BaseModel):
    startDate: str


@router.post("/start", dependencies=[Depends(require_user)])
async def start(body: StartIn) -> dict:
    """Start (or start over) with 1,000 per stock from this date; finished sessions since then are replayed."""
    try:
        day = date.fromisoformat(body.startDate)
    except ValueError:
        raise HTTPException(400, "Pick a start date.")
    if day > date.today():
        raise HTTPException(400, "The start date can't be in the future.")
    if day < date.today() - timedelta(days=MAX_START_DAYS):
        raise HTTPException(400, f"Pick a start date within the last {MAX_START_DAYS} days (each trading day costs 10 price requests).")
    if busy():
        raise HTTPException(409, "The lab is replaying right now. Try again when it's done.")
    rows = col("tradinglab_days")
    while docs := list(rows.limit(400).select([]).stream()):
        batch = db().batch()
        for d in docs:
            batch.delete(d.reference)
        batch.commit()
    _cfg_ref().set({
        "version": VERSION, "startDate": day.isoformat(), "potPerStock": RULES.pot, "startedAt": now_utc().isoformat(),
        "pots": {k: {s: RULES.pot for s in m.stocks} for k, m in MARKETS.items()},
        "totals": {k: _blank_totals() for k in MARKETS}, "progress": {},
        "strategy": dict(DEFAULT_STRATEGY), "strategySince": {},
    })
    _kick()
    return await view()


@router.post("/refresh", dependencies=[Depends(require_user)])
async def refresh() -> dict:
    """Replay any session that has finished since the last run (the page's "Check for new days")."""
    if _config():
        _kick()
    return await view()


async def _replay(day: str) -> dict | None:
    """One day replayed: every stock's 1-minute candles, opening range and trade. A stored day replays from its
    pots; today, while a market is trading, replays the candles so far (the last live check's, so no new request).
    None if neither."""
    snap = col("tradinglab_days").document(day).get()
    if not snap.exists:
        return await _replay_live(day)
    rec = snap.to_dict()
    stocks = rec.get("stocks", {})
    used = {k: strategy(md.get("strategy"))[1] for k, md in rec.get("markets", {}).items()}   # the rules that day ran
    bench: dict[str, list[dict] | None] = {}
    for k, r in used.items():
        if r.market_up:
            try:
                bench[k] = await data.day(MARKETS[k].benchmark, day)
            except data.DataError:
                bench[k] = None

    async def one(symbol: str, saved: dict) -> dict:
        key = saved["market"]
        try:
            candles = await data.day(symbol, day)
        except data.DataError as e:
            return {"symbol": symbol, "market": key, "error": str(e)}
        r = simulate_day(key, candles, saved["potStart"], used.get(key, RULES), bench=bench.get(key))
        return {"symbol": symbol, "market": key, "currency": MARKETS[key].currency, "candles": candles_every(candles, 1),
                "range": r["range"], "trade": r["trade"], "note": r["note"], "pnl": r["pnl"], "potStart": r["potStart"]}

    order = [s for m in MARKETS.values() for s in m.stocks if s in stocks]
    return {"date": day, "stocks": await asyncio.gather(*(one(s, stocks[s]) for s in order))}


async def _replay_live(day: str, only: str | None = None) -> dict | None:
    """Today while trading, from the candles the live checks already fetched. `only`: just that stock."""
    cfg = _config()
    keys = [k for k in MARKETS if live.session_date(k) == day and (_live_state(k) or {}).get("day") == day
            and (not only or only in MARKETS[k].stocks)]
    if not cfg or not keys:
        return None

    async def one(symbol: str, key: str) -> dict:
        candles = live.candles_today(symbol)
        if candles is None:   # the server restarted since the last check: fetch once and keep them
            try:
                candles = await data.day(symbol, day, finished=False)
                live.remember(symbol, candles)
            except data.DataError as e:
                return {"symbol": symbol, "market": key, "error": str(e)}
        pot = cfg["pots"][key].get(symbol, RULES.pot)
        rules = rules_for(cfg, key)
        r = simulate_day(key, candles, pot, rules, live=True, bench=live.candles_today(MARKETS[key].benchmark) if rules.market_up else None)
        return {"symbol": symbol, "market": key, "currency": MARKETS[key].currency, "candles": candles_every(candles, 1),
                "range": r["range"], "trade": r["trade"], "note": r["note"], "pnl": r["pnl"], "potStart": pot,
                "state": r["state"], "live": True}

    return {"date": day, "live": True,
            "stocks": await asyncio.gather(*(one(s, k) for k in keys for s in MARKETS[k].stocks if not only or s == only))}


# ── US swing strategy and the buy-and-hold yardstick ────────────────────────

_extras: dict = {"at": 0.0, "value": None}
EXTRAS_FRESH_S = 600


async def extras(cfg: dict, fresh: bool = False) -> dict:
    """The US swing strategy's state and buy-and-hold per market since the lab's start. Daily candles:
    11 requests at most, reused for hours; a session still trading today is left out."""
    if not fresh and _extras["value"] and time.monotonic() - _extras["at"] < EXTRAS_FRESH_S:
        return _extras["value"]
    unfinished = {k: live.session_date(k) if live.is_open(k) else None for k in MARKETS}
    try:
        sw = await swing.lab_state(cfg.get("swingStart") or cfg["startDate"], unfinished=unfinished["US"])
        hold = {k: await swing.hold_since(k, cfg["startDate"], unfinished=unfinished[k]) for k in MARKETS}
        value = {"swing": sw, "hold": hold}
    except Exception as e:
        log.warning("Couldn't build the swing strategy / yardstick: %s", e)
        value = {"error": f"Daily prices unavailable just now ({type(e).__name__})"}
    _extras.update(at=time.monotonic(), value=value)
    return value


async def _swing_update(notify: bool) -> None:
    """After a session: save the swing strategy's P&L for its latest day, and tell Telegram about its
    buys, sells and next-open buys once per day."""
    cfg = _config()
    if not cfg:
        return
    ex = await extras(cfg, fresh=True)
    sw = ex.get("swing")
    if not sw or not sw.get("asOf"):
        return
    day = sw["asOf"]
    col("tradinglab_swing").document(day).set({"date": day, "realised": sw["realised"], "unrealised": sw["unrealised"],
                                                 "total": sw["total"], "trades": sw["trades"], "wins": sw["wins"], "open": len(sw["held"])})
    meta_ref = col("tradinglab").document("swing_meta")
    meta = (meta_ref.get().to_dict() or {}) if meta_ref.get().exists else {}
    lines = []
    if meta.get("notified") != day:
        for t in sw["closed"]:
            if t["sell"] == day:
                lines.append(f"{'✅' if t['pnl'] > 0 else '🔻'} Swing: sold {t['symbol']} ({t['why']}), {_cur('USD', t['pnl'], True)}")
        for h in sw["held"]:
            if h["buy"] == day:
                lines.append(f"🟢 Swing: bought {h['symbol']} at ${h['buyPrice']:,.2f}; target ${h['target']:,.2f}, stop ${h['stop']:,.2f}")
        for s in sw["buyNext"]:
            lines.append(f"👀 Swing: {s} closed above its 20-day high with SPY up; buying at the next open")
    meta_ref.set({"notified": day, "summary": {
        "asOf": day, "total": sw["total"], "realised": sw["realised"], "unrealised": sw["unrealised"], "trades": sw["trades"], "wins": sw["wins"],
        "held": [{k: h[k] for k in ("symbol", "buy", "buyPrice", "last", "pnl", "target", "stop", "daysHeld")} for h in sw["held"]],
        "buyNext": sw["buyNext"], "hold": {k: {"pnl": v["pnl"], "pnlPct": v["pnlPct"]} for k, v in ex.get("hold", {}).items()}}})
    if notify and lines:
        try:
            await telegram.send("📈 Trading Lab, US swing (paper money)\n" + "\n".join(lines))
        except Exception:
            log.exception("Couldn't send the swing update")


@router.get("/extras", dependencies=[Depends(require_user)])
async def extras_view() -> dict:
    cfg = _config()
    return await extras(cfg) if cfg else {}


def swing_text() -> str:
    snap = col("tradinglab").document("swing_meta").get()
    if not snap.exists:
        return "The US swing strategy hasn't run yet; it updates after each US session (or say 'lab check')."
    s = snap.to_dict()["summary"]
    lines = [f"US SWING STRATEGY (paper, $1,000 a trade, rule A: 20-day breakout while SPY is above its 50-day average; "
             f"+5% / −3% / 10 days), up to {s['asOf']}: total {_cur('USD', s['total'], True)} "
             f"({s['trades']} closed trades, {s['wins']} won; open positions {_cur('USD', s['unrealised'], True)})."]
    for h in s["held"]:
        lines.append(f"- Holding {h['symbol']} since {h['buy']} at ${h['buyPrice']:,.2f}, now ${h['last']:,.2f} ({_cur('USD', h['pnl'], True)}); "
                     f"target ${h['target']:,.2f}, stop ${h['stop']:,.2f}, day {h['daysHeld']} of 10")
    if s["buyNext"]:
        lines.append("- Buying at the next open: " + ", ".join(s["buyNext"]))
    for k, h in s.get("hold", {}).items():
        lines.append(f"- Yardstick, buy and hold {MARKETS[k].name}'s 5 stocks since the start: {_cur(MARKETS[k].currency, h['pnl'], True)} ({h['pnlPct']:+.2f}%)")
    return "\n".join(lines)


# ── live paper trading during market hours ───────────────────────────────────

def _live_ref(key: str):
    return col("tradinglab").document(f"live_{key}")


def _live_state(key: str) -> dict | None:
    snap = _live_ref(key).get()
    return snap.to_dict() if snap.exists else None


_last_live = 0.0   # when the last all-stocks check ran (monotonic), so opening the page can't add to the cron's
PAGE_CHECK_AFTER_S = 240


@router.post("/live", dependencies=[Depends(require_cron)])
async def live_tick() -> dict:
    """Cron, every 5 minutes on weekdays. Checks only markets that are open right now; just after a close
    it saves that session's money. Outside trading hours it returns without asking FMP for anything."""
    return await _live_tick()


@router.post("/live/check", dependencies=[Depends(require_user)])
async def live_check_now() -> dict:
    """The page opened during market hours: check all stocks now unless that ran in the last 4 minutes.
    Only open markets, so never outside trading hours."""
    if time.monotonic() - _last_live < PAGE_CHECK_AFTER_S or not any(live.is_open(k) for k in MARKETS):
        return await live_view()
    await _live_tick()
    return await live_view()


async def _live_tick() -> dict:
    global _last_live
    _last_live = time.monotonic()
    cfg = _config()
    if not cfg:
        return {"ok": True, "lab": "not started"}
    out, lines = {}, []
    for key, m in MARKETS.items():
        if live.is_open(key):
            state, said = await live.check(key, _live_state(key) or {}, cfg["pots"][key], rules_for(cfg, key))
            _live_ref(key).set(state)
            lines += said
            out[key] = "holiday" if state.get("holiday") else f"checked {state.get('checkedAt', '')}"
        elif (cfg["progress"].get(key) or "") < last_closed_session(key) and live.market_now(key).weekday() < 5 \
                and live.market_now(key).strftime("%H:%M") >= m.close:
            out[key] = "closed: saving today" if _kick(notify=True) else "closed: already saving"
        else:
            out[key] = "closed"
    if lines:
        try:
            await telegram.send("📈 Trading Lab, live (paper money)\n" + "\n".join(lines))
        except Exception:
            log.exception("Couldn't send the Trading Lab live update")
    return {"ok": True, **out}


@router.post("/live/stock/{symbol}", dependencies=[Depends(require_user)])
async def live_stock(symbol: str) -> dict:
    """The stock on screen, refreshed every minute while the page is open: one request for this one stock,
    at most once every 55 seconds, and only while its market is open. Returns its chart data and tile."""
    symbol = symbol.upper()
    key = next((k for k, m in MARKETS.items() if symbol in m.stocks), None)
    cfg = _config()
    if not key or not cfg:
        raise HTTPException(404, "That stock isn't in the lab.")
    state = _live_state(key) or {}
    if live.is_open(key):
        state, lines, fetched = await live.check_one(key, symbol, state, cfg["pots"][key].get(symbol, RULES.pot), rules_for(cfg, key))
        if fetched:
            _live_ref(key).set(state)
        if lines:
            try:
                await telegram.send("📈 Trading Lab, live (paper money)\n" + "\n".join(lines))
            except Exception:
                log.exception("Couldn't send the Trading Lab live update")
    day = live.session_date(key)
    out = await _replay_live(day, only=symbol)
    stock = next((s for s in (out or {}).get("stocks", []) if s["symbol"] == symbol), None)
    return {"stock": stock, "tile": (state.get("stocks") or {}).get(symbol), "checkedAt": state.get("checkedAt"),
            "open": live.is_open(key)}


@router.get("/backtest", dependencies=[Depends(require_user)])
async def backtest_view() -> dict:
    """The last strategy-tester comparison published from the laptop (python -m tradinglab.backtest --publish)."""
    snap = col("tradinglab").document("backtest").get()
    return {"result": snap.to_dict() if snap.exists else None}


def backtest_text() -> str:
    """The strategy tester's comparison in sentences, for Jarvis."""
    snap = col("tradinglab").document("backtest").get()
    if not snap.exists:
        return "The strategy tester hasn't been run yet (it runs on the laptop: python -m tradinglab.backtest --publish)."
    res = snap.to_dict()
    lines = [f"STRATEGY TEST ({res['from']} to {res['to']}, fixed 1,000 a trade, after charges; "
             "'both' = better than the current rules in the first and the last part of the period):"]
    for k, m in MARKETS.items():
        rows = sorted(res["variants"], key=lambda r: -r["markets"][k]["all"]["pnl"])
        cur = next(r for r in res["variants"] if r["key"] == "current")["markets"][k]["all"]
        lines.append(f"- {m.name}: current rules {_cur(m.currency, cur['pnl'], True)} over {cur['trades']} trades ({cur['winRate']:.0f}% won). "
                     "Best: " + "; ".join(f"{r['name']} {_cur(m.currency, r['markets'][k]['all']['pnl'], True)}"
                                          f"{' (both)' if r['markets'][k]['beatsCurrentInBoth'] else ''}" for r in rows[:4]))
        best = next(r for r in res["variants"] if r["key"] == res["best"][k])
        lines.append(f"  Recommended for {m.name}: {best['name']}: {best['about']}.")
    return "\n".join(lines)


@router.get("/live", dependencies=[Depends(require_user)])
async def live_view() -> dict:
    """What's happening now, from the last check: no request to FMP, two small reads."""
    out = {}
    for key, m in MARKETS.items():
        state = _live_state(key) or {}
        today = live.session_date(key)
        out[key] = {"open": live.is_open(key), "nextOpen": live.next_open(key), "day": today,
                    "state": state if state.get("day") == today else None}
    return {"markets": out}


@router.get("/day/{day}", dependencies=[Depends(require_user)])
async def day_view(day: str) -> dict:
    """One day replayed for the chart (1-minute candles; the page groups them into 5 or 15 minutes)."""
    out = await _replay(day)
    if out is None:
        raise HTTPException(404, "That day hasn't been replayed.")
    return out


# ── for Jarvis's chat, Telegram and voice ───────────────────────────────────

def _cur(currency: str, v: float, signed: bool = False) -> str:
    sym = "₹" if currency == "INR" else "$"
    sign = ("+" if v > 0 else "−" if v < 0 else "") if signed else ("−" if v < 0 else "")
    return f"{sign}{sym}{abs(v):,.2f}"


def briefing() -> str:
    """A few lines about the lab for Jarvis's DATA block (chat and voice)."""
    cfg = _config()
    if not cfg:
        return "TRADING LAB (paper money): not started. The admin starts it on the Trading Lab page."
    days = sorted((d.to_dict() for d in col("tradinglab_days").stream()), key=lambda d: d["date"])
    lines = [f"TRADING LAB (paper money, day trading 10 stocks with 1,000 each in their own currency; started {cfg['startDate']}):"]
    lines.append("- Rules now: " + "; ".join(f"{m.name}: {STRATEGIES[strategy_key(cfg, k)][0]}" for k, m in MARKETS.items()))
    for k, m in MARKETS.items():
        t, pots = cfg["totals"][k], cfg["pots"][k]
        start = RULES.pot * len(m.stocks)
        lines.append(f"- {m.name}: total {_cur(m.currency, sum(pots.values()) + t['withdrawn'])} on {_cur(m.currency, start)}, "
                     f"P&L {_cur(m.currency, t['pnl'], True)}, withdrawn {_cur(m.currency, t['withdrawn'])}, "
                     f"{t['trades']} trades, {t['wins']} won, replayed up to {cfg['progress'].get(k, 'nothing yet')}")
    for d in days[-5:]:
        parts = []
        for k, md in sorted(d.get("markets", {}).items()):
            winners = [s for s, r in d["stocks"].items() if r["market"] == k and r["traded"]]
            parts.append(f"{MARKETS[k].name} {_cur(md['currency'], md['pnl'], True)} ({md['trades']} trades: "
                         + (", ".join(f"{s} {_cur(md['currency'], d['stocks'][s]['pnl'], True)}" for s in winners) or "none") + ")")
        lines.append(f"- {d['date']}: " + "; ".join(parts))
    for k, m in MARKETS.items():   # what's happening right now, from the last live check (no request)
        st = _live_state(k) or {}
        if live.is_open(k) and st.get("day") == live.session_date(k) and st.get("stocks"):
            now = "; ".join(f"{s} {r['state'].replace('_', ' ')}" + (f" {_cur(m.currency, r['pnl'], True)}" if r["trade"] else "")
                            for s, r in st["stocks"].items())
            lines.append(f"- LIVE NOW, {m.name} (checked {st.get('checkedAt')} exchange time): {now}")
        elif live.is_open(k) and st.get("holiday"):
            lines.append(f"- LIVE NOW, {m.name}: market holiday today")
    if col("tradinglab").document("swing_meta").get().exists:
        lines.append(swing_text().replace("\n", "\n  "))
    if col("tradinglab").document("backtest").get().exists:
        lines.append("A strategy test comparing smarter rules exists: use the command 'lab test' for it.")
    lines.append("For trade times and reasons on a day, use the command 'lab day <YYYY-MM-DD> [stock]' (today works while trading).")
    return "\n".join(lines)


def status_text() -> str:
    return briefing().replace("For trade times", "\nSay \"lab day <date> <stock>\" for trade times")


def check_text() -> str:
    if not _config():
        return "The Trading Lab isn't started yet. Start it on the Trading Lab page."
    return ("📈 Checking for finished sessions now; the page and \"lab status\" show them in a few seconds."
            if _kick() else "📈 The lab is already replaying; give it a few seconds.")


async def day_text(day: str | None, symbol: str | None = None) -> str:
    """Every trade on one day (or one stock's), in sentences Jarvis can read or say."""
    cfg = _config()
    if not cfg:
        return "The Trading Lab isn't started yet."
    if not day:
        days = sorted(d.id for d in col("tradinglab_days").select([]).stream())
        if not days:
            return "No sessions have been replayed yet."
        day = days[-1]
    out = await _replay(day)
    if out is None:
        return f"{day} wasn't replayed (a weekend, a holiday, or before the start date)."
    rows = [s for s in out["stocks"] if not symbol or s["symbol"].upper() == symbol.upper()]
    if not rows:
        return f"No {symbol.upper()} on {day}. The stocks are " + ", ".join(s for m in MARKETS.values() for s in m.stocks) + "."
    lines = [f"Trading Lab, {day}" + (" (live, trading now; prices from the last check):" if out.get("live") else ":")]
    for s in rows:
        if s.get("error"):
            lines.append(f"- {s['symbol']}: prices unavailable ({s['error']})")
        elif s["trade"] and s["trade"].get("open"):   # today, still held
            t, c = s["trade"], s["currency"]
            lines.append(f"- {s['symbol']}: HOLDING. Bought {t['buyTime']} at {t['buyPrice']:,.2f} ({t['reason']}); "
                         f"now {t['last']:,.2f} at {t['lastTime']}, {_cur(c, t['pnl'], True)} so far ({t['pnlPct']:+.2f}%); "
                         f"sells if it falls to {t['stop']:,.2f}{' (trailing stop)' if t.get('trailing') else ''} or at the close")
        elif s["trade"]:
            t, c = s["trade"], s["currency"]
            lines.append(f"- {s['symbol']}: bought {t['buyTime']} at {t['buyPrice']:,.2f} ({t['reason']}); "
                         f"sold {t['sellTime']} at {t['sellPrice']:,.2f} ({t['exit']}); {_cur(c, t['pnl'], True)} ({t['pnlPct']:+.2f}%)")
        else:
            last = s["candles"][-1] if s.get("candles") else None
            now = f" Price now {last['close']:,.2f} at {last['time']}." if s.get("live") and last else ""
            lines.append(f"- {s['symbol']}: no trade yet. {s['note']}.{now}" if s.get("live") else f"- {s['symbol']}: no trade. {s['note']}.")
    return "\n".join(lines)


@router.post("/job", dependencies=[Depends(require_cron)])
async def job() -> dict:
    """Cron, 8 AM IST Tue–Sat: replay the sessions that finished overnight and report on Telegram."""
    if not _config():
        return {"ok": True, "lab": "not started"}
    return {"ok": True, "started": _kick(notify=True)}
