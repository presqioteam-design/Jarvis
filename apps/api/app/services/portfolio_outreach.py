"""
Portfolio emails: Vinod's website offer, sent from the same Gmail as Presqio's outreach, signed by
Vinod with his own email and phone in the text.

- Only businesses approved on the Portfolio page are emailed (status "ready").
- Its own schedule and daily limit; both campaigns together stay inside Presqio's daily limit,
  which protects the one Gmail account they share.
- A business is never pitched by both campaigns within PITCH_GAP_DAYS, and never after it has
  replied to Presqio. The do-not-contact list is shared.
- Records go to portfolio_messages, so Presqio's counts and daily report don't change.
- Replies arrive in the same inbox; these are picked out by the threads the portfolio emails started.
"""

import asyncio
import json
import logging
import random
import re
from datetime import datetime, time, timedelta

from google.cloud.firestore_v1.base_query import FieldFilter

from ..config import get_settings
from ..firebase import col
from ..timeutil import now_local, now_utc
from . import activity, gmail, inbox, keepalive, llm, mailer, portfolio, portfolio_emails, prefs, telegram, usage

log = logging.getLogger(__name__)
PAUSE_SECONDS = (25, 55)
PITCH_GAP_DAYS = 60
LOOKBACK_DAYS = 21
LIMITED_PAUSE = timedelta(minutes=30)
# the tick cron runs every 30 min, 9:30 AM-8 PM IST, Monday-Saturday
EARLIEST, LATEST, DAYS = "09:30", "20:00", [0, 1, 2, 3, 4, 5]
MAX_PER_RUN, MAX_DAILY = 10, 60
DEFAULTS = {"enabled": False, "perRun": 3, "dailyCap": 15, "from": "10:00", "until": "18:00", "days": DAYS,
            "followUps": True, "followUpDays": [4, 10]}
PRESQIO_ENGAGED = ("replied", "interested", "demo", "customer")

_running: asyncio.Task | None = None
_limited_until = None
_limited_reason = ""


# ── settings ────────────────────────────────────────────────────────────────

def settings() -> dict:
    return DEFAULTS | (prefs.portfolio().get("sending") or {})


def me() -> dict:
    return portfolio_emails.DEFAULTS | {k: v for k, v in (prefs.portfolio().get("me") or {}).items() if v}


def save_settings(patch: dict) -> dict:
    """Validate and save; raises ValueError with a sentence for the page."""
    cfg = settings() | {k: v for k, v in patch.items() if v is not None}
    for k in ("from", "until"):
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(cfg[k])):
            raise ValueError("Times look like 10:00.")
    if not (EARLIEST <= cfg["from"] < cfg["until"] <= LATEST):
        raise ValueError(f"Sending hours must be between {EARLIEST} and {LATEST}, and start before they end.")
    if not 1 <= int(cfg["perRun"]) <= MAX_PER_RUN:
        raise ValueError(f"Emails per run must be 1 to {MAX_PER_RUN}.")
    if not 1 <= int(cfg["dailyCap"]) <= MAX_DAILY:
        raise ValueError(f"The daily limit must be 1 to {MAX_DAILY}.")
    days = sorted({int(d) for d in cfg["days"]})
    if not days or any(d not in DAYS for d in days):
        raise ValueError("Pick at least one day, Monday to Saturday.")
    f1, f2 = (int(x) for x in cfg["followUpDays"])
    if not 1 <= f1 < f2 <= 30:
        raise ValueError("Follow-ups go out 1 to 30 days after the first email, the second after the first.")
    if int(cfg["dailyCap"]) > prefs.sending()["dailyCap"]:
        raise ValueError(f"The portfolio limit can't be more than the mailbox's daily limit ({prefs.sending()['dailyCap']}, "
                         "on the Settings page): both campaigns share it.")
    cfg |= {"perRun": int(cfg["perRun"]), "dailyCap": int(cfg["dailyCap"]), "days": days, "followUpDays": [f1, f2],
            "enabled": bool(cfg["enabled"]), "followUps": bool(cfg["followUps"])}
    prefs.save_portfolio({"sending": {k: cfg[k] for k in DEFAULTS}})
    return settings()


