"""
Daily limits on Gemini usage, so Jarvis never uses up the free allowance.
Counters live in usage/{YYYY-MM-DD} (local date): one read and one write per use.
Change the limits with the *_PER_DAY settings in Render.
"""

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
# TomTom's free plan allows about 2,500 searches a day, counted by UTC date (it resets at
# 5:30 AM IST). Searches are counted in memory and written in batches, not one write each.

MAP_SEARCHES_PER_DAY = 2500
_unsaved_maps = 0


def _maps_doc():
    return col("usage").document(f"maps-{now_utc().date().isoformat()}")


def count_map_searches(n: int) -> None:
    global _unsaved_maps
    _unsaved_maps += n


def save_map_searches() -> None:
    """Write the searches counted since the last save (call at checkpoints)."""
    global _unsaved_maps
    n, _unsaved_maps = _unsaved_maps, 0
    if n:
        _maps_doc().set({"searches": Increment(n)}, merge=True)


def map_searches_today() -> int:
    snap = _maps_doc().get()
    return int((snap.to_dict() or {}).get("searches", 0)) + _unsaved_maps
