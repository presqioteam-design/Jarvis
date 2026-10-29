"""
Read replies from the outreach Gmail inbox (IMAP), match them to leads,
sort them with the AI, update the lead and alert the admin on Telegram.
Bounces ("address not found") mark the lead as bounced.
"""

import asyncio
import email
import imaplib
import json
import logging
import re
from datetime import timedelta
from email.header import decode_header, make_header
from email.utils import parseaddr

from google.cloud.firestore_v1.base_query import FieldFilter

from ..config import get_settings
from ..firebase import col
from ..timeutil import now_utc
from . import activity, gmail, leads, llm, telegram, usage

log = logging.getLogger(__name__)
LOOKBACK_DAYS = 21
KINDS = {"interested", "question", "not_now", "unsubscribe", "other"}
STATUS_FOR = {"interested": "interested", "question": "replied", "not_now": "not_interested", "unsubscribe": "unsubscribed", "other": "replied"}

CLASSIFY = """A hotel replied to a cold email about Presqio (staff attendance and payroll software).
Sort the reply into one kind:
- interested: wants to try it, a call, a demo, or more details
- question: asks something specific (price, features, setup) without saying yes or no
- not_now: polite no, not needed, maybe later
- unsubscribe: asks to stop emailing, remove them, or is angry about the email
- other: anything else (auto-reply, out of office, wrong person)
Return JSON: {"kind": "<kind>", "summary": "<one short sentence of what they said>"}"""


def _text_of(msg: email.message.Message) -> str:
    part = next((p for p in msg.walk() if p.get_content_type() == "text/plain"), None)
    if part is None:
        part = next((p for p in msg.walk() if p.get_content_type() == "text/html"), msg)
    raw = part.get_payload(decode=True) or b""
    text = raw.decode(part.get_content_charset() or "utf-8", errors="replace")
    text = re.sub(r"<[^>]+>", " ", text)
    # drop the quoted original email below the reply
    text = re.split(r"\nOn .{5,120}wrote:|\n-{2,} ?Original Message|\n>", text)[0]
    return re.sub(r"\s+\n", "\n", text).strip()[:3000]


def _parse(raw: bytes) -> dict:
    msg = email.message_from_bytes(raw)
    return {
        "messageId": (msg.get("Message-ID") or "").strip(),
        "from": parseaddr(msg.get("From", ""))[1].lower(),
        "subject": str(make_header(decode_header(msg.get("Subject", "")))),
        "inReplyTo": (msg.get("In-Reply-To") or "").strip(),
        "body": _text_of(msg),
        "date": msg.get("Date", ""),
    }


async def fetch(since_days: int) -> list[dict]:
    """Inbox messages via the Gmail API when set up (works on Render), else IMAP."""
    if gmail.enabled():
        return [_parse(raw) for raw in await gmail.recent_raw(since_days)]
    return await asyncio.to_thread(_fetch, since_days)


def _fetch(since_days: int) -> list[dict]:
    s = get_settings()
    since = (now_utc() - timedelta(days=since_days)).strftime("%d-%b-%Y")
    imap = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=30)
    try:
        imap.login(s.email_address, s.email_app_password)
        imap.select("INBOX", readonly=True)
        _, data = imap.search(None, f'(SINCE "{since}")')
        out = []
        for num in data[0].split():
            _, parts = imap.fetch(num, "(BODY.PEEK[])")
            out.append(_parse(parts[0][1]))
        return out
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def _lead_emailed(addresses: list[str]) -> dict | None:
    """The lead we emailed at one of these addresses (Firestore allows 30 per 'in' query)."""
    addresses = list(dict.fromkeys(addresses))[:30]
    if not addresses:
        return None
    for d in col("leads").where(filter=FieldFilter("emailedTo", "in", addresses)).limit(1).stream():
        return {"id": d.id, **d.to_dict()}
    return None