def save_me(patch: dict) -> dict:
    cur = me() | {k: v.strip() for k, v in patch.items() if isinstance(v, str)}
    if not cur["senderName"]:
        raise ValueError("Add the name the emails are signed with.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", cur["email"], re.I):
        raise ValueError("Add the email address people can write to, like you@gmail.com.")
    if not cur["website"].startswith(("http://", "https://")):
        raise ValueError("The website starts with https://")
    prefs.save_portfolio({"me": cur})
    return me()


def mailbox() -> dict:
    """The Presqio outreach mailbox, which the portfolio emails share."""
    s = get_settings()
    return {"address": s.email_address, "connected": gmail.enabled() or bool(s.email_app_password and not s.render_external_url),
            "sharedCap": prefs.sending()["dailyCap"], "sharedSentToday": _mailbox_sent_today()}


def _mailbox_sent_today() -> int:
    """Everything the shared mailbox sent today: Presqio's emails and these."""
    from . import outreach   # outreach imports this module too
    return outreach.sent_today()


def room_today() -> int:
    """How many more portfolio emails can go today: inside its own limit and the mailbox's."""
    return max(0, min(settings()["dailyCap"] - sent_today(), prefs.sending()["dailyCap"] - _mailbox_sent_today()))


# ── who gets emailed ────────────────────────────────────────────────────────

def sent_today() -> int:
    start = datetime.combine(now_local().date(), time.min, tzinfo=get_settings().tz).isoformat()
    q = col("portfolio_messages").where(filter=FieldFilter("at", ">=", start)).select(["direction"])
    return sum(1 for m in q.stream() if m.to_dict().get("direction") == "out")


def _presqio_off_limits() -> set[str]:
    """Addresses Presqio emailed in the last PITCH_GAP_DAYS days, or that ever answered Presqio."""
    cutoff = (now_utc() - timedelta(days=PITCH_GAP_DAYS)).isoformat()
    out = set()
    for d in col("leads").where(filter=FieldFilter("emailedTo", ">", "")).select(["emailedTo", "lastContactAt", "status"]).stream():
        l = d.to_dict()
        if l.get("status") in PRESQIO_ENGAGED or (l.get("lastContactAt") or "") >= cutoff:
            out.add(l["emailedTo"].lower())
    return out


def recently_pitched() -> set[str]:
    """For Presqio's side: addresses the portfolio emails reached in the last PITCH_GAP_DAYS days,
    or that answered them."""
    cutoff = (now_utc() - timedelta(days=PITCH_GAP_DAYS)).isoformat()
    out = set()
    for d in col("prospects").where(filter=FieldFilter("emailedTo", ">", "")).select(["emailedTo", "lastContactAt", "status"]).stream():
        p = d.to_dict()
        if p.get("status") in ("replied", "interested") or (p.get("lastContactAt") or "") >= cutoff:
            out.add(p["emailedTo"].lower())
    return out


def pick_first_emails(count: int) -> list[dict]:
    """Approved businesses with an email, oldest approval first. Never the same address twice."""
    if count <= 0:
        return []
    q = col("prospects").where(filter=FieldFilter("status", "==", "ready")).where(filter=FieldFilter("reach", "==", "email"))
    ready = sorted(({"id": d.id, **d.to_dict()} for d in q.stream()), key=lambda p: p.get("updatedAt", ""))
    if not ready:
        return []
    emailed = {d.to_dict()["emailedTo"].lower() for d in col("prospects").where(filter=FieldFilter("emailedTo", ">", ""))
               .select(["emailedTo"]).stream()}
    skip = emailed | {d.id for d in col("dnc").stream()} | _presqio_off_limits()
    picked = []
    for p in ready:
        to = next((e.lower() for e in p.get("emails", []) if e.lower() not in skip), None)
        if to:
            skip.add(to)
            picked.append(p | {"to": to})
            if len(picked) == count:
                break
    return picked


