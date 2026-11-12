"""
What Jarvis's on-screen character presents during a voice call: a "display" (plain data the page draws as
stat tiles, charts and a list) plus the facts as text, which Jarvis talks through.

Topics: "overview" (today's outreach and the lab in one view), "trading_lab", "lab_day" (one session,
optionally one stock with its price line).
"""

import asyncio
import logging
import time

from . import leads, outreach, prefs, report
from ..timeutil import now_local

log = logging.getLogger(__name__)

PIPELINE = [("new", "New"), ("ready", "Approved"), ("emailed", "Emailed"), ("replied", "Replied"),
            ("interested", "Interested"), ("not_interested", "Not interested")]
FRESH_SECONDS = 60   # the overview costs a few database reads; asking twice in a minute reuses it
_overview: tuple[float, dict] | None = None


def _overview_now() -> dict:
    r = report.gather()
    counts = leads.status_counts()
    rep = r["replies"]
    sent = r["first"] + r["followUps"]
    stats = [
        {"label": "Emails today", "value": f"{sent}", "note": f"{r['first']} new · {r['followUps']} follow-ups · limit {prefs.sending()['dailyCap']}"},
        {"label": "Replies today", "value": f"{sum(rep.values())}", "tone": "up" if rep.get("interested") else None,
         "note": f"{rep.get('interested', 0)} interested" + (f" · {r['bounced']} bounced" if r["bounced"] else "")},
        {"label": "Waiting for a reply", "value": f"{r['awaiting']:,}"},
        {"label": "Still to contact", "value": f"{r['left']:,}", "note": f"{r['dueTomorrow']} follow-ups due by tomorrow"},
        {"label": "Auto-send", "value": "ON" if r["auto"] else "PAUSED", "tone": "up" if r["auto"] else "down",
         "note": outreach.auto_window() if r["auto"] else "say “resume auto”"},
    ]
    try:
        from tradinglab.jarvis_api import lab_display   # the lab lives in its own folder
        lab = lab_display()
        if lab:
            stats += [st for st in lab["stats"] if st["label"].endswith("P&L")]
    except Exception:
        log.exception("Couldn't read the Trading Lab for the overview")
    display = {
        "title": "Today at a glance", "subtitle": now_local().strftime("%A %d %b"),
        "stats": stats,
        "charts": [{"type": "bars", "title": "Businesses by stage",
                    "items": [{"label": label, "value": counts.get(k, 0), "text": f"{counts.get(k, 0):,}"} for k, label in PIPELINE]}],
        "rows": {"title": "Interested", "items": [{"label": n} for n in r["hot"]]} if r["hot"] else None,
    }
    spoken = report.spoken(r).replace("Good evening. Here is today's Presqio outreach report. ", "Today's outreach so far. ")
    return {"display": display, "result": spoken}   # the spoken report already covers the lab


async def build(topic: str, date: str | None = None, symbol: str | None = None) -> dict:
    """-> {"display": ... or None, "result": text for Jarvis to speak from}."""
    global _overview
    if topic == "overview":
        if not (_overview and time.monotonic() - _overview[0] < FRESH_SECONDS):
            _overview = (time.monotonic(), await asyncio.to_thread(_overview_now))
        return _overview[1]
    from tradinglab import jarvis_api as lab
    if topic == "trading_lab":
        return {"display": await asyncio.to_thread(lab.lab_display), "result": await asyncio.to_thread(lab.briefing)}
    if topic == "lab_day":
        from .chat import _lab_date
        day = _lab_date(date)
        sym = None if str(symbol or "").lower() in ("", "none", "null") else symbol
        display = await lab.day_display(day, sym)   # one after the other: the second reuses the prices the first fetched
        text = await lab.day_text(day, sym)
        return {"display": display, "result": text}
    return {"display": None, "result": f"I can show: overview, trading_lab or lab_day, not {topic!r}."}