async def check() -> int:
    """Process new replies. Returns how many were new.

    Runs every few minutes, so it must stay cheap on the free Firestore quota: one read of
    meta/inbox (message ids already looked at), then one lead lookup per mail never seen before.
    Reading every emailed lead on each run used up the daily quota once hundreds were emailed.
    """
    state = col("meta").document("inbox")
    snap = state.get()
    if snap.exists:
        seen: dict[str, str] = (snap.to_dict() or {}).get("seen", {})
    else:   # first run with this format: start from the replies already recorded
        seen = {m.to_dict().get("messageId"): now_utc().isoformat()
                for m in col("messages").where(filter=FieldFilter("direction", "==", "in")).stream()
                if m.to_dict().get("messageId")}
    mails = await fetch(LOOKBACK_DAYS)

    handled, changed = [], not snap.exists
    for m in mails:
        if not m["messageId"] or m["messageId"] in seen:
            continue
        try:
            if "mailer-daemon" in m["from"] or "postmaster" in m["from"]:
                lead = _lead_emailed(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", m["body"].lower()))
                if lead:
                    await bounced(lead, m)
                    handled.append(lead["id"])
            else:
                lead = _lead_emailed([m["from"]])
                if lead:
                    await replied(lead, m)
                    handled.append(lead["id"])
        except Exception:
            log.exception("Couldn't process mail from %s; will retry next check", m["from"])
            continue
        seen[m["messageId"]] = now_utc().isoformat()
        changed = True

    # forget ids well past the look-back window so the document stays small
    cutoff = (now_utc() - timedelta(days=LOOKBACK_DAYS + 7)).isoformat()
    kept = {k: v for k, v in seen.items() if v >= cutoff}
    if changed or len(kept) != len(seen):
        state.set({"seen": kept, "updatedAt": now_utc().isoformat()})
    if handled:
        leads.recompute_area_of(handled)
    return len(handled)


async def classify(body: str) -> tuple[str, str]:
    try:
        raw = await llm.complete(CLASSIFY, [{"role": "user", "content": body or "(empty reply)"}], max_tokens=300, json=True)
    except usage.LimitReached:
        return "other", "(not sorted: today's AI limit is used up)"   # still recorded and alerted
    try:
        out = json.loads(raw)
        kind = out.get("kind") if out.get("kind") in KINDS else "other"
        return kind, str(out.get("summary", "")).strip()
    except (json.JSONDecodeError, AttributeError):
        return "other", ""


async def replied(lead: dict, m: dict) -> None:
    kind, summary = await classify(m["body"])
    now = now_utc().isoformat()
    col("messages").add({
        "leadId": lead["id"], "direction": "in", "from": m["from"], "subject": m["subject"], "body": m["body"],
        "messageId": m["messageId"], "inReplyTo": m["inReplyTo"], "kind": kind, "at": now,
    })
    # a reply stops the follow-ups; unsubscribe also blocks the address for good
    col("leads").document(lead["id"]).update({"status": STATUS_FOR[kind], "nextActionAt": None, "updatedAt": now})
    if kind == "unsubscribe":
        col("dnc").document(m["from"]).set({"reason": "asked to stop", "createdAt": now})

    icon = {"interested": "🔥", "question": "❓", "not_now": "👋", "unsubscribe": "🚫", "other": "✉️"}[kind]
    label = {"interested": "is interested", "question": "has a question", "not_now": "said not now",
             "unsubscribe": "asked us to stop (blocked)", "other": "replied"}[kind]
    activity.log("reply", f"{lead['name']} {label}: {summary}", lead["id"])
    snippet = m["body"][:600] + ("…" if len(m["body"]) > 600 else "")
    await telegram.send(
        f"{icon} {lead['name']} ({lead.get('area', '?')}) {label}\n"
        f"From: {m['from']}\n\n\"{snippet}\"\n\n"
        f"{'Call them: ' + lead['phone'] if lead.get('phone') else 'Reply from the Gmail inbox.'}"
    )


async def bounced(lead: dict, m: dict) -> None:
    now = now_utc().isoformat()
    col("messages").add({"leadId": lead["id"], "direction": "in", "from": m["from"], "subject": m["subject"],
                         "body": m["body"][:500], "messageId": m["messageId"], "kind": "bounce", "at": now})
    col("leads").document(lead["id"]).update({"status": "bounced", "nextActionAt": None, "updatedAt": now})
    activity.log("status_change", f"Email to {lead['name']} bounced ({lead['emailedTo']})", lead["id"])


async def watch(every_minutes: int = 10) -> None:
    """Background loop started with the API."""
    while True:
        try:
            await check()
        except Exception:
            log.exception("Reply check failed")
        await asyncio.sleep(every_minutes * 60)