def due_follow_ups(limit: int) -> list[dict]:
    if limit <= 0:
        return []
    now = now_utc().isoformat()
    docs = col("prospects").where(filter=FieldFilter("status", "==", "emailed")).stream()
    due = [{"id": d.id, **d.to_dict()} for d in docs]
    due = [p for p in due if p.get("nextActionAt") and p["nextActionAt"] <= now and p.get("followUps", 0) < 2]
    for p in due:
        p["to"] = p["emailedTo"]
    return sorted(due, key=lambda p: p["nextActionAt"])[:limit]


# ── sending ─────────────────────────────────────────────────────────────────

def busy() -> bool:
    return _running is not None and not _running.done()


def gmail_limited() -> str:
    return _limited_reason if _limited_until and now_utc() < _limited_until else ""


def outreach_limited() -> str:
    """Gmail refused Presqio's emails recently: it's the same account, so wait too."""
    from . import outreach
    return outreach.gmail_limited()


def _start(job) -> bool:
    global _running
    if busy():
        job.close()
        return False
    _running = asyncio.create_task(_reported(job))
    return True


async def _reported(job) -> None:
    try:
        await job
    except Exception as e:
        log.exception("Portfolio send batch failed")
        await telegram.send(f"❌ The portfolio email batch stopped with an error: {type(e).__name__}: {str(e)[:200]}")


def send_now(count: int) -> str:
    """The page's "Send now": approved businesses, inside today's limit, outside the schedule too."""
    if not mailbox()["connected"]:
        raise ValueError("The outreach mailbox isn't set up (Settings → Connections).")
    if why := gmail_limited() or outreach_limited():
        raise ValueError(f"Gmail is refusing to send for now; Jarvis tries again in 30 minutes. Google says: {why}")
    room = room_today()
    if room <= 0:
        raise ValueError("Today's limit is used (the portfolio's own, or the mailbox's shared with Presqio). More go out tomorrow.")
    ready = col("prospects").where(filter=FieldFilter("status", "==", "ready")).where(filter=FieldFilter("reach", "==", "email"))
    if not list(ready.limit(1).stream()):
        raise ValueError("No approved businesses with an email are waiting. Approve some on the Portfolio page, "
                         "or say “show website leads” and then “approve 1 3”.")
    if not _start(_batch(min(count, room), follow_ups=False, heading="📤 Portfolio emails")):
        raise ValueError("A batch is already sending.")
    return f"Sending up to {min(count, room)} now, about 40 seconds apart. Telegram gets the list when it's done."


def auto_send() -> str:
    """Called by the tick cron every 30 min."""
    c = settings()
    now = now_local()
    if not c["enabled"]:
        return "off"
    if not mailbox()["connected"]:
        return "mailbox not set up"
    if now.weekday() not in c["days"] or not (c["from"] <= now.strftime("%H:%M") <= c["until"]):
        return "outside sending hours"
    if busy():
        return "a batch is already sending"
    if gmail_limited() or outreach_limited():
        return "Gmail is limiting sending; trying again later"
    room = room_today()
    if room <= 0:
        return "daily limit reached"
    return "started" if _start(_batch(min(room, c["perRun"]), c["followUps"], "🌐 Portfolio auto batch")) else "busy"


