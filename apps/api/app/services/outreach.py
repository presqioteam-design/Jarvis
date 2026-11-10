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
from . import activity, gmail, inbox, keepalive, leads, mailer, prefs, telegram, templates

log = logging.getLogger(__name__)
PAUSE_SECONDS = (20, 45)
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

_running: asyncio.Task | None = None
# set when Gmail refuses to send (a limit or a spam hold): nothing more is tried until then,
# so Jarvis doesn't keep knocking on a door that's shut (that makes the hold longer)
LIMITED_PAUSE = timedelta(minutes=30)
_limited_until = None
_limited_reason = ""


def gmail_limited() -> str:
    """Google's reason if sending is paused because Gmail refused, else ""."""
    return _limited_reason if _limited_until and now_utc() < _limited_until else ""


def busy() -> bool:
    return _running is not None and not _running.done()


def start(job) -> bool:
    """Run one send job in the background; refuses if one is already running."""
    global _running
    if busy():
        return False
    _running = asyncio.create_task(_reported(job))
    return True


async def _reported(job) -> None:
    """A background batch that crashes must say so; otherwise it just stops and nothing is sent or reported."""
    try:
        await job
    except Exception as e:
        log.exception("Send batch failed")
        try:
            await telegram.send(f"❌ The email batch stopped with an error before finishing: {type(e).__name__}: {str(e)[:200]}")
        except Exception:
            log.exception("Couldn't report the failed batch on Telegram")


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
    limit = prefs.sending()["dailyCap"]
    cap = limit - sent_today()
    if cap <= 0:
        await telegram.send(f"⚠️ Daily limit reached ({limit} emails). I'll send more tomorrow.")
        return
    targets = pick_first_emails(min(count, cap), area)
    if not targets:
        where = f" in {area}" if area else ""
        await telegram.send(f"No leads{where} with an email are left to contact. Run a scan or approve more leads.")
        return
    note = f" (capped at today's limit of {limit})" if count > cap else ""
    await telegram.send(f"📤 Sending {len(targets)} emails{note}. About {len(targets) * 32 // 60 + 1} min; I'll send the list when done.")
    await run(targets, step=0)


async def _replies_read() -> str:
    """Check replies before sending. Returns Google's reason if Gmail won't let us read the inbox, else ""."""
    try:
        await inbox.check()
        return ""
    except gmail.ReadRefused as e:
        log.warning("Gmail refused to read the inbox before sending: %s", e)
        return str(e)


async def send_follow_ups(count: int = 50) -> None:
    # never follow up on someone who has replied or asked us to stop, so no inbox means no follow-ups
    if why := await _replies_read():
        await telegram.send(f"⚠️ No follow-ups sent: Gmail won't let me read the inbox to check for replies first. Google says: {why}")
        return
    targets = due_follow_ups(min(count, prefs.sending()["dailyCap"] - sent_today()))
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
    kind = "first emails" if step == 0 else "follow-ups"
    await _report([(f"✅ Sent {len(sent)} {kind}:", sent)], failed)


# ── automatic sending ────────────────────────────────────────────────────────

def auto_enabled() -> bool:
    return prefs.sending()["enabled"]


def set_auto(on: bool) -> None:
    prefs.ref().set({"autoSend": on}, merge=True)
    prefs.forget()


def days_text(days: list[int]) -> str:
    if days == list(range(days[0], days[-1] + 1)) and len(days) > 2:
        return f"{WEEKDAYS[days[0]]}–{WEEKDAYS[days[-1]]}"
    return ", ".join(WEEKDAYS[d] for d in days)


def auto_window() -> str:
    c = prefs.sending()
    return f"{c['perRun']} every 30 min, {c['from']}–{c['until']} {days_text(c['days'])}, up to {c['dailyAuto']} a day"


def auto_send() -> str:
    """Called by the cron every 30 min. Starts a batch, or says why not."""
    c = prefs.sending()
    now = now_local()
    if not c["enabled"]:
        return "paused"
    if now.weekday() not in c["days"] or not (c["from"] <= now.strftime("%H:%M") <= c["until"]):
        return "outside sending hours"
    if busy():
        return "a batch is already sending"
    if gmail_limited():
        return "Gmail is limiting sending; trying again later"
    room = min(c["dailyAuto"], c["dailyCap"]) - sent_today()
    if room <= 0:
        return "daily limit reached"
    return "started" if start(_auto_batch(room, c["perRun"], c["followUps"])) else "a batch is already sending"


async def _auto_batch(room: int, per_run: int, follow_ups: bool) -> None:
    # replies first: never email someone who just answered. If the inbox can't be read, first emails
    # (addresses never contacted) still go out, but follow-ups wait until replies can be checked.
    unread = await _replies_read()
    follow = due_follow_ups(min(per_run, room)) if follow_ups and not unread else []
    for t in follow:
        t["to"] = t["emailedTo"]
    first = pick_first_emails(min(per_run, room - len(follow)), None) if room > len(follow) else []
    if not follow and not first:
        await _nothing_left_once_a_day()
        return
    async with keepalive.awake():
        sent_f, failed_f = await _send_all(follow, None)
        sent_n, failed_n = await _send_all(first, 0)
    stamp = now_local().strftime("%I:%M %p").lstrip("0")
    await _report([(f"🤖 Auto batch, {stamp}", []), (f"New ({len(sent_n)}):", sent_n), (f"Follow-ups ({len(sent_f)}):", sent_f)], failed_f + failed_n)
    if unread:
        await telegram.send(f"⏸ Follow-ups skipped this batch: Gmail won't let me read the inbox to check for replies first. Google says: {unread}")


