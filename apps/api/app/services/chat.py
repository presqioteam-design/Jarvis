"""
Talk to Jarvis from Telegram or the dashboard. Jarvis answers from live data
and can act: send emails, send follow-ups, or scan a place for hotels.
"""

import asyncio
import json
import logging
import re
from datetime import timedelta

from firebase_admin import firestore
from google.api_core.exceptions import ResourceExhausted

from ..config import get_settings
from ..firebase import col
from ..timeutil import now_local, now_utc
from . import activity, explore, inbox, leads, llm, outreach, presqio, report, telegram, usage, voice

log = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()   # keep background scans alive
STATUS_WORDS = {"new": "Waiting for review", "ready": "Approved", "emailed": "Emailed", "replied": "Replied",
                "interested": "Interested", "no_contact": "No contact details"}
QUOTA_MESSAGE = (
    "⚠️ I can't read the database right now: today's free Firestore reads are used up. "
    "They reset at midnight US Pacific time (about 12:30 PM IST). Sending and answering will work again then."
)

SYSTEM = """You are Jarvis, the sales assistant for Presqio. You find hotels, email them about Presqio,
track replies and report to the admin (the Presqio owner) you are talking to.

Reply with a JSON object only:
{{"reply": "<what you say to the admin>", "action": null}}
or, when the admin clearly asks you to do something, one of these actions:
{{"reply": "...", "action": {{"name": "send_emails", "count": <1-50>, "area": "<locality only, e.g. Madhapur, or null>"}}}}
{{"reply": "...", "action": {{"name": "send_follow_ups"}}}}
{{"reply": "...", "action": {{"name": "check_replies"}}}}
{{"reply": "...", "action": {{"name": "auto", "on": true|false}}}}   (turn automatic sending on or off)
{{"reply": "...", "action": {{"name": "report"}}}}   (today's report now)
{{"reply": "...", "action": {{"name": "explore_status"}}}}   (how the night explorer is doing)
{{"reply": "...", "action": {{"name": "list_leads", "area": "<locality or null>", "status": "new|ready|emailed|replied|interested|no_contact"}}}}
{{"reply": "...", "action": {{"name": "approve", "numbers": [<numbers from the last list>]}}}}
{{"reply": "...", "action": {{"name": "approve_all", "area": "<locality or null for the whole city>"}}}}
{{"reply": "...", "action": {{"name": "block", "numbers": [<numbers from the last list>]}}}}
{{"reply": "...", "action": {{"name": "scan", "place": "<city, or area and city>", "radius_km": <number or null for a whole city>}}}}

Rules:
- Only act when asked. If they ask to send emails without saying how many, ask how many (action null).
- When they say how many to send, always start send_emails, even if the data suggests fewer leads are left:
  the sending job checks and reports exactly what it sent. Don't ask for confirmation.
- The same for send_follow_ups and check_replies: just start them.
- "show / list leads (in X)" -> list_leads. status "new" means waiting for review (the default), "ready" means approved.
- "approve 1 3 5" or "block 2" refer to the numbers in the LAST LIST below. "approve all (with email) in X" -> approve_all.
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
    all_areas = leads.areas()
    areas = sorted(all_areas, key=lambda a: -a["total"])[:30]
    most_email = ", ".join(f"{a['area']} {a['withEmail']}" for a in sorted(all_areas, key=lambda a: -a["withEmail"])[:10] if a["withEmail"]) or "none"
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
        f"follow-ups due now: {len(outreach.due_follow_ups(100))}; sending right now: {'yes' if outreach.busy() else 'no'}\n"
        f"AUTO-SEND: {'on' if outreach.auto_enabled() else 'paused'} ({outreach.auto_window()})\n"
        f"GEMINI USAGE TODAY: {usage.summary()}\n"
        f"NIGHT EXPLORER: {explore.status().replace(chr(10), ' ')}\n\n"
        f"MOST EMAILS (sorted): {most_email}\n\n"
        f"AREAS (biggest first):\n{area_lines}\n\n"
        f"NEEDS ATTENTION:\n{hot_lines}\n\n"
        f"SCANS:\n{camp_lines}\n\n"
        f"LAST 48 HOURS:\n{recent_lines}\n\n"
        f"LAST LIST SHOWN: " + (", ".join(f"{i}. {r['name']}" for i, r in enumerate(_last_list, 1)) or "none")
    )


_last_list: list[dict] = []   # the numbered list last shown, so "approve 2" knows which hotel


def show(rows: list[dict], title: str) -> str:
    global _last_list
    _last_list = [{"id": r["id"], "name": r["name"]} for r in rows]
    if not rows:
        return f"{title}: none."
    lines = [f"{title}:"]
    for i, r in enumerate(rows, 1):
        contact = " · ".join(x for x in (r["emails"][0] if r.get("emails") else "", r.get("phone", "")) if x) or "no contact"
        lines.append(f"{i}. {r['name']} ({r.get('area', '?')}) — {contact}")
    lines.append("\nReply e.g. \"approve 1 3\", \"block 2\" or \"approve all with email in <area>\".")
    return "\n".join(lines)


def picked(numbers) -> list[dict]:
    out = []
    for n in numbers or []:
        try:
            i = int(n)
        except (TypeError, ValueError):
            continue
        if 0 < i <= len(_last_list) and _last_list[i - 1] not in out:
            out.append(_last_list[i - 1])
    return out


def recent_history(limit: int = 10) -> list[dict]:
    docs = col("chats").order_by("createdAt", direction=firestore.Query.DESCENDING).limit(limit).stream()
    msgs = [d.to_dict() for d in docs][::-1]
    return [{"role": m["role"], "content": m["text"]} for m in msgs]


def save(role: str, text: str, channel: str) -> None:
    col("chats").add({"role": role, "text": text, "channel": channel, "createdAt": now_utc().isoformat()})


HELP = """Here's what you can tell me:

🤖 Automatic sending
• auto status — is it on, and today's progress
• pause auto / resume auto
(Runs every 30 min, 10 AM–2 PM Mon–Sat; I message you after every batch.)

📤 Sending by hand (any time, on top of auto)
• send 10 — email 10 hotels (approved ones first)
• send 5 in Hitech City — only that area
• send follow ups — follow-ups that are due (day 3 and day 7)
• check replies — read the inbox now (I also check every 10 min)

✅ Reviewing
• show leads in Madhapur — a numbered list, emails first
• show approved leads
• approve 1 3 5 / block 2 — numbers from the last list
• approve all with email in Banjara Hills

🔎 Finding hotels
• scan Gachibowli 2km — search around a spot
• scan Vijayawada — a whole city

❓ Questions, e.g.
• how many emails did we send today?
• who replied this week?
• which area has the most emails?
• what does Presqio cost? (I'll say: call us)

🌍 Night explorer (finds new hotels 12:30–5 AM, report in the morning)
• explore status · pause explore / resume explore
• explore Pune next — put a city first in line

📊 report — today's numbers now (also sent at 7 PM, with a voice note)
📈 usage — today's AI and voice usage against the daily limits
🎙 You can send me voice notes too.

I'll message you by myself when a hotel replies, after every batch, and at 7 PM with the daily report."""

# Core commands are matched by pattern, not left to the AI, so they always behave the same.
COMMANDS = [
    (re.compile(r"^/?(help|start|commands|menu|what can you do\??)$", re.I), lambda m: {"name": "help"}),
    (re.compile(r"^(pause|stop)\s+auto(?:[\s-]?send(?:ing)?)?[.!]*$", re.I), lambda m: {"name": "auto", "on": False}),
    (re.compile(r"^(resume|start)\s+auto(?:[\s-]?send(?:ing)?)?[.!]*$", re.I), lambda m: {"name": "auto", "on": True}),
    (re.compile(r"^auto(?:[\s-]?send)?\s+status\??$|^status\??$", re.I), lambda m: {"name": "auto_status"}),
    (re.compile(r"^/?(daily\s+)?report[.!?]*$", re.I), lambda m: {"name": "report"}),
    (re.compile(r"^/?(usage|limits?|quota)[.!?]*$", re.I), lambda m: {"name": "usage"}),
    (re.compile(r"^explor(?:e|er|ing)\s+status\??$", re.I), lambda m: {"name": "explore_status"}),
    (re.compile(r"^(pause|stop)\s+explor(?:e|er|ing)[.!]*$", re.I), lambda m: {"name": "explore_on", "on": False}),
    (re.compile(r"^(resume|start)\s+explor(?:e|er|ing)[.!]*$", re.I), lambda m: {"name": "explore_on", "on": True}),
    (re.compile(r"^explore\s+(.+?)\s+next[.!]*$", re.I), lambda m: {"name": "explore_next", "city": m[1]}),
    (re.compile(r"^send\s+(\d+)(?:\s+(?:new\s+)?(?:e-?mails?|mails?))?(?:\s+(?:in|to|from|at)\s+(.+?))?[.!]*$", re.I),
     lambda m: {"name": "send_emails", "count": int(m[1]), "area": m[2]}),
    (re.compile(r"^send\s+follow[\s-]?ups?[.!]*$", re.I), lambda m: {"name": "send_follow_ups"}),
    (re.compile(r"^check\s+(?:the\s+)?(?:replies|inbox|mails?|emails?)[.!?]*$", re.I), lambda m: {"name": "check_replies"}),
    (re.compile(r"^approve\s+([\d,\s]+|\d+(?:\s*(?:,|and)\s*\d+)*)$", re.I), lambda m: {"name": "approve", "numbers": re.findall(r"\d+", m[1])}),
    (re.compile(r"^block\s+([\d,\s]+|\d+(?:\s*(?:,|and)\s*\d+)*)$", re.I), lambda m: {"name": "block", "numbers": re.findall(r"\d+", m[1])}),
]


def command(text: str) -> dict | None:
    t = text.strip()
    for pattern, build in COMMANDS:
        m = pattern.match(t)
        if m:
            return build(m)
    return None


async def handle(text: str, channel: str) -> tuple[str, bool]:
    """-> (reply, started_a_job). A started job reports its own progress on Telegram."""
    save("user", text, channel)
    action = command(text)
    if action:
        started, note = run_action(action)
        reply = note or ("On it." if started else "Done.")
        save("assistant", reply, channel)
        return reply, started

    history = recent_history()
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
    if name == "help":
        return False, HELP
    if name == "explore_status":
        return False, explore.status()
    if name == "explore_on":
        explore.set_enabled(bool(action.get("on")))
        return False, ("🌍 Explorer is ON: it searches new areas every night from 12:30 AM." if action.get("on")
                       else "⏸ Explorer is PAUSED. Say “resume explore” to restart.")
    if name == "explore_next":
        task = asyncio.create_task(_explore_next(str(action.get("city", ""))))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        return True, "🌍 Looking that city up…"
    if name == "usage":
        return False, f"📊 Gemini used today: {usage.summary()}. Limits reset at midnight."
    if name == "auto":
        outreach.set_auto(bool(action.get("on")))
        return False, ("▶️ Auto-send is ON: " + outreach.auto_window() + ". I'll message you after every batch."
                       if action.get("on") else "⏸ Auto-send is PAUSED. You can still say “send 10”. Say “resume auto” to restart.")
    if name == "auto_status":
        s = get_settings()
        return False, (f"🤖 Auto-send is {'ON' if outreach.auto_enabled() else 'PAUSED'}: {outreach.auto_window()}.\n"
                       f"Today: {outreach.sent_today()} of {s.daily_email_cap} emails sent; follow-ups due now: {len(outreach.due_follow_ups(100))}."
                       + ("\nA batch is sending right now." if outreach.busy() else ""))
    if name == "report":
        task = asyncio.create_task(report.send_daily())
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        return True, "📊 Putting today's report together…"
    if name == "list_leads":
        status = action.get("status") if action.get("status") in STATUS_WORDS else "new"
        area = leads.find_area(action["area"]) if action.get("area") else None
        if action.get("area") and not area:
            return False, f"I couldn't find an area called \"{action['area']}\"."
        rows = leads.list_leads(area["key"] if area else None, status)
        where = f" in {area['area']}" if area else ""
        return False, show(rows, f"{STATUS_WORDS[status]}{where} (first {len(rows)}, emails first)")
    if name in ("approve", "block"):
        chosen = picked(action.get("numbers"))
        if not chosen:
            return False, "Which ones? Show a list first (\"show leads in Madhapur\"), then say e.g. \"approve 1 3\"."
        if name == "approve":
            leads.set_status([c["id"] for c in chosen], "ready")
            return False, "✅ Approved: " + ", ".join(c["name"] for c in chosen) + ". They'll be emailed first on your next \"send\"."
        for c in chosen:
            leads.block(c["id"])
        return False, "🚫 Blocked (never contacted): " + ", ".join(c["name"] for c in chosen)
    if name == "approve_all":
        area = leads.find_area(action["area"]) if action.get("area") else None
        if action.get("area") and not area:
            return False, f"I couldn't find an area called \"{action['area']}\"."
        city = area["city"] if area else next((a["city"] for a in leads.areas()), None)
        if not city:
            return False, "No scanned city yet."
        n = leads.approve_all_with_email(city, area["area"] if area else None)
        return False, f"✅ Approved {n} hotels with email in {area['area'] if area else city}."
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
        if reason := leads.scan_blocked(whole_city=not radius):
            return False, f"⚠️ {reason}"
        campaign_id = leads.create_campaign(place, int(float(radius) * 1000) if radius else None)
        task = asyncio.create_task(leads.run_campaign(campaign_id))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        return False, f"🔎 Scanning {place} for hotels. This can take a while; I'll message you when it's done."
    return False, ""


async def _explore_next(city: str) -> None:
    await telegram.send(await explore.prioritise(city))


async def _check_replies() -> None:
    n = await inbox.check()
    await telegram.send("No new replies." if n == 0 else f"Done: {n} new replies (details above).")


async def on_telegram_message(msg: dict) -> None:
    """Text goes straight to Jarvis; a voice note is transcribed first."""
    if msg.get("text"):
        return await on_telegram(msg["text"])
    try:
        await telegram.typing()
        audio = await telegram.download(msg["voice"]["file_id"])
        text = await voice.hear(audio, msg["voice"].get("mime_type", "audio/ogg"))
    except usage.LimitReached as e:
        return await telegram.send(f"⚠️ {e} Type your message instead.")
    except Exception:
        log.exception("Voice message failed")
        return await telegram.send("Sorry, I couldn't hear that voice note. Try again, or type it.")
    await telegram.send(f"🎙 You said: “{text}”")
    await on_telegram(text)


async def on_telegram(text: str) -> None:
    """Called for each message the admin sends the bot."""
    try:
        await telegram.typing()
        reply, started = await handle(text, "telegram")
    except ResourceExhausted:
        reply, started = QUOTA_MESSAGE, False
    except usage.LimitReached as e:
        reply, started = f"⚠️ {e} Commands like “send 10”, “report” and “auto status” still work.", False
    except Exception:
        log.exception("Telegram message failed")
        reply, started = "Sorry, something went wrong answering that. Try again in a minute.", False
    if not started and reply:
        await telegram.send(reply)
