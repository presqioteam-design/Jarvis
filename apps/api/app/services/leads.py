"""Leads: running a campaign (search → dedupe → crawl → save) and read helpers."""

import logging
import math
import re
from collections import Counter

from google.cloud.firestore_v1.base_query import FieldFilter

from ..firebase import col, db
from ..timeutil import now_utc
from . import activity, crawler, sources, telegram

log = logging.getLogger(__name__)
SAME_PLACE_M = 200   # two results this close with similar names are one hotel


def status_counts() -> dict[str, int]:
    return dict(Counter(d.to_dict().get("status", "new") for d in col("leads").stream()))


def by_status(status: str, limit: int = 20) -> list[dict]:
    docs = col("leads").where(filter=FieldFilter("status", "==", status)).limit(limit).stream()
    return [{"id": d.id, **d.to_dict()} for d in docs]


# ── campaign run ─────────────────────────────────────────────────────────────

def create_campaign(area: str, radius_m: int) -> str:
    now = now_utc().isoformat()
    _, ref = col("campaigns").add({
        "name": f"Hotels in {area}",
        "area": {"label": area, "lat": 0, "lon": 0, "radiusM": radius_m},
        "query": "hotel",
        "status": "searching",
        "createdAt": now,
        "stats": {"found": 0, "withEmail": 0, "withPhone": 0, "emailed": 0, "replied": 0, "interested": 0},
    })
    return ref.id


async def run_campaign(campaign_id: str) -> None:
    """Background task: fills the campaign with leads. Records failures on the campaign."""
    ref = col("campaigns").document(campaign_id)
    camp = ref.get().to_dict()
    try:
        place = await sources.geocode(camp["area"]["label"])
        radius = camp["area"]["radiusM"]
        ref.update({"area": {**place, "radiusM": radius}, "name": f"Hotels in {place['label']}"})

        found = merge(
            await sources.tomtom_hotels(place["lat"], place["lon"], radius),
            await sources.osm_hotels(place["lat"], place["lon"], radius),
        )
        sites = [h["website"] for h in found if h["website"] and not h["emails"] and not crawler.is_aggregator(h["website"])]
        crawled = await crawler.crawl_many(sites)
        for h in found:
            info = crawled.get(h["website"], {})
            h["emails"] = [e for e in h["emails"] or info.get("emails", []) if not crawler.is_aggregator(e)]
            h["phone"] = h["phone"] or info.get("phone", "")

        new, with_email, with_phone = save_leads(found, campaign_id)
        ref.update({
            "status": "ready",
            "stats.found": len(found),
            "stats.withEmail": with_email,
            "stats.withPhone": with_phone,
        })
        text = (
            f"Found {len(found)} hotels in {place['label']} ({new} new): "
            f"{with_email} with email, {with_phone} with phone."
        )
        activity.log("lead_found", text)
        await telegram.send(f"🏨 {text}\nReview them on the dashboard → Leads.")
    except Exception as e:
        log.exception("Campaign %s failed", campaign_id)
        msg = str(e) if isinstance(e, ValueError) else "Search failed. Try again in a minute."
        ref.update({"status": "failed", "error": msg})
        activity.log("error", f"Campaign '{camp['area']['label']}' failed: {msg}")


def merge(primary: list[dict], extra: list[dict]) -> list[dict]:
    """Drop duplicates within and across sources, filling gaps from the duplicate."""
    out: list[dict] = []
    for h in primary + extra:
        if not h["name"]:
            continue
        twin = next((o for o in out if same_hotel(o, h)), None)
        if twin is None:
            out.append(h)
            continue
        for field in ("phone", "website", "address"):
            twin[field] = twin[field] or h[field]
        twin["emails"] = twin["emails"] or h["emails"]
    return out


def same_hotel(a: dict, b: dict) -> bool:
    if a["phone"] and a["phone"] == b["phone"]:
        return True
    return norm(a["name"]) == norm(b["name"]) and distance_m(a, b) < SAME_PLACE_M


def norm(name: str) -> str:
    name = re.sub(r"\b(hotel|hotels|the|inn|residency|suites?|by oyo|oyo \d+)\b", " ", name.lower())
    return re.sub(r"[^a-z0-9]", "", name)


def distance_m(a: dict, b: dict) -> float:
    dlat = math.radians(b["lat"] - a["lat"])
    dlon = math.radians(b["lon"] - a["lon"]) * math.cos(math.radians(a["lat"]))
    return 6_371_000 * math.hypot(dlat, dlon)


def save_leads(hotels: list[dict], campaign_id: str) -> tuple[int, int, int]:
    """Create new leads; on re-runs only fill missing contact details. -> (new, with_email, with_phone)"""
    blocked = {d.id for d in col("dnc").stream()}
    existing = {d.id: d.to_dict() for d in col("leads").where(filter=FieldFilter("campaignId", "==", campaign_id)).stream()}
    now = now_utc().isoformat()
    batch, pending, new = db().batch(), 0, 0

    for h in hotels:
        doc = col("leads").document(h["id"])
        contact = {"phone": h["phone"], "website": h["website"], "emails": h["emails"]}
        if h["id"] in existing:
            old = existing[h["id"]]
            patch = {k: v for k, v in contact.items() if v and not old.get(k)}
            if not patch:
                continue
            batch.update(doc, {**patch, "updatedAt": now})
        else:
            if not doc.get().exists:   # might belong to another campaign already
                is_blocked = any(k in blocked for k in [*h["emails"], re.sub(r"\D", "", h["phone"])] if k)
                batch.set(doc, {
                    "campaignId": campaign_id,
                    "name": h["name"],
                    "address": h["address"],
                    "lat": h["lat"],
                    "lon": h["lon"],
                    **contact,
                    "source": h["source"],
                    "status": "unsubscribed" if is_blocked else ("new" if h["emails"] or h["phone"] else "no_contact"),
                    "followUps": 0,
                    "createdAt": now,
                    "updatedAt": now,
                })
                new += 1
            else:
                continue
        pending += 1
        if pending >= 400:
            batch.commit()
            batch, pending = db().batch(), 0
    if pending:
        batch.commit()

    return new, sum(1 for h in hotels if h["emails"]), sum(1 for h in hotels if h["phone"])


def block(lead_id: str) -> None:
    """Never contact this hotel again (adds its email and phone to the do-not-contact list)."""
    ref = col("leads").document(lead_id)
    lead = ref.get().to_dict() or {}
    keys = [*lead.get("emails", []), re.sub(r"\D", "", lead.get("phone", ""))]
    now = now_utc().isoformat()
    for k in filter(None, keys):
        col("dnc").document(k.lower()).set({"reason": "blocked by admin", "createdAt": now})
    ref.update({"status": "unsubscribed", "updatedAt": now})
    activity.log("status_change", f"Blocked {lead.get('name', lead_id)}: will never be contacted.", lead_id)

