"""
Settings the admin changes on the Settings page, stored in settings/main next to the
Telegram switches. Render's environment gives the defaults; a value saved here wins,
so a change takes effect on the next cron run without a redeploy. One read per use.
"""

import re

from ..config import get_settings
from ..firebase import col

# The tick cron runs every 30 min, 9:30 AM–8 PM IST, Monday–Saturday (apps/cron/wrangler.toml),
# so sending can only happen inside that.
EARLIEST, LATEST = "09:30", "20:00"
DAYS = [0, 1, 2, 3, 4, 5]   # Monday–Saturday (Python weekday numbers)
# kept below what a free Gmail account can send safely
MAX_PER_RUN, MAX_DAILY = 20, 150


def ref():
    return col("settings").document("main")


def sending() -> dict:
    """The sending settings in effect: saved values over Render's defaults."""
    s = get_settings()
    doc = ref().get().to_dict() or {}
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
    ref().set({"sending": saved, **({"autoSend": bool(patch["enabled"])} if patch.get("enabled") is not None else {})}, merge=True)
    return sending()
