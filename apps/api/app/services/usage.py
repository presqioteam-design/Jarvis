"""
Daily limits on Gemini usage, so Jarvis never uses up the free allowance.
Counters live in usage/{YYYY-MM-DD} (local date): one read and one write per use.
Change the limits with the *_PER_DAY settings in Render.
"""

from google.cloud.firestore_v1 import Increment

from ..config import get_settings
from ..firebase import col
from ..timeutil import now_local

LABELS = {"voiceCalls": "voice calls", "ai": "AI requests", "tts": "spoken replies"}


class LimitReached(Exception):
    def __init__(self, kind: str):
        self.kind = kind
        super().__init__(f"Today's limit of {limit(kind)} {LABELS[kind]} is used up. It resets at midnight.")


def limit(kind: str) -> int:
    s = get_settings()
    return {"voiceCalls": s.voice_calls_per_day, "ai": s.ai_requests_per_day, "tts": s.tts_per_day}[kind]


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