async def _nothing_left_once_a_day() -> None:
    ref = col("settings").document("main")
    today = now_local().date().isoformat()
    if ((ref.get().to_dict() or {}).get("emptyNoticeOn")) != today:
        ref.set({"emptyNoticeOn": today}, merge=True)
        await telegram.send("🤖 Auto-send: no businesses with an email are left to contact, and no follow-ups are due. "
                            "Scan another area to find more.")


async def _send_all(targets: list[dict], step: int | None) -> tuple[list[dict], list[str]]:
    global _limited_until, _limited_reason
    sent, failed = [], []
    if gmail_limited():
        return sent, failed
    f1, f2 = prefs.sending()["followUpDays"]
    gaps = [f1, f2 - f1]   # days until follow-up 1, then until follow-up 2
    me = prefs.emails()
    for i, lead in enumerate(targets):
        n = lead.get("followUps", 0) + 1 if step is None else step
        email = templates.render(n, lead["name"], lead.get("area") or templates.area_from(lead.get("address", "")),
                                 me["senderName"], lead.get("category"), me["phone"], me["website"])
        # a first email to a domain that takes no mail would only bounce (and bounces get Gmail throttled)
        if n == 0 and not await mailer.accepts_email(lead["to"]):
            mark_undeliverable(lead)
            failed.append(f"{lead['name']} ({lead['to']}): skipped, that domain doesn't receive email (marked bounced)")
            continue
        try:
            msg_id, thread_id = await mailer.send(lead["to"], email.subject, email.body,
                                                  lead.get("lastMessageId") if n else None, lead.get("threadId") if n else None,
                                                  sender_name=me["senderName"])
        except mailer.MailSetupError as e:
            failed.append(f"Stopped before sending anything: {e}")
            break
        except mailer.SendingLimited as e:
            _limited_until, _limited_reason = now_utc() + LIMITED_PAUSE, str(e)
            failed.append(f"⏸ Gmail is refusing to send right now, so I stopped and will try again in 30 minutes. "
                          f"Google says: {e}. This usually means a sending limit or a short spam hold; "
                          "fewer emails a day and fewer bounces make it rarer.")
            log.warning("Gmail refused to send: %s", e)
            break
        except Exception as e:
            log.exception("Send to %s failed", lead["to"])
            failed.append(f"{lead['name']} ({lead['to']}): {type(e).__name__}: {str(e)[:120]}")
            if len(failed) >= 2 and not sent:
                failed.append("Stopped after 2 failures in a row; the rest weren't tried.")
                break
            continue
        record(lead, n, email, msg_id, thread_id, gaps)
        sent.append(lead)
        if i < len(targets) - 1:
            await asyncio.sleep(random.uniform(*PAUSE_SECONDS))

    return sent, failed


async def _report(groups: list[tuple[str, list[dict]]], failed: list[str]) -> None:
    """groups: (heading, leads sent) pairs. The first heading always shows; later empty groups are skipped."""
    everyone = [l for _, g in groups for l in g]
    if everyone:
        leads.recompute_area_of([l["id"] for l in everyone])
    lines = []
    for i, (heading, sent) in enumerate(groups):
        if sent or i == 0:
            lines.append(heading)
            lines += [f"{i}. {l['name']} ({l.get('area') or '?'}): {l['to']}" for i, l in enumerate(sent, 1)]
    if failed:
        lines += ["", f"❌ {len(failed)} failed:"] + failed
    lines += ["", f"Today: {sent_today()} of {prefs.sending()['dailyCap']} emails used."]
    await telegram.send("\n".join(lines))


def mark_undeliverable(lead: dict) -> None:
    """Never emailed: its domain doesn't exist or takes no email."""
    now = now_utc().isoformat()
    col("leads").document(lead["id"]).update({"status": "bounced", "nextActionAt": None, "updatedAt": now,
                                              "bounceReason": "domain doesn't receive email"})
    activity.log("status_change", f"Skipped {lead['name']}: {lead['to']} can't receive email (domain doesn't take mail)", lead["id"])


def record(lead: dict, n: int, email: templates.Email, msg_id: str, thread_id: str | None, gaps: list[int]) -> None:
    now = now_utc()
    col("messages").add({
        "leadId": lead["id"], "direction": "out", "to": lead["to"], "subject": email.subject, "body": email.body,
        "messageId": msg_id, "inReplyTo": lead.get("lastMessageId"), "followUpNo": n, "at": now.isoformat(),
    })
    patch = {
        "status": "emailed", "followUps": n, "lastContactAt": now.isoformat(), "updatedAt": now.isoformat(),
        "lastMessageId": msg_id, "emailedTo": lead["to"], **({"threadId": thread_id} if thread_id else {}),
        "nextActionAt": (now + timedelta(days=gaps[n])).isoformat() if n < len(gaps) else None,
    }
    col("leads").document(lead["id"]).update(patch)
    label = "Emailed" if n == 0 else f"Follow-up {n} to"
    activity.log("email_sent", f"{label} {lead['name']} ({lead['to']})", lead["id"])
