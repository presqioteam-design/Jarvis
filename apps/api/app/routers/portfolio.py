"""The Portfolio page: businesses that need a website, for marketing Vinod's web development work."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..deps import require_user
from ..services import categories, portfolio, site_check

router = APIRouter(prefix="/portfolio", tags=["portfolio"], dependencies=[Depends(require_user)])


class CollectIn(BaseModel):
    collect: bool


class CheckIn(BaseModel):
    restart: bool = False


def _overview() -> dict:
    return {
        "collect": portfolio.enabled(),
        "check": portfolio.check_state(),
        "cities": portfolio.cities(),
        "groups": [{"key": k, "label": site_check.GROUP_LABELS[k]} for k in site_check.GROUPS],
        "categories": [{"key": c.key, "label": c.label} for c in categories.CATEGORIES],
    }


@router.get("")
def overview() -> dict:
    return _overview()


@router.get("/prospects")
def prospects(city: str, site: str | None = None, reach: Literal["email", "call"] | None = None,
              category: str | None = None, after: str | None = None) -> dict:
    if site and site not in site_check.GROUPS:
        raise HTTPException(422, "Unknown group")
    if category and category not in categories.BY_KEY:
        raise HTTPException(422, "Unknown business category")
    return portfolio.list_prospects(city, site, reach, category, after)


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
