from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field

from ..deps import require_user
from ..services import leads

router = APIRouter(tags=["campaigns"], dependencies=[Depends(require_user)])


class CampaignIn(BaseModel):
    place: str = Field(min_length=2, max_length=120)         # "Hyderabad" or "Madhapur, Hyderabad"
    radiusKm: float | None = Field(default=None, ge=0.5, le=10)   # None = whole city


class StatusIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    status: Literal["new", "ready", "not_interested"]


@router.post("/campaigns")
async def create_campaign(body: CampaignIn, background: BackgroundTasks):
    """Starts the scan and returns at once; the dashboard watches the campaign in Firestore."""
    radius = int(body.radiusKm * 1000) if body.radiusKm else None
    campaign_id = leads.create_campaign(body.place.strip(), radius)
    background.add_task(leads.run_campaign, campaign_id)
    return {"id": campaign_id}


@router.post("/campaigns/{campaign_id}/resume")
async def resume_campaign(campaign_id: str, background: BackgroundTasks):
    leads.mark_searching(campaign_id)
    background.add_task(leads.run_campaign, campaign_id)
    return {"ok": True}


@router.post("/leads/status")
async def set_status(body: StatusIn):
    leads.set_status(body.ids, body.status)
    return {"ok": True}


@router.post("/leads/{lead_id}/block")
async def block_lead(lead_id: str):
    leads.block(lead_id)
    return {"ok": True}
