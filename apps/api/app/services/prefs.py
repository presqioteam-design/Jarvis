"""
Settings the admin changes on the Settings page, stored in settings/main next to the
Telegram switches. Render's environment gives the defaults; a value saved here wins,
so a change takes effect on the next cron run without a redeploy. One read per use.
"""

import re
import time

from ..config import get_settings
from ..firebase import col
from . import categories

# The tick cron runs every 30 min, 9:30 AM–8 PM IST, Monday–Saturday (apps/cron/wrangler.toml),
# so sending can only happen inside that.
EARLIEST, LATEST = "09:30", "20:00"
DAYS = [0, 1, 2, 3, 4, 5]   # Monday–Saturday (Python weekday numbers)
# kept below what a free Gmail account can send safely
MAX_PER_RUN, MAX_DAILY = 20, 150


def ref():
    return col("settings").document("main")


# The settings doc is read on every AI request and cron run: keep it for 30 s instead of
# re-reading each time. Saving here clears it at once; changes made elsewhere show within 30 s.
_cached: tuple[float, dict] | None = None


def _doc() -> dict:
    global _cached
    if _cached and time.monotonic() - _cached[0] < 30:
        return _cached[1]
    _cached = (time.monotonic(), ref().get().to_dict() or {})
    return _cached[1]


def forget() -> None:
    global _cached
    _cached = None


def _save(data: dict) -> None:
    ref().set(data, merge=True)
    forget()


def sending() -> dict:
    """The sending settings in effect: saved values over Render's defaults."""
    s = get_settings()
    doc = _doc()
    saved = doc.get("sending") or {}
    return {
        "enabled": doc.get("autoSend", True),
        "perRun": saved.get("perRun", s.auto_send_per_run),
        "dailyAuto": saved.get("dailyAuto", s.auto_daily_cap),
        "dailyCap": saved.get("dailyCap", s.daily_email_cap),
        "from": saved.get("from", s.auto_send_from),
        "until": saved.get("until", s.auto_send_until),
        "days": saved.get("days", DAYS),
        "followUps": saved.get("followUps", True),
        "followUpDays": saved.get("followUpDays", [3, 7]),
    }


