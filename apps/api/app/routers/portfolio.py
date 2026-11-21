"""The Portfolio page: businesses that need a website, and emailing them from Vinod's own Gmail."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..deps import require_user
from ..services import categories, portfolio, portfolio_outreach, site_check

router = APIRouter(prefix="/portfolio", tags=["portfolio"], dependencies=[Depends(require_user)])


class CollectIn(BaseModel):
    collect: bool


class CheckIn(BaseModel):
    restart: bool = False


class ReviewIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)
    approved: bool


class ApproveAllIn(BaseModel):
    city: str
    site: str | None = None
    category: str | None = None


class SendingIn(BaseModel):
    enabled: bool | None = None
    perRun: int | None = None
    dailyCap: int | None = None
    from_: str | None = Field(default=None, alias="from")
    until: str | None = None
    days: list[int] | None = None
    followUps: bool | None = None
    followUpDays: list[int] | None = None


class MeIn(BaseModel):
    senderName: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None


class SendNowIn(BaseModel):
    count: int = Field(ge=1, le=portfolio_outreach.MAX_PER_RUN)


def _overview() -> dict:
    return {
        "collect": portfolio.enabled(),
        "check": portfolio.check_state(),
        "cities": portfolio.cities(),
        "groups": [{"key": k, "label": site_check.GROUP_LABELS[k]} for k in site_check.GROUPS],
        "categories": [{"key": c.key, "label": c.label} for c in categories.CATEGORIES],
        "mailbox": portfolio_outreach.mailbox(),
        "sending": portfolio_outreach.settings(),
        "me": portfolio_outreach.me(),
        "sentToday": portfolio_outreach.sent_today(),
        "busy": portfolio_outreach.busy(),
        "limits": {"earliest": portfolio_outreach.EARLIEST, "latest": portfolio_outreach.LATEST,
                   "maxPerRun": portfolio_outreach.MAX_PER_RUN, "maxDaily": portfolio_outreach.MAX_DAILY},
    }


def _bad(e: ValueError) -> HTTPException:
    return HTTPException(422, str(e))


@router.get("")
def overview() -> dict:
    return _overview()


@router.get("/prospects")
def prospects(city: str, tab: Literal["review", "approved", "contacted", "closed"] = "review", site: str | None = None,
              reach: Literal["email", "call"] | None = None, category: str | None = None, after: str | None = None) -> dict:
    if site and site not in site_check.GROUPS:
        raise HTTPException(422, "Unknown group")
    if category and category not in categories.BY_KEY:
        raise HTTPException(422, "Unknown business category")
    return portfolio.list_prospects(city, tab, site, reach, category, after)


@router.post("/collect")
def set_collect(body: CollectIn) -> dict:
    portfolio.set_enabled(body.collect)
    return _overview()


@router.post("/check")
async def check_saved(body: CheckIn) -> dict:
    """Read the websites of every business already in Leads (in the background)."""
    if not portfolio.start_check(body.restart):
        raise HTTPException(409, "The website check is already running.")
    return _overview()


@router.post("/review")
def review(body: ReviewIn) -> dict:
    return {"changed": portfolio.set_review(body.ids, body.approved)}


@router.post("/approve-all")
def approve_all(body: ApproveAllIn) -> dict:
    return {"approved": portfolio.approve_all(body.city, body.site, body.category)}


@router.post("/sending")
def save_sending(body: SendingIn) -> dict:
    try:
        portfolio_outreach.save_settings(body.model_dump(by_alias=True))
    except ValueError as e:
        raise _bad(e)
    return _overview()


@router.post("/me")
def save_me(body: MeIn) -> dict:
    try:
        portfolio_outreach.save_me(body.model_dump())
    except ValueError as e:
        raise _bad(e)
    return _overview()


@router.post("/send-now")
async def send_now(body: SendNowIn) -> dict:
    try:
        return {"note": portfolio_outreach.send_now(body.count)}
    except ValueError as e:
        raise _bad(e)


@router.get("/{pid}/preview")
def preview(pid: str) -> dict:
    try:
        return {"emails": portfolio_outreach.preview(pid)}
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/{pid}/skip")
def skip(pid: str) -> dict:
    try:
        portfolio.skip(pid)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


@router.post("/{pid}/block")
def block(pid: str) -> dict:
    try:
        portfolio.block(pid)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}