async def _batch(room: int, follow_ups: bool, heading: str) -> None:
    # replies first: never email someone who just answered; no inbox, no follow-ups
    try:
        await check_replies()
        unread = ""
    except gmail.ReadRefused as e:
        unread = str(e)
    except Exception as e:   # e.g. the mailbox's sign-in was revoked: follow-ups wait, the send will say more
        log.exception("Portfolio: couldn't read replies before sending")
        unread = f"{type(e).__name__}: {str(e)[:150]}"
    follow = due_follow_ups(room) if follow_ups and not unread else []
    first = pick_first_emails(room - len(follow))
    if not follow and not first:
        return
    async with keepalive.awake():
        sent_f, failed_f = await _send_all(follow, None)
        sent_n, failed_n = await _send_all(first, 0)
    lines = [f"{heading}, {now_local().strftime('%I:%M %p').lstrip('0')}"]
    for title, sent in ((f"New ({len(sent_n)}):", sent_n), (f"Follow-ups ({len(sent_f)}):", sent_f)):
        if sent:
            lines += [title] + [f"{i}. {p['name']} ({p.get('area') or '?'}): {p['to']}" for i, p in enumerate(sent, 1)]
    failed = failed_f + failed_n
    if failed:
        lines += ["", f"❌ {len(failed)} failed:"] + failed
    lines += ["", f"Today: {sent_today()} of {settings()['dailyCap']} portfolio emails used."]
    if unread:
        lines += ["", f"⏸ Follow-ups skipped: Gmail won't let me read the inbox to check for replies first. Google says: {unread}"]
    await telegram.send("\n".join(lines))


async def _send_all(targets: list[dict], step: int | None) -> tuple[list[dict], list[str]]:
    global _limited_until, _limited_reason
    sent, failed = [], []
    f1, f2 = settings()["followUpDays"]
    gaps = [f1, f2 - f1]
    sender = me()
    for i, p in enumerate(targets):
        if gmail_limited() or outreach_limited():
            break
        n = p.get("followUps", 0) + 1 if step is None else step
        email = portfolio_emails.render(n, p, sender)
        if n == 0 and not await mailer.accepts_email(p["to"]):
            portfolio.move(p["id"], p, "bounced", {"bounceReason": "domain doesn't receive email", "nextActionAt": None})
            failed.append(f"{p['name']} ({p['to']}): skipped, that domain doesn't receive email")
            continue
        try:
            msg_id, thread_id = await mailer.send(p["to"], email.subject, email.body, p.get("lastMessageId") if n else None,
                                                  p.get("threadId") if n else None, sender_name=sender["senderName"])
        except mailer.MailSetupError as e:
            failed.append(f"Stopped before sending anything: {e}")
            break
        except mailer.SendingLimited as e:
            _limited_until, _limited_reason = now_utc() + LIMITED_PAUSE, str(e)
            failed.append(f"⏸ Gmail is refusing to send right now; I'll try again in 30 minutes. Google says: {e}")
            break
        except Exception as e:
            log.exception("Portfolio send to %s failed", p["to"])
            failed.append(f"{p['name']} ({p['to']}): {type(e).__name__}: {str(e)[:120]}")
            if len(failed) >= 2 and not sent:
                failed.append("Stopped after 2 failures in a row; the rest weren't tried.")
                break
            continue
        _record(p, n, email, msg_id, thread_id, gaps)
        sent.append(p)
        if i < len(targets) - 1:
            await asyncio.sleep(random.uniform(*PAUSE_SECONDS))
    return sent, failed


def _record(p: dict, n: int, email, msg_id: str, thread_id: str, gaps: list[int]) -> None:
    now = now_utc()
    col("portfolio_messages").add({
        "prospectId": p["id"], "direction": "out", "to": p["to"], "subject": email.subject, "body": email.body,
        "messageId": msg_id, "threadId": thread_id, "followUpNo": n, "at": now.isoformat(),
    })
    portfolio.move(p["id"], p, "emailed", {
        "followUps": n, "lastContactAt": now.isoformat(), "lastMessageId": msg_id, "emailedTo": p["to"], "threadId": thread_id,
        "nextActionAt": (now + timedelta(days=gaps[n])).isoformat() if n < len(gaps) else None,
    })
    activity.log("email_sent", f"Portfolio: {'emailed' if n == 0 else f'follow-up {n} to'} {p['name']} ({p['to']})")


# ── replies ─────────────────────────────────────────────────────────────────

