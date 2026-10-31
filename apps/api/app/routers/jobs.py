"""
Scheduled jobs. Called by the Cloudflare cron worker with X-Cron-Secret.
You can also trigger them by hand with curl while developing.
"""

from fastapi import APIRouter, Depends

from ..deps import require_cron
from ..services import chat, explore, health, inbox, outreach, report

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(require_cron)])


@router.post("/tick")
async def tick():
    """Cron, every 30 min in the day: start an automatic batch if it's sending time,
    otherwise just check replies. Also keeps the free Render instance awake."""
    health.record_run("tick")         # so Settings can tell if the schedule stopped
    await explore.morning_summary()   # last night's explorer results, once
    chat.prune_history()              # chat history is kept for 24 hours
    status = outreach.auto_send()
    replies = 0 if status == "started" else await inbox.check()   # a batch checks replies itself
    return {"ok": True, "autoSend": status, "newReplies": replies}


@router.post("/explore")
async def explore_tick():
    """Cron, every 30 min from 12:30 to 5:00 AM IST: explore one more area if tonight's budget allows."""
    health.record_run("explore")
    return {"ok": True, "explore": explore.tick()}


@router.post("/check-replies")
async def check_replies():
    return {"ok": True, "newReplies": await inbox.check()}


@router.post("/daily-report")
async def daily_report():
    health.record_run("report")
    return {"ok": True, "report": await report.send_daily()}
