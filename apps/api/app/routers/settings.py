"""The Settings page. Saved values override Render's environment from the next cron run.

Plain `def` endpoints: FastAPI runs them in a worker thread, so a busy moment elsewhere
(a sending batch or a scan doing database work) can't keep the page waiting."""

from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..deps import require_user
from ..services import outreach, prefs

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