def runs_per_day(cfg: dict) -> int:
    """How many 30-minute cron runs fall inside the window (both ends included)."""
    def minutes(t: str) -> int:
        h, m = map(int, t.split(":"))
        return h * 60 + m
    start, end = minutes(cfg["from"]), minutes(cfg["until"])
    first = -(-start // 30) * 30   # the cron fires on :00 and :30
    return max(0, (end - first) // 30 + 1) if end >= first else 0


def save_sending(patch: dict) -> dict:
    """Validate and save; raises ValueError with a sentence for the page."""
    cfg = sending() | {k: v for k, v in patch.items() if v is not None}
    for k in ("from", "until"):
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(cfg[k])):
            raise ValueError("Times look like 10:00.")
    if not (EARLIEST <= cfg["from"] < cfg["until"] <= LATEST):
        raise ValueError(f"Sending hours must be between {EARLIEST} and {LATEST}, and start before they end.")
    if not 1 <= int(cfg["perRun"]) <= MAX_PER_RUN:
        raise ValueError(f"Emails per run must be 1 to {MAX_PER_RUN}.")
    if not 1 <= int(cfg["dailyCap"]) <= MAX_DAILY:
        raise ValueError(f"The daily limit must be 1 to {MAX_DAILY}.")
    if not 1 <= int(cfg["dailyAuto"]) <= int(cfg["dailyCap"]):
        raise ValueError("Automatic emails a day can't be more than the daily limit.")
    days = sorted({int(d) for d in cfg["days"]})
    if not days or any(d not in DAYS for d in days):
        raise ValueError("Pick at least one day, Monday to Saturday.")
    f1, f2 = (int(d) for d in cfg["followUpDays"])
    if not (1 <= f1 < f2 <= 30):
        raise ValueError("Follow-ups: the second must come after the first, within 30 days.")
    saved = {
        "perRun": int(cfg["perRun"]), "dailyAuto": int(cfg["dailyAuto"]), "dailyCap": int(cfg["dailyCap"]),
        "from": cfg["from"], "until": cfg["until"], "days": days,
        "followUps": bool(cfg["followUps"]), "followUpDays": [f1, f2],
    }
    _save({"sending": saved, **({"autoSend": bool(patch["enabled"])} if patch.get("enabled") is not None else {})})
    return sending()


# ── what to find ─────────────────────────────────────────────────────────────
# Kinds switched off are stored (not the ones on), so a kind added later starts switched on.
MAX_AREAS_PER_NIGHT = 10   # ~160 TomTom searches an area at most; TomTom's free plan allows ~2,500 a day


def finding() -> dict:
    doc = _doc()
    saved = doc.get("finding") or {}
    off = set(saved.get("off", []))
    return {
        "categories": [c.key for c in categories.CATEGORIES if c.key not in off],
        "exploreEnabled": doc.get("exploreEnabled", True),
        "areasPerNight": saved.get("areasPerNight", get_settings().explore_areas_per_night),
    }


def enabled_categories() -> list[categories.Category]:
    on = set(finding()["categories"])
    return [c for c in categories.CATEGORIES if c.key in on]


def save_finding(patch: dict) -> dict:
    cfg = finding() | {k: v for k, v in patch.items() if v is not None}
    keys = [c.key for c in categories.CATEGORIES]
    on = [k for k in cfg["categories"] if k in keys]
    if not on:
        raise ValueError("Keep at least one kind of business switched on.")
    areas = int(cfg["areasPerNight"])
    if not 1 <= areas <= MAX_AREAS_PER_NIGHT:
        raise ValueError(f"Areas a night must be 1 to {MAX_AREAS_PER_NIGHT} (the free map searches allow about that many).")
    _save({"finding": {"off": [k for k in keys if k not in on], "areasPerNight": areas},
           **({"exploreEnabled": bool(patch["exploreEnabled"])} if patch.get("exploreEnabled") is not None else {})})
    return finding()


# ── emails: who they're from ─────────────────────────────────────────────────

def emails() -> dict:
    from . import presqio   # presqio reads these settings too
    saved = _doc().get("emails") or {}
    return {
        "senderName": saved.get("senderName", get_settings().sender_name),
        "phone": saved.get("phone", presqio.PHONE),
        "website": saved.get("website", presqio.WEBSITE),
    }


def save_emails(patch: dict) -> dict:
    cfg = emails() | {k: v.strip() for k, v in patch.items() if isinstance(v, str)}
    if not 2 <= len(cfg["senderName"]) <= 60:
        raise ValueError("The sender name must be 2 to 60 characters.")
    if not re.fullmatch(r"\+?[\d ()-]{8,20}", cfg["phone"]) or len(re.sub(r"\D", "", cfg["phone"])) < 8:
        raise ValueError("Enter a phone number like +91 63093 87321.")
    if not re.fullmatch(r"https?://[^\s/$.?#][^\s]*\.[^\s]{2,}", cfg["website"]):
        raise ValueError("Enter the website as a full address, like https://presqio.pages.dev.")
    _save({"emails": cfg})
    return emails()


# ── voice and AI limits ──────────────────────────────────────────────────────
# Upper bounds stay inside Gemini's free allowance; a Live voice call can't run past 15 minutes.
AI_BOUNDS = {"voiceCallsPerDay": (1, 30), "minutesPerCall": (1, 15), "aiPerDay": (50, 1500), "ttsPerDay": (0, 20)}


def ai_limits() -> dict:
    s, saved = get_settings(), _doc().get("ai") or {}
    return {
        "voiceCallsPerDay": saved.get("voiceCallsPerDay", s.voice_calls_per_day),
        "minutesPerCall": saved.get("minutesPerCall", s.voice_minutes_per_call),
        "aiPerDay": saved.get("aiPerDay", s.ai_requests_per_day),
        "ttsPerDay": saved.get("ttsPerDay", s.tts_per_day),
    }


def save_ai_limits(patch: dict) -> dict:
    cfg = ai_limits() | {k: int(v) for k, v in patch.items() if v is not None}
    names = {"voiceCallsPerDay": "Voice calls a day", "minutesPerCall": "Minutes per call",
             "aiPerDay": "AI requests a day", "ttsPerDay": "Spoken replies a day"}
    for k, (lo, hi) in AI_BOUNDS.items():
        if not lo <= cfg[k] <= hi:
            raise ValueError(f"{names[k]} must be {lo} to {hi}.")
    _save({"ai": {k: cfg[k] for k in AI_BOUNDS}})
    return ai_limits()
