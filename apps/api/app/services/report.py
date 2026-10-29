"""
The end-of-day report: a Telegram message plus the same news as a voice note.
Reads only today's messages, a few counts and the leads with follow-ups.
"""

from collections import Counter
from datetime import datetime, time, timedelta

from google.cloud.firestore_v1.base_query import FieldFilter

from ..config import get_settings
from ..firebase import col
from ..timeutil import now_local
from . import leads, outreach, telegram, usage, voice


def count(q) -> int:
    """Server-side count: about one read per 1,000 matches instead of one per lead."""
    return int(q.count().get()[0][0].value)


def gather() -> dict:
    tz = get_settings().tz
    start = datetime.combine(now_local().date(), time.min, tzinfo=tz)
    msgs = [m.to_dict() for m in col("messages").where(filter=FieldFilter("at", ">=", start.isoformat())).stream()]
    out = [m for m in msgs if m.get("direction") == "out"]
    incoming = [m for m in msgs if m.get("direction") == "in"]
    # bounces were stored as "other" before they got their own kind; their sender gives them away
    bounced = sum(1 for m in incoming if m.get("kind") == "bounce" or "mailer-daemon" in m.get("from", "") or "postmaster" in m.get("from", ""))
    replies = Counter(m.get("kind", "other") for m in incoming
                      if m.get("kind") != "bounce" and "mailer-daemon" not in m.get("from", "") and "postmaster" not in m.get("from", ""))

    left = sum(count(col("leads").where(filter=FieldFilter("status", "==", st)).where(filter=FieldFilter("hasEmail", "==", True)))
               for st in ("ready", "new"))
    end_tomorrow = datetime.combine(now_local().date() + timedelta(days=1), time.max, tzinfo=tz).isoformat()
    waiting = [d.to_dict() for d in col("leads").where(filter=FieldFilter("status", "==", "emailed")).select(["nextActionAt"]).stream()]
    due_tomorrow = sum(1 for l in waiting if l.get("nextActionAt") and l["nextActionAt"] <= end_tomorrow)
    hot = leads.by_status("interested", 10)
    return {
        "first": sum(1 for m in out if not m.get("followUpNo")),
        "followUps": sum(1 for m in out if m.get("followUpNo")),
        "replies": replies,
        "bounced": bounced,
        "left": left,
        "dueTomorrow": due_tomorrow,
        "awaiting": len(waiting),
        "hot": [l["name"] for l in hot],
        "auto": outreach.auto_enabled(),
    }


def written(r: dict) -> str:
    s = get_settings()
    rep = r["replies"]
    lines = [
        f"🌙 Jarvis daily report, {now_local().strftime('%A %d %b')}",
        "",
        f"📤 Emails sent today: {r['first'] + r['followUps']} ({r['first']} new, {r['followUps']} follow-ups) of {s.daily_email_cap} allowed",
        f"📥 Replies today: {sum(rep.values())}"
        + (f" (🔥 {rep['interested']} interested, ❓ {rep['question']} questions, 👋 {rep['not_now']} not now, 🚫 {rep['unsubscribe']} stop, ✉️ {rep['other']} other)" if rep else ""),
        *([f"📭 Bounced (address doesn't exist): {r['bounced']}"] if r["bounced"] else []),
        f"⏳ Waiting for a reply: {r['awaiting']} hotels",
        "",
        f"📋 Still to contact: {r['left']:,} hotels with an email",
        f"🔁 Follow-ups due by tomorrow: {r['dueTomorrow']}",
        f"🤖 Tomorrow: {'auto-send ON, ' + outreach.auto_window() if r['auto'] else 'auto-send PAUSED (say “resume auto” to restart)'}",
    ]
    if r["hot"]:
        lines += ["", "🔥 Interested: " + ", ".join(r["hot"])]
    lines += ["", f"📈 Gemini today: {usage.summary()}"]
    if r["left"] == 0:
        lines += ["", "⚠️ No hotels with an email are left. Scan another area to find more."]
    return "\n".join(lines)


def spoken(r: dict) -> str:
    rep = r["replies"]
    parts = [
        f"Good evening. Here is today's Presqio outreach report. "
        f"I sent {r['first'] + r['followUps']} emails today: {r['first']} new, and {r['followUps']} follow-ups.",
        f"We got {sum(rep.values())} replies" + (f", and {rep['interested']} of them are interested." if rep.get("interested") else "."),
        *([f"{r['bounced']} emails bounced because the address doesn't exist."] if r["bounced"] else []),
        f"{r['awaiting']} hotels haven't replied yet.",
        f"There are {r['left']} hotels with an email still to contact, and {r['dueTomorrow']} follow-ups are due by tomorrow.",
        "Automatic sending continues tomorrow from ten in the morning." if r["auto"] else "Automatic sending is paused.",
    ]
    if r["hot"]:
        parts.append("Interested hotels: " + ", ".join(r["hot"][:5]) + ". You may want to call them.")
    return " ".join(parts)


async def send_daily() -> str:
    r = gather()
    text = written(r)
    await telegram.send(text)
    try:
        audio, kind = await voice.speak(spoken(r))
        await telegram.send_voice(audio, kind, "🔊 Today's report")
    except Exception:
        pass   # the written report already went out; a voice failure shouldn't hide it
    return text
