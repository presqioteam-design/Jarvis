"""
Daily limits on Gemini usage, so Jarvis never uses up the free allowance.
Counters live in usage/{YYYY-MM-DD} (local date): one read and one write per use.
Change the limits with the *_PER_DAY settings in Render.
"""

from datetime import timedelta

from google.cloud.firestore_v1 import Increment

from ..config import get_settings
from ..firebase import col
from ..timeutil import now_local, now_utc

LABELS = {"voiceCalls": "voice calls", "ai": "AI requests", "tts": "spoken replies"}


class LimitReached(Exception):
    def __init__(self, kind: str):
        self.kind = kind
        super().__init__(f"Today's limit of {limit(kind)} {LABELS[kind]} is used up. It resets at midnight.")


def limit(kind: str) -> int:
    from . import prefs   # prefs reads categories, which come after this module loads
    a = prefs.ai_limits()
    return {"voiceCalls": a["voiceCallsPerDay"], "ai": a["aiPerDay"], "tts": a["ttsPerDay"]}[kind]


def _doc():
    return col("usage").document(now_local().date().isoformat())


def today() -> dict[str, int]:
    snap = _doc().get()
    data = snap.to_dict() or {} if snap.exists else {}
    return {k: int(data.get(k, 0)) for k in LABELS}


def take(kind: str) -> int:
    """Count one use, or raise LimitReached. Returns how many are left after this one."""
    used = today()[kind]
    if used >= limit(kind):
        raise LimitReached(kind)
    _doc().set({kind: Increment(1)}, merge=True)
    return limit(kind) - used - 1


def summary() -> str:
    used = today()
    return " · ".join(f"{LABELS[k]} {used[k]}/{limit(k)}" for k in LABELS)


# ── map searches (TomTom) ────────────────────────────────────────────────────
# TomTom's free (Freemium) plan allows 2,500 Search API requests a MONTH. Jarvis once assumed a day,
# and a few busy days used the whole month. Now each day gets a fair share of what's left this month:
# (allowance - reserve - used before today) / days left, counting today. A quiet day leaves more for
# the next ones. When today's share is used, searches carry on with OpenStreetMap alone.
# Counted by UTC month and date; searches are counted in memory and written in batches.
# (Looking a place up by name uses TomTom's Geocoding API, a separate 20,000 a month: not counted.)

MAP_SEARCHES_PER_MONTH = 2500
MAP_RESERVE = 100          # never plan to the last search: TomTom's count and ours can differ a little
_unsaved_maps = 0
_today: dict = {}          # {"date", "allowed", "used"}: worked out once a day, then counted in memory


def _maps_doc():
    return col("usage").document(f"maps-{now_utc().date().isoformat()}")


def _month_doc():
    return col("usage").document(f"maps-month-{now_utc().strftime('%Y-%m')}")


def count_map_searches(n: int) -> None:
    global _unsaved_maps
    _unsaved_maps += n
    if _today.get("date") == now_utc().date().isoformat():
        _today["used"] += n


def save_map_searches() -> None:
    """Write the searches counted since the last save (call at checkpoints)."""
    global _unsaved_maps
    n, _unsaved_maps = _unsaved_maps, 0
    if n:
        _maps_doc().set({"searches": Increment(n)}, merge=True)
        _month_doc().set({"searches": Increment(n)}, merge=True)


def map_searches_today() -> int:
    snap = _maps_doc().get()
    return int((snap.to_dict() or {}).get("searches", 0)) + _unsaved_maps


def map_searches_this_month() -> int:
    snap = _month_doc().get()
    return int((snap.to_dict() or {}).get("searches", 0)) + _unsaved_maps


def _days_left_in_month() -> int:
    today = now_utc().date()
    first_of_next = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    return (first_of_next - today).days      # counting today


def _refresh_today() -> None:
    """Two reads, once a day per server."""
    date = now_utc().date().isoformat()
    if _today.get("date") == date:
        return
    used_today = int((_maps_doc().get().to_dict() or {}).get("searches", 0)) + _unsaved_maps
    month = int((_month_doc().get().to_dict() or {}).get("searches", 0)) + _unsaved_maps
    left = max(0, MAP_SEARCHES_PER_MONTH - MAP_RESERVE - (month - used_today))
    _today.update(date=date, allowed=left // _days_left_in_month(), used=used_today)


def mark_month_used_up() -> None:
    """TomTom says there are no credits left: count this month as used, so no more TomTom searches are
    tried until the month changes (our count can start late, or miss searches made elsewhere)."""
    _month_doc().set({"searches": MAP_SEARCHES_PER_MONTH, "usedUpAt": now_utc().isoformat()}, merge=True)
    _today.update(date=now_utc().date().isoformat(), allowed=0, used=_today.get("used", 0))


def map_allowance_today() -> int:
    """Today's share of the month's TomTom searches."""
    _refresh_today()
    return _today["allowed"]


def map_searches_left_today() -> int:
    _refresh_today()
    return max(0, _today["allowed"] - _today["used"])
