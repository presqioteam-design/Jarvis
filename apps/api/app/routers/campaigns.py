from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field

from ..deps import require_user
from ..services import leads

router = APIRouter(tags=["campaigns"], dependencies=[Depends(require_user)])


class CampaignIn(BaseModel):
    area: str = Field(min_length=2, max_length=120)          # e.g. "Madhapur, Hyderabad"
    radiusKm: float = Field(default=3, ge=0.5, le=10)


@router.post("/campaigns")
async def create_campaign(body: CampaignIn, background: BackgroundTasks):
    """Starts the search and returns at once; the dashboard watches the campaign in Firestore."""
    campaign_id = leads.create_campaign(body.area.strip(), int(body.radiusKm * 1000))
    background.add_task(leads.run_campaign, campaign_id)
    return {"id": campaign_id}


@router.post("/leads/{lead_id}/block")
async def block_lead(lead_id: str):
    leads.block(lead_id)
    return {"ok": True}