CLASSIFY = """A business replied to a cold email from an independent web developer offering to build their website.
Sort the reply into one kind:
- interested: wants a quote, a call, a meeting, examples, or says yes
- question: asks something specific (price, timeline, what's included) without saying yes or no
- not_now: polite no, already has someone, maybe later
- unsubscribe: asks to stop emailing, remove them, or is angry about the email
- other: anything else (auto-reply, out of office, wrong person)
Return JSON: {"kind": "<kind>", "summary": "<one short sentence of what they said>"}"""
STATUS_FOR = {"interested": "interested", "question": "replied", "not_now": "not_interested", "unsubscribe": "unsubscribed",
              "other": "replied"}


async def _classify(body: str) -> tuple[str, str]:
    try:
        raw = await llm.complete(CLASSIFY, [{"role": "user", "content": body or "(empty reply)"}], max_tokens=300, json=True)
        out = json.loads(raw)
        kind = out.get("kind") if out.get("kind") in STATUS_FOR else "other"
        return kind, str(out.get("summary", "")).strip()
    except usage.LimitReached:
        return "other", "(not sorted: today's AI limit is used up)"
    except (json.JSONDecodeError, AttributeError):
        return "other", ""


async def check_replies() -> int:
    """New replies and bounces in the portfolio mailbox, in threads Jarvis started. Returns how many.
    Raises gmail.ReadRefused when Gmail won't let us read."""
    if not gmail.enabled():
        return 0   # locally without the Gmail API: Presqio's IMAP check still sees the replies
    contacted = {d.to_dict().get("threadId"): {"id": d.id, **d.to_dict()} for d in
                 col("prospects").where(filter=FieldFilter("emailedTo", ">", "")).stream() if d.to_dict().get("threadId")}
    if not contacted:
        return 0
    state = col("meta").document("inbox-portfolio")
    seen: dict[str, str] = (state.get().to_dict() or {}).get("seen", {})
    mails = await gmail.thread_messages(LOOKBACK_DAYS, lambda mid, tid: tid in contacted and mid not in seen)
    me_address = get_settings().email_address.lower()
    handled = 0
    for mid, tid, raw in mails:
        m = inbox._parse(raw)
        p = contacted[tid]
        try:
            if m["from"] != me_address:   # our own sent follow-ups sit in the same thread
                if "mailer-daemon" in m["from"] or "postmaster" in m["from"]:
                    await _bounced(p, m)
                elif p.get("status") not in ("unsubscribed", "bounced"):
                    await _replied(p, m)
                handled += 1
        except Exception:
            log.exception("Portfolio: couldn't process mail from %s; will retry", m["from"])
            continue
        seen[mid] = now_utc().isoformat()
    cutoff = (now_utc() - timedelta(days=LOOKBACK_DAYS + 7)).isoformat()
    state.set({"seen": {k: v for k, v in seen.items() if v >= cutoff}, "updatedAt": now_utc().isoformat()})
    return handled


async def _replied(p: dict, m: dict) -> None:
    kind, summary = await _classify(m["body"])
    now = now_utc().isoformat()
    col("portfolio_messages").add({"prospectId": p["id"], "direction": "in", "from": m["from"], "subject": m["subject"],
                                   "body": m["body"], "messageId": m["messageId"], "kind": kind, "at": now})
    portfolio.move(p["id"], p, STATUS_FOR[kind], {"nextActionAt": None, "replySummary": summary, "repliedAt": now})
    if kind == "unsubscribe":
        col("dnc").document(m["from"]).set({"reason": "asked to stop (portfolio)", "business": p.get("name", ""), "createdAt": now})
    icon = {"interested": "🔥", "question": "❓", "not_now": "👋", "unsubscribe": "🚫", "other": "✉️"}[kind]
    label = {"interested": "is interested", "question": "has a question", "not_now": "said not now",
             "unsubscribe": "asked you to stop (blocked)", "other": "replied"}[kind]
    activity.log("reply", f"Portfolio: {p['name']} {label}: {summary}")
    snippet = m["body"][:600] + ("…" if len(m["body"]) > 600 else "")
    await telegram.send(f"🌐 {icon} {p['name']} ({p.get('area', '?')}) {label} about a website\nFrom: {m['from']}\n\n"
                        f"\"{snippet}\"\n\n{'Call them: ' + p['phone'] if p.get('phone') else 'Reply from your Gmail.'}")


