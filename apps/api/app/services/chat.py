"""
Talk to Jarvis from Telegram or the dashboard. Jarvis answers from live data
and can act: send emails, send follow-ups, or scan a place for hotels.
"""

import asyncio
import json
import logging
from datetime import timedelta

from firebase_admin import firestore

from ..config import get_settings
from ..firebase import col
from ..timeutil import now_local, now_utc
from . import activity, inbox, leads, llm, outreach, presqio, telegram

log = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()   # keep background scans alive

SYSTEM = """You are Jarvis, the sales assistant for Presqio. You find hotels, email them about Presqio,
track replies and report to the admin (the Presqio owner) you are talking to.

Reply with a JSON object only:
{{"reply": "<what you say to the admin>", "action": null}}
or, when the admin clearly asks you to do something, one of these actions:
{{"reply": "...", "action": {{"name": "send_emails", "count": <1-50>, "area": "<locality only, e.g. Madhapur, or null>"}}}}
{{"reply": "...", "action": {{"name": "send_follow_ups"}}}}
{{"reply": "...", "action": {{"name": "check_replies"}}}}
{{"reply": "...", "action": {{"name": "scan", "place": "<city, or area and city>", "radius_km": <number or null for a whole city>}}}}

Rules:
- Only act when asked. If they ask to send emails without saying how many, ask how many (action null).
- When they say how many to send, always start send_emails, even if the data suggests fewer leads are left:
  the sending job checks and reports exactly what it sent. Don't ask for confirmation.
- The same for send_follow_ups and check_replies: just start them.
- Never more than 50 emails per request.
- Answer questions from the DATA below; never invent hotels, numbers or replies. If the data doesn't have it, say so.
- Keep replies short: 1-4 sentences, or a short list. Plain text, no markdown tables.
- If asked about Presqio itself, use only the PRODUCT FACTS.

PRODUCT FACTS:
{facts}

Current local time: {now}
"""


def context_block() -> str:
    s = get_settings()
    counts = leads.status_counts()
    pipeline = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "no leads yet"
    areas = sorted(leads.areas(), key=lambda a: -a["total"])[:30]
    area_lines = "\n".join(
        f"- {a['area']} ({a['city']}): {a['total']} hotels, {a['withEmail']} with email, {a['withPhone']} with phone, "
        f"emailed {a['statuses'].get('emailed', 0)}, replied {a['statuses'].get('replied', 0)}, interested {a['statuses'].get('interested', 0)}"
        for a in areas
    ) or "- none yet"
    hot = leads.by_status("interested", 10) + leads.by_status("replied", 10)
    hot_lines = "\n".join(f"- {l['name']} ({l.get('area', '?')}): {l['status']}" for l in hot) or "- none"
    recent = activity.since((now_utc() - timedelta(hours=48)).isoformat())[-30:]
    recent_lines = "\n".join(f"- {a['at'][:16].replace('T', ' ')} UTC: {a['text']}" for a in recent) or "- nothing yet"
    camps = col("campaigns").order_by("createdAt", direction=firestore.Query.DESCENDING).limit(5).stream()
    camp_lines = "\n".join(
        f"- {c.get('name')}: {c.get('status')}, {c.get('scan', {}).get('found', c['stats']['found'])} hotels found"
        for c in (d.to_dict() for d in camps)
    ) or "- none"
    return (
        f"PIPELINE (all areas): {pipeline}\n"
        f"EMAILS TODAY: {outreach.sent_today()} of {s.daily_email_cap} daily limit; "
        f"follow-ups due now: {len(outreach.due_follow_ups(100))}; sending right now: {'yes' if outreach.busy() else 'no'}\n\n"
        f"AREAS (biggest first):\n{area_lines}\n\n"
        f"NEEDS ATTENTION:\n{hot_lines}\n\n"
        f"SCANS:\n{camp_lines}\n\n"
        f"LAST 48 HOURS:\n{recent_lines}"
    )


def recent_history(limit: int = 10) -> list[dict]:
    docs = col("chats").order_by("createdAt", direction=firestore.Query.DESCENDING).limit(limit).stream()
    msgs = [d.to_dict() for d in docs][::-1]
    return [{"role": m["role"], "content": m["text"]} for m in msgs]


def save(role: str, text: str, channel: str) -> None:
    col("chats").add({"role": role, "text": text, "channel": channel, "createdAt": now_utc().isoformat()})


async def handle(text: str, channel: str) -> tuple[str, bool]:
    """-> (reply, started_a_job). A started job reports its own progress on Telegram."""
    history = recent_history()
    save("user", text, channel)
    system = SYSTEM.format(facts=presqio.FACTS, now=now_local().strftime("%A %d %b %Y, %H:%M"))
    messages = [*history, {"role": "user", "content": f"DATA:\n{context_block()}\n\nADMIN: {text}"}]
    raw = await llm.complete(system, messages, max_tokens=1200, json=True)
    try:
        out = json.loads(raw)
        reply, action = str(out.get("reply", "")).strip(), out.get("action")
    except (json.JSONDecodeError, AttributeError):
        reply, action = raw, None

    started = False
    if isinstance(action, dict):
        started, note = run_action(action)
        if note:
            reply = note
    save("assistant", reply, channel)
    return reply, started


def run_action(action: dict) -> tuple[bool, str]:
    """-> (started, message to show instead of the model's reply, or "")."""
    name = action.get("name")
    if name in ("send_emails", "send_follow_ups") and outreach.busy():
        return False, "I'm still sending the previous batch. I'll report when it's done."
    if name == "send_emails":
        count = max(1, min(int(action.get("count") or 0) or 1, 50))
        area = action.get("area") or None
        return outreach.start(outreach.send_first_emails(count, area)), ""
    if name == "send_follow_ups":
        return outreach.start(outreach.send_follow_ups()), ""
    if name == "check_replies":
        task = asyncio.create_task(_check_replies())
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        return True, "📥 Checking the inbox for replies…"
    if name == "scan":
        place = str(action.get("place", "")).strip()
        if not place:
            return False, "Which city or area should I scan?"
        radius = action.get("radius_km")
        campaign_id = leads.create_campaign(place, int(float(radius) * 1000) if radius else None)
        task = asyncio.create_task(leads.run_campaign(campaign_id))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        return False, f"🔎 Scanning {place} for hotels. This can take a while; I'll message you when it's done."
    return False, ""


async def _check_replies() -> None:
    n = await inbox.check()
    await telegram.send("No new replies." if n == 0 else f"Done: {n} new replies (details above).")


async def on_telegram(text: str) -> None:
    """Called for each message the admin sends the bot."""
    try:
        await telegram.typing()
        reply, started = await handle(text, "telegram")
    except Exception:
        log.exception("Telegram message failed")
        reply, started = "Sorry, something went wrong answering that. Try again in a minute.", False
    if not started and reply:
        await telegram.send(reply)
