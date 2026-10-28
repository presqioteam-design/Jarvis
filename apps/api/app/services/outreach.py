"""
Outreach runs only when the admin asks ("send 10"). Jarvis picks the leads,
sends one email every 20-45 seconds so Gmail doesn't see a burst, and reports
the list back on Telegram.
"""

import asyncio
import logging
import random
from datetime import datetime, time, timedelta

from google.cloud.firestore_v1.base_query import FieldFilter

from ..config import get_settings
from ..firebase import col
from ..timeutil import now_local, now_utc
from . import activity, inbox, keepalive, leads, mailer, telegram, templates

log = logging.getLogger(__name__)
FOLLOW_UP_GAP_DAYS = [3, 4]     # follow-up 1 three days after the first email, follow-up 2 four days later
PAUSE_SECONDS = (20, 45)

_running: asyncio.Task | None = None


def busy() -> bool:
    return _running is not None and not _running.done()


def start(job) -> bool:
    """Run one send job in the background; refuses if one is already running."""
    global _running
    if busy():
        return False
    _running = asyncio.create_task(job)
    return True


def sent_today() -> int:
    start_of_day = datetime.combine(now_local().date(), time.min, tzinfo=get_settings().tz).isoformat()
    # one filter only, so Firestore needs no composite index
    q = col("messages").where(filter=FieldFilter("at", ">=", start_of_day)).select(["direction"])
    return sum(1 for m in q.stream() if m.to_dict().get("direction") == "out")


def pick_first_emails(count: int, area: str | None) -> list[dict]:
    """Approved leads first, then unreviewed ones with an email. Never the same address twice."""
    contacted = {d.to_dict()["emailedTo"] for d in col("leads").where(filter=FieldFilter("emailedTo", ">", "")).select(["emailedTo"]).stream()}
    blocked = {d.id for d in col("dnc").stream()}
    picked, seen = [], set(contacted)
    area = area.split(",")[0].strip().lower() if area else None   # "Madhapur, Hyderabad" -> "madhapur"
    for status in ("ready", "new"):
        # two equality filters: no composite index needed, and only leads with an email are read
        q = col("leads").where(filter=FieldFilter("status", "==", status)).where(filter=FieldFilter("hasEmail", "==", True))
        for d in q.stream():
            lead = {"id": d.id, **d.to_dict()}
            if area and area not in lead.get("area", "").lower():
                continue
            to = next((e for e in lead.get("emails", []) if e not in seen and e not in blocked), None)
            if not to:
                continue
            seen.add(to)
            picked.append({**lead, "to": to})
            if len(picked) == count:
                return picked
    return picked


def due_follow_ups(limit: int) -> list[dict]:
    now = now_utc().isoformat()
    docs = col("leads").where(filter=FieldFilter("status", "==", "emailed")).stream()
    due = [{"id": d.id, **d.to_dict()} for d in docs]
    due = [l for l in due if l.get("nextActionAt") and l["nextActionAt"] <= now and l.get("followUps", 0) < 2]
    return sorted(due, key=lambda l: l["nextActionAt"])[:limit]


async def send_first_emails(count: int, area: str | None = None) -> None:
    cap = get_settings().daily_email_cap - sent_today()
    if cap <= 0:
        await telegram.send(f"⚠️ Daily limit reached ({get_settings().daily_email_cap} emails). I'll send more tomorrow.")
        return
    targets = pick_first_emails(min(count, cap), area)
    if not targets:
        where = f" in {area}" if area else ""
        await telegram.send(f"No leads{where} with an email are left to contact. Run a scan or approve more leads.")
        return
    note = f" (capped at today's limit of {get_settings().daily_email_cap})" if count > cap else ""
    await telegram.send(f"📤 Sending {len(targets)} emails{note}. About {len(targets) * 32 // 60 + 1} min; I'll send the list when done.")
    await run(targets, step=0)


async def send_follow_ups(count: int = 50) -> None:
    await inbox.check()   # never follow up on someone who has replied or asked us to stop
    targets = due_follow_ups(min(count, get_settings().daily_email_cap - sent_today()))
    if not targets:
        await telegram.send("No follow-ups are due right now.")
        return
    for t in targets:
        t["to"] = t["emailedTo"]
    await telegram.send(f"📤 Sending {len(targets)} follow-ups…")
    await run(targets, step=None)


async def run(targets: list[dict], step: int | None) -> None:
    """step=0 for first emails; None means each lead's next follow-up."""
    async with keepalive.awake():
        sent, failed = await _send_all(targets, step)
    await _report(sent, failed, step)


async def _send_all(targets: list[dict], step: int | None) -> tuple[list[dict], list[str]]:
    sent, failed = [], []
    for i, lead in enumerate(targets):
        n = lead.get("followUps", 0) + 1 if step is None else step
        email = templates.render(n, lead["name"], lead.get("area") or templates.area_from(lead.get("address", "")), get_settings().sender_name)
        try:
            msg_id = await mailer.send(lead["to"], email.subject, email.body, lead.get("lastMessageId") if n else None)
        except Exception as e:
            log.exception("Send to %s failed", lead["to"])
            failed.append(f"{lead['name']} ({lead['to']}): {type(e).__name__}")
            continue
        record(lead, n, email, msg_id)
        sent.append(lead)
        if i < len(targets) - 1:
            await asyncio.sleep(random.uniform(*PAUSE_SECONDS))

    return sent, failed


async def _report(sent: list[dict], failed: list[str], step: int | None) -> None:
    if sent:
        leads.recompute_area_of([l["id"] for l in sent])
    kind = "first emails" if step == 0 else "follow-ups"
    lines = [f"✅ Sent {len(sent)} {kind}:"]
    lines += [f"{i}. {l['name']} ({l.get('area') or '?'}): {l['to']}" for i, l in enumerate(sent, 1)]
    if failed:
        lines += ["", f"❌ {len(failed)} failed:"] + failed
    lines += ["", f"Today: {sent_today()} of {get_settings().daily_email_cap} emails used."]
    await telegram.send("\n".join(lines))


def record(lead: dict, n: int, email: templates.Email, msg_id: str) -> None:
    now = now_utc()
    col("messages").add({
        "leadId": lead["id"], "direction": "out", "to": lead["to"], "subject": email.subject, "body": email.body,
        "messageId": msg_id, "inReplyTo": lead.get("lastMessageId"), "followUpNo": n, "at": now.isoformat(),
    })
    patch = {
        "status": "emailed", "followUps": n, "lastContactAt": now.isoformat(), "updatedAt": now.isoformat(),
        "lastMessageId": msg_id, "emailedTo": lead["to"],
        "nextActionAt": (now + timedelta(days=FOLLOW_UP_GAP_DAYS[n])).isoformat() if n < len(FOLLOW_UP_GAP_DAYS) else None,
    }
    col("leads").document(lead["id"]).update(patch)
    label = "Emailed" if n == 0 else f"Follow-up {n} to"
    activity.log("email_sent", f"{label} {lead['name']} ({lead['to']})", lead["id"])
