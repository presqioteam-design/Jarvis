"""The Settings page. Saved values override Render's environment from the next cron run.

Plain `def` endpoints: FastAPI runs them in a worker thread, so a busy moment elsewhere
(a sending batch or a scan doing database work) can't keep the page waiting."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as dtime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..deps import require_user
from ..config import get_settings
from ..timeutil import now_local, now_utc
from ..services import categories, dbusage, explore, health, leads, outreach, prefs, templates, usage

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_user)])


_pool = ThreadPoolExecutor(max_workers=4)


def _sending_view() -> dict:
    # the two reads don't depend on each other: do them at the same time
    cfg_f, sent_f = _pool.submit(prefs.sending), _pool.submit(outreach.sent_today)
    cfg = cfg_f.result()
    return {
        "settings": cfg,
        "runsPerDay": prefs.runs_per_day(cfg),
        "sentToday": sent_f.result(),
        "limits": {"earliest": prefs.EARLIEST, "latest": prefs.LATEST, "maxPerRun": prefs.MAX_PER_RUN,
                   "maxDaily": prefs.MAX_DAILY, "days": prefs.DAYS},
    }


@router.get("/sending")
def get_sending():
    return _sending_view()


class SendingIn(BaseModel):
    enabled: bool | None = None
    perRun: int | None = Field(default=None, ge=1)
    dailyAuto: int | None = Field(default=None, ge=1)
    dailyCap: int | None = Field(default=None, ge=1)
    from_: str | None = Field(default=None, alias="from")
    until: str | None = None
    days: list[int] | None = None
    followUps: bool | None = None
    followUpDays: list[int] | None = Field(default=None, min_length=2, max_length=2)


@router.post("/sending")
def save_sending(body: SendingIn):
    patch = body.model_dump(by_alias=True)
    try:
        prefs.save_sending(patch)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return _sending_view()


# ── what to find ─────────────────────────────────────────────────────────────

def _finding_view() -> dict:
    cfg_f, queue_f, night_f = _pool.submit(prefs.finding), _pool.submit(explore.queue), _pool.submit(explore.night)
    night = night_f.result()
    return {
        "settings": cfg_f.result(),
        "categories": [{"key": c.key, "label": c.label} for c in categories.CATEGORIES],
        "maxAreasPerNight": prefs.MAX_AREAS_PER_NIGHT,
        "queue": queue_f.result(),
        "tonight": {"areas": night["areas"], "added": night["added"], "done": night["done"]},
    }


@router.get("/finding")
def get_finding():
    return _finding_view()


class FindingIn(BaseModel):
    categories: list[str] | None = Field(default=None, max_length=50)
    exploreEnabled: bool | None = None
    areasPerNight: int | None = None


@router.post("/finding")
def save_finding(body: FindingIn):
    try:
        prefs.save_finding(body.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e))
    return _finding_view()


class CityIn(BaseModel):
    city: str = Field(min_length=2, max_length=80)


@router.post("/explore/prioritise")
async def prioritise(body: CityIn):
    """Put a listed city first in line, or look up and add a new one."""
    note = await explore.prioritise(body.city.strip())
    if note.startswith("I couldn't"):
        raise HTTPException(422, note)
    return {"note": note.removeprefix("🌍 "), **_finding_view()}


class SkipIn(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    skipped: bool


@router.post("/explore/skip")
def skip(body: SkipIn):
    try:
        explore.set_skipped(body.id, body.skipped)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return _finding_view()


# ── emails ───────────────────────────────────────────────────────────────────

def _emails_view() -> dict:
    return {"settings": prefs.emails(), "categories": [{"key": c.key, "label": c.label} for c in categories.CATEGORIES]}


@router.get("/emails")
def get_emails():
    return _emails_view()


class EmailsIn(BaseModel):
    senderName: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=30)
    website: str | None = Field(default=None, max_length=200)


@router.post("/emails")
def save_emails(body: EmailsIn):
    try:
        prefs.save_emails(body.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e))
    return _emails_view()


class PreviewIn(EmailsIn):
    category: str = categories.DEFAULT
    name: str = Field(default="Sunrise Residency", max_length=120)
    area: str = Field(default="Madhapur", max_length=80)


@router.post("/emails/preview")
def preview(body: PreviewIn):
    """The three emails a business of this kind gets, with the details being edited (not yet saved)."""
    me = prefs.emails() | {k: v.strip() for k, v in body.model_dump(include={"senderName", "phone", "website"}).items() if v and v.strip()}
    out = []
    for step, when in ((0, "First email"), (1, "Follow-up 1"), (2, "Follow-up 2")):
        e = templates.render(step, body.name or "Sunrise Residency", body.area or "Madhapur", me["senderName"], body.category,
                             me["phone"], me["website"])
        out.append({"label": when, "subject": e.subject, "body": e.body})
    return {"emails": out, "from": f"{me['senderName']} <{get_settings().email_address}>"}


# ── do-not-contact list ──────────────────────────────────────────────────────

@router.get("/dnc")
def get_dnc():
    return leads.dnc_view()


class AddressIn(BaseModel):
    address: str = Field(min_length=3, max_length=200)


@router.post("/dnc/block")
def block(body: AddressIn):
    try:
        leads.block_address(body.address)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return leads.dnc_view()


class KeyIn(BaseModel):
    key: str = Field(min_length=3, max_length=200)


@router.post("/dnc/unblock")
def unblock(body: KeyIn):
    try:
        restored = leads.unblock(body.key.strip().lower())
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"restored": restored, **leads.dnc_view()}


# ── usage today ──────────────────────────────────────────────────────────────

@router.get("/usage")
def get_usage():
    tz = get_settings().tz
    midnight_ist = datetime.combine(now_local().date() + timedelta(days=1), dtime.min, tzinfo=tz).isoformat()
    midnight_utc = datetime.combine(now_utc().date() + timedelta(days=1), dtime.min, tzinfo=timezone.utc).isoformat()
    sent_f, ai_f, maps_f, db_f, cfg_f = (_pool.submit(outreach.sent_today), _pool.submit(usage.today),
                                         _pool.submit(usage.map_searches_today), _pool.submit(dbusage.today),
                                         _pool.submit(prefs.sending))
    ai = ai_f.result()
    meters = [
        {"key": "emails", "label": "Emails sent", "used": sent_f.result(), "limit": cfg_f.result()["dailyCap"], "resetsAt": midnight_ist,
         "note": "Your daily limit (Settings → Automatic sending)."},
        {"key": "ai", "label": "AI requests", "used": ai["ai"], "limit": usage.limit("ai"), "resetsAt": midnight_ist,
         "note": "Chat, sorting replies, voice notes. Kept well under Gemini's free allowance."},
        {"key": "voiceCalls", "label": "Voice calls", "used": ai["voiceCalls"], "limit": usage.limit("voiceCalls"), "resetsAt": midnight_ist,
         "note": "Talk to Jarvis."},
        {"key": "tts", "label": "Spoken replies", "used": ai["tts"], "limit": usage.limit("tts"), "resetsAt": midnight_ist,
         "note": "The voice note in the daily report."},
        {"key": "maps", "label": "Map searches", "used": maps_f.result(), "limit": usage.MAP_SEARCHES_PER_DAY, "resetsAt": midnight_utc,
         "note": "TomTom's free daily searches, used by scans and the night explorer."},
    ]
    return {"meters": meters, "database": db_f.result()}


# ── voice and AI limits ──────────────────────────────────────────────────────

def _ai_view() -> dict:
    limits_f, used_f = _pool.submit(prefs.ai_limits), _pool.submit(usage.today)
    used = used_f.result()
    return {
        "settings": limits_f.result(),
        "bounds": {k: {"min": lo, "max": hi} for k, (lo, hi) in prefs.AI_BOUNDS.items()},
        "usedToday": {"voiceCallsPerDay": used["voiceCalls"], "aiPerDay": used["ai"], "ttsPerDay": used["tts"]},
    }


@router.get("/ai")
def get_ai():
    return _ai_view()


class AiIn(BaseModel):
    voiceCallsPerDay: int | None = None
    minutesPerCall: int | None = None
    aiPerDay: int | None = None
    ttsPerDay: int | None = None


@router.post("/ai")
def save_ai(body: AiIn):
    try:
        prefs.save_ai_limits(body.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e))
    return _ai_view()


# ── connections and account ──────────────────────────────────────────────────

@router.get("/connections")
async def get_connections(refresh: bool = False):
    result = await health.check(force=refresh)
    return {**result, "chatHours": prefs.chat_hours(), "chatHoursOptions": prefs.CHAT_HOURS}


@router.post("/connections/tomtom")
async def check_tomtom():
    return await health.check_tomtom()


class ChatHoursIn(BaseModel):
    hours: int


@router.post("/chat-history")
def save_chat_history(body: ChatHoursIn):
    try:
        return {"chatHours": prefs.save_chat_hours(body.hours)}
    except ValueError as e:
        raise HTTPException(422, str(e))
