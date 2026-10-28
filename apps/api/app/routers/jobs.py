"""
Scheduled jobs. Called by the Cloudflare cron worker with X-Cron-Secret.
You can also trigger them by hand with curl while developing.
"""

from collections import Counter
from datetime import datetime, time

from fastapi import APIRouter, Depends

from ..config import get_settings
from ..deps import require_cron
from ..timeutil import now_local
from ..services import activity, inbox, leads, telegram

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(require_cron)])


@router.post("/check-replies")
async def check_replies():
    """Called every 30 minutes in the day; also keeps the free Render instance awake."""
    return {"ok": True, "newReplies": await inbox.check()}


@router.post("/daily-report")
async def daily_report():
    start = datetime.combine(now_local().date(), time.min, tzinfo=get_settings().tz)
    today = activity.since(start.isoformat())
    by_type = Counter(a["type"] for a in today)
    interested = leads.by_status("interested", 10)

    lines = [
        "🌙 Jarvis daily report",
        f"Leads found: {by_type['lead_found']}",
        f"Emails sent: {by_type['email_sent']}",
        f"Replies: {by_type['reply']}",
    ]
    if interested:
        lines.append("Interested: " + ", ".join(l["name"] for l in interested))
    text = "\n".join(lines)
    await telegram.send(text)
    return {"ok": True, "report": text}
