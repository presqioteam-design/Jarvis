"""The Settings page. Saved values override Render's environment from the next cron run.

Plain `def` endpoints: FastAPI runs them in a worker thread, so a busy moment elsewhere
(a sending batch or a scan doing database work) can't keep the page waiting."""

from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..deps import require_user
from ..services import categories, explore, outreach, prefs

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