async def _bounced(p: dict, m: dict) -> None:
    now = now_utc().isoformat()
    col("portfolio_messages").add({"prospectId": p["id"], "direction": "in", "from": m["from"], "subject": m["subject"],
                                   "body": m["body"][:500], "messageId": m["messageId"], "kind": "bounce", "at": now})
    portfolio.move(p["id"], p, "bounced", {"nextActionAt": None})
    activity.log("status_change", f"Portfolio email to {p['name']} bounced ({p.get('emailedTo')})")


def preview(pid: str) -> list[dict]:
    """The three emails this business would get, as they'd be sent now."""
    p = col("prospects").document(pid).get().to_dict()
    if not p:
        raise ValueError("That business isn't in the list any more.")
    labels = ["First email", "Follow-up 1", "Follow-up 2"]
    sender = me()
    to = p.get("emailedTo") or (p.get("emails") or [""])[0]
    return [{"label": labels[i], "to": to, **vars(portfolio_emails.render(i, p, sender))} for i in range(3)]


# ── for chat, voice and Telegram ────────────────────────────────────────────

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def set_auto(on: bool) -> str:
    save_settings({"enabled": on})
    return (f"🌐 Portfolio auto-send is ON: {auto_window()}. I'll message you after every batch." if on
            else "⏸ Portfolio auto-send is PAUSED. You can still say “send 3 website emails”.")


def auto_window() -> str:
    c = settings()
    days = c["days"]
    day_text = f"{WEEKDAYS[days[0]]}–{WEEKDAYS[days[-1]]}" if days == list(range(days[0], days[-1] + 1)) and len(days) > 2 \
        else ", ".join(WEEKDAYS[d] for d in days)
    return f"{c['perRun']} every 30 min, {c['from']}–{c['until']} {day_text}, up to {c['dailyCap']} a day"


def status_text() -> str:
    """The portfolio campaign in a few lines, for chat, Telegram and the voice briefing."""
    t = portfolio.totals()
    s = t["byStatus"]
    if not t["cities"]:
        return ("🌐 Portfolio: no businesses yet. They're collected during business searches; "
                "say “check websites of saved leads” to look through the leads you already have.")
    lines = [
        f"🌐 Portfolio (your web development offer): {sum(s.values())} businesses need a website.",
        f"To review {s.get('new', 0)}, approved {s.get('ready', 0)}, emailed {s.get('emailed', 0)}, "
        f"replied {s.get('replied', 0) + s.get('interested', 0)} (interested {s.get('interested', 0)}).",
        f"Today: {sent_today()} of {settings()['dailyCap']} portfolio emails sent "
        f"({_mailbox_sent_today()} of {prefs.sending()['dailyCap']} from the mailbox in all, Presqio included).",
        f"Auto-send: {'ON, ' + auto_window() if settings()['enabled'] else 'paused'}"
        f"{'; a batch is sending now' if busy() else ''}. Follow-ups due now: {len(due_follow_ups(100))}.",
    ]
    for c in t["cities"][:6]:
        groups = ", ".join(f"{site_label(g)} {n}" for g, n in sorted(c["toReviewByGroup"].items(), key=lambda x: -x[1]))
        lines.append(f"• {c['city']}: {c['total']} in all; to review: {groups or 'none'}; call list {c['callList']}")
    return "\n".join(lines)


def site_label(group: str) -> str:
    from . import site_check
    return site_check.GROUP_LABELS.get(group, group).lower()


def send_text(count: int) -> tuple[bool, str]:
    """"send 3 website emails" from chat/voice/Telegram -> (started, message)."""
    try:
        return True, "🌐 " + send_now(count)
    except ValueError as e:
        return False, f"⚠️ {e}"
