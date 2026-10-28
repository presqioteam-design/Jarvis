"""
Leads: scanning a city or area for hotels, and keeping per-area totals.

A scan covers the place's map box with squares. TomTom returns at most 100
hotels per search, so a square that comes back full is split into four and
searched again. Progress is saved on the campaign, so a stopped scan resumes.
"""

import logging
import math
import re
from collections import Counter, defaultdict

import httpx
from google.cloud.firestore_v1.base_query import FieldFilter

from ..firebase import col, db
from ..timeutil import now_utc
from . import activity, crawler, sources, telegram

log = logging.getLogger(__name__)
SAME_PLACE_M = 200      # two results this close with similar names are one hotel
START_SQUARE_KM = 3     # first grid size; full squares are split down to MIN_SQUARE_KM
MIN_SQUARE_KM = 0.15
SAVE_EVERY = 10         # squares between progress saves


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "other"


def area_key(city: str, area: str) -> str:
    return f"{slug(city)}--{slug(area)}"


# ── reads ────────────────────────────────────────────────────────────────────
# Area totals live in one doc per city (cities/{city}), so the dashboard and
# Jarvis read 1 document instead of every lead. Free Firestore allows 50k reads a day.

def city_doc(city: str):
    return col("cities").document(slug(city))


def areas(city: str | None = None) -> list[dict]:
    docs = [city_doc(city).get()] if city else list(col("cities").stream())
    return [a for d in docs if d.exists for a in (d.to_dict().get("areas") or {}).values()]


def status_counts() -> dict[str, int]:
    """Totals across all cities."""
    total: Counter = Counter()
    for d in col("cities").stream():
        total.update(d.to_dict().get("statuses", {}))
    return dict(total)


def by_status(status: str, limit: int = 20) -> list[dict]:
    docs = col("leads").where(filter=FieldFilter("status", "==", status)).limit(limit).stream()
    return [{"id": d.id, **d.to_dict()} for d in docs]


# ── campaign ─────────────────────────────────────────────────────────────────

def create_campaign(place: str, radius_m: int | None) -> str:
    """radius_m=None scans the whole city/town; otherwise a square around the spot."""
    _, ref = col("campaigns").add({
        "name": place,
        "kind": "area" if radius_m else "city",
        "area": {"label": place, "lat": 0, "lon": 0, "radiusM": radius_m or 0},
        "query": "hotel",
        "status": "searching",
        "createdAt": now_utc().isoformat(),
        "stats": {"found": 0, "withEmail": 0, "withPhone": 0, "emailed": 0, "replied": 0, "interested": 0},
        "scan": {"phase": "map", "queue": [], "squaresDone": 0, "found": 0},
    })
    return ref.id


async def run_campaign(campaign_id: str) -> None:
    """Background task. Safe to call again on a stopped campaign: it resumes."""
    ref = col("campaigns").document(campaign_id)
    camp = ref.get().to_dict()
    try:
        city = camp.get("city")
        if not city:
            place = await sources.geocode(camp["area"]["label"])
            radius = camp["area"]["radiusM"]
            box = square_around(place["lat"], place["lon"], radius) if radius else place["box"]
            city = place["city"]
            camp["scan"]["queue"] = grid(box, START_SQUARE_KM)
            camp["box"], camp["name"] = box, place["label"]
            ref.update({
                "city": city, "box": box, "name": place["label"],
                "area": {"label": place["label"], "lat": place["lat"], "lon": place["lon"], "radiusM": radius},
                "scan.queue": camp["scan"]["queue"],
            })

        scan = camp["scan"]
        if scan["phase"] == "map":
            await scan_squares(ref, scan, campaign_id, city)
            scan["phase"] = "osm"
            ref.update({"scan.phase": "osm"})
        if scan["phase"] == "osm":
            add_osm(await sources.osm_hotels(camp["box"]), campaign_id, city)
            ref.update({"scan.phase": "websites"})
        await crawl_city(city)

        totals = recompute_areas(city)
        ref.update({
            "status": "ready", "scan.phase": "done",
            "stats.found": totals["total"], "stats.withEmail": totals["withEmail"], "stats.withPhone": totals["withPhone"],
        })
        text = (
            f"Scan of {camp['name']} finished: {totals['total']} hotels in "
            f"{totals['areas']} areas, {totals['withEmail']} with email, {totals['withPhone']} with phone."
        )
        activity.log("lead_found", text)
        await telegram.send(f"🏨 {text}")
    except Exception as e:
        log.exception("Campaign %s failed", campaign_id)
        msg = str(e) if isinstance(e, ValueError) else "Search stopped. Start it again to resume."
        ref.update({"status": "failed", "error": msg})
        activity.log("error", f"Scan of {camp['area']['label']} stopped: {msg}")


def square_around(lat: float, lon: float, radius_m: int) -> dict:
    dlat = radius_m / 111_000
    dlon = radius_m / (111_000 * math.cos(math.radians(lat)))
    return {"n": lat + dlat, "s": lat - dlat, "w": lon - dlon, "e": lon + dlon}


def grid(box: dict, km: float) -> list[dict]:
    """Split a box into squares about `km` wide."""
    rows = max(1, math.ceil((box["n"] - box["s"]) * 111 / km))
    cols = max(1, math.ceil((box["e"] - box["w"]) * 111 * math.cos(math.radians(box["s"])) / km))
    h, w = (box["n"] - box["s"]) / rows, (box["e"] - box["w"]) / cols
    return [
        {"n": box["n"] - r * h, "s": box["n"] - (r + 1) * h, "w": box["w"] + c * w, "e": box["w"] + (c + 1) * w}
        for r in range(rows) for c in range(cols)
    ]


def width_km(box: dict) -> float:
    return (box["e"] - box["w"]) * 111 * math.cos(math.radians(box["s"]))


async def scan_squares(ref, scan: dict, campaign_id: str, city: str) -> None:
    queue = scan["queue"]
    async with httpx.AsyncClient(timeout=30) as client:
        while queue:
            box = queue.pop(0)
            hotels = await sources.tomtom_box(client, box)
            if len(hotels) >= 100 and width_km(box) > MIN_SQUARE_KM:
                queue.extend(grid(box, width_km(box) / 2))
            scan["found"] += upsert(hotels, campaign_id, city)
            scan["squaresDone"] += 1
            if scan["squaresDone"] % SAVE_EVERY == 0 or not queue:
                ref.update({"scan.queue": queue, "scan.squaresDone": scan["squaresDone"], "scan.found": scan["found"]})


def upsert(hotels: list[dict], campaign_id: str, city: str) -> int:
    """Create new leads; for known ones only fill missing details. Returns how many were new."""
    hotels = [h for h in hotels if h["name"]]
    if not hotels:
        return 0
    refs = [col("leads").document(h["id"]) for h in hotels]
    known = {s.id: s.to_dict() for s in db().get_all(refs) if s.exists}
    blocked = {d.id for d in col("dnc").stream()} if len(known) < len(hotels) else set()
    now = now_utc().isoformat()
    batch, new = db().batch(), 0

    for h, doc in zip(hotels, refs):
        area = h["area"] or "Other"
        place = {"city": city, "area": area, "areaKey": area_key(city, area)}
        contact = {"phone": h["phone"], "website": h["website"], "emails": h["emails"]}
        if h["id"] in known:
            old = known[h["id"]]
            patch = {k: v for k, v in {**contact, **place}.items() if v and not old.get(k)}
            if patch.get("emails"):
                patch["hasEmail"] = True
            if patch:
                batch.update(doc, {**patch, "updatedAt": now})
            continue
        is_blocked = any(k in blocked for k in [*h["emails"], re.sub(r"\D", "", h["phone"])] if k)
        batch.set(doc, {
            "campaignId": campaign_id, "name": h["name"], "address": h["address"], "lat": h["lat"], "lon": h["lon"],
            **place, **contact, "hasEmail": bool(h["emails"]), "source": h["source"],
            "status": "unsubscribed" if is_blocked else ("new" if h["emails"] or h["phone"] else "no_contact"),
            "crawled": not h["website"], "followUps": 0, "createdAt": now, "updatedAt": now,
        })
        new += 1
    batch.commit()
    return new


def add_osm(osm: list[dict], campaign_id: str, city: str) -> None:
    """Add OpenStreetMap hotels the map scan missed; give them the nearest known area."""
    known = [d.to_dict() | {"id": d.id} for d in col("leads").where(filter=FieldFilter("city", "==", city)).select(["name", "lat", "lon", "area", "phone"]).stream()]
    cells = defaultdict(list)
    for k in known:
        cells[(round(k["lat"], 2), round(k["lon"], 2))].append(k)

    def near(h):
        lat, lon = round(h["lat"], 2), round(h["lon"], 2)
        return [k for dl in (-0.01, 0, 0.01) for dn in (-0.01, 0, 0.01) for k in cells[(round(lat + dl, 2), round(lon + dn, 2))]]

    fresh = []
    for h in osm:
        around = near(h)
        if any(same_hotel(k, h) for k in around):
            continue
        if not h["area"]:
            closest = min(around, key=lambda k: distance_m(k, h), default=None)
            h["area"] = closest["area"] if closest and distance_m(closest, h) < 1500 else ""
        fresh.append(h)
    for i in range(0, len(fresh), 200):
        upsert(fresh[i:i + 200], campaign_id, city)


async def crawl_city(city: str) -> None:
    """Visit websites not yet read; promote no_contact leads that gained an email or phone."""
    todo = [d for d in col("leads").where(filter=FieldFilter("city", "==", city)).where(filter=FieldFilter("crawled", "==", False)).stream()]
    leads_by_site = defaultdict(list)
    for d in todo:
        lead = d.to_dict()
        if lead.get("website") and not crawler.is_aggregator(lead["website"]):
            leads_by_site[lead["website"]].append((d.reference, lead))
    found = await crawler.crawl_many(list(leads_by_site))
    now = now_utc().isoformat()
    batch, pending = db().batch(), 0
    for d in todo:
        lead = d.to_dict()
        info = found.get(lead.get("website", ""), {})
        emails = [e for e in lead.get("emails") or info.get("emails", []) if crawler.usable(e)]
        phone = lead.get("phone") or info.get("phone", "")
        patch = {"crawled": True, "emails": emails, "hasEmail": bool(emails), "phone": phone, "updatedAt": now}
        if lead["status"] == "no_contact" and (emails or phone):
            patch["status"] = "new"
        batch.update(d.reference, patch)
        pending += 1
        if pending >= 400:
            batch.commit()
            batch, pending = db().batch(), 0
    if pending:
        batch.commit()


def area_summary(rows: list[dict], city: str) -> dict:
    statuses = Counter(l["status"] for l in rows)
    return {
        "city": city, "area": rows[0]["area"], "total": len(rows),
        "withEmail": sum(1 for l in rows if l.get("emails")), "withPhone": sum(1 for l in rows if l.get("phone")),
        "statuses": dict(statuses),
    }


def write_city(city: str, area_map: dict) -> dict:
    statuses: Counter = Counter()
    for a in area_map.values():
        statuses.update(a["statuses"])
    totals = {
        "total": sum(a["total"] for a in area_map.values()),
        "withEmail": sum(a["withEmail"] for a in area_map.values()),
        "withPhone": sum(a["withPhone"] for a in area_map.values()),
    }
    city_doc(city).set({"city": city, "areas": area_map, "statuses": dict(statuses), **totals, "updatedAt": now_utc().isoformat()})
    return {**totals, "areas": len(area_map)}


def recompute_areas(city: str) -> dict:
    """Rebuild a city's totals from every lead. Run after a scan, not after small edits."""
    groups: dict[str, list] = defaultdict(list)
    unflagged = []
    for d in col("leads").where(filter=FieldFilter("city", "==", city)).select(["area", "areaKey", "status", "emails", "phone", "hasEmail"]).stream():
        l = d.to_dict()
        groups[l["areaKey"]].append(l)
        if l.get("emails") and not l.get("hasEmail"):
            unflagged.append(d.reference)
    for i in range(0, len(unflagged), 400):
        batch = db().batch()
        for r in unflagged[i:i + 400]:
            batch.update(r, {"hasEmail": True})
        batch.commit()
    return write_city(city, {k: area_summary(rows, city) for k, rows in groups.items()})


def recompute_area(key: str) -> None:
    """Refresh one area's totals (reads only that area's leads)."""
    rows = [d.to_dict() for d in col("leads").where(filter=FieldFilter("areaKey", "==", key)).select(["area", "city", "status", "emails", "phone"]).stream()]
    ref = col("cities").document(key.split("--")[0])
    snap = ref.get()
    if not snap.exists:
        return
    doc = snap.to_dict()
    area_map = doc.get("areas") or {}
    if rows:
        area_map[key] = area_summary(rows, doc["city"])
    else:
        area_map.pop(key, None)
    write_city(doc["city"], area_map)


def recompute_area_of(lead_ids: list[str]) -> None:
    keys = {s.to_dict().get("areaKey") for s in db().get_all([col("leads").document(i) for i in lead_ids]) if s.exists}
    for key in filter(None, keys):
        recompute_area(key)


# ── duplicates ───────────────────────────────────────────────────────────────

def same_hotel(a: dict, b: dict) -> bool:
    if a.get("phone") and a.get("phone") == b.get("phone"):
        return True
    return norm(a["name"]) == norm(b["name"]) and distance_m(a, b) < SAME_PLACE_M


def norm(name: str) -> str:
    name = re.sub(r"\b(hotel|hotels|the|inn|residency|suites?|by oyo|oyo \d+)\b", " ", name.lower())
    return re.sub(r"[^a-z0-9]", "", name)


def distance_m(a: dict, b: dict) -> float:
    dlat = math.radians(b["lat"] - a["lat"])
    dlon = math.radians(b["lon"] - a["lon"]) * math.cos(math.radians(a["lat"]))
    return 6_371_000 * math.hypot(dlat, dlon)


# ── admin actions ────────────────────────────────────────────────────────────

def set_status(lead_ids: list[str], status: str) -> None:
    now = now_utc().isoformat()
    batch = db().batch()
    for i in lead_ids:
        batch.update(col("leads").document(i), {"status": status, "updatedAt": now})
    batch.commit()
    recompute_area_of(lead_ids)


def find_area(name: str) -> dict | None:
    """'hitech city' -> that area's summary (with city and key), matching loosely."""
    want = slug(name.split(",")[0])
    for d in col("cities").stream():
        for key, a in (d.to_dict().get("areas") or {}).items():
            if slug(a["area"]) == want:
                return {**a, "key": key}
    for d in col("cities").stream():   # second pass: partial match, e.g. "jubilee" for "Jubliee Hills"
        for key, a in (d.to_dict().get("areas") or {}).items():
            if want in slug(a["area"]) or slug(a["area"]) in want:
                return {**a, "key": key}
    return None


def list_leads(area_key_: str | None, status: str, limit: int = 20) -> list[dict]:
    """Up to `limit` leads with this status, those with an email first. Equality filters only."""
    out: list[dict] = []
    for has_email in (True, False):
        q = col("leads").where(filter=FieldFilter("status", "==", status)).where(filter=FieldFilter("hasEmail", "==", has_email))
        if area_key_:
            q = q.where(filter=FieldFilter("areaKey", "==", area_key_))
        out += [{"id": d.id, **d.to_dict()} for d in q.limit(limit - len(out)).stream()]
        if len(out) >= limit:
            break
    return out


def approve_all_with_email(city: str, area: str | None) -> int:
    q = (col("leads").where(filter=FieldFilter("city", "==", city))
         .where(filter=FieldFilter("status", "==", "new")).where(filter=FieldFilter("hasEmail", "==", True)))
    if area:
        q = q.where(filter=FieldFilter("areaKey", "==", area_key(city, area)))
    refs = [d.reference for d in q.select(["areaKey"]).stream()]
    now = now_utc().isoformat()
    for i in range(0, len(refs), 400):
        batch = db().batch()
        for r in refs[i:i + 400]:
            batch.update(r, {"status": "ready", "updatedAt": now})
        batch.commit()
    if refs:
        recompute_area_of([r.id for r in refs])
        activity.log("status_change", f"Approved {len(refs)} hotels with email in {area or city}.")
    return len(refs)


def block(lead_id: str) -> None:
    """Never contact this hotel again (adds its email and phone to the do-not-contact list)."""
    ref = col("leads").document(lead_id)
    lead = ref.get().to_dict() or {}
    keys = [*lead.get("emails", []), re.sub(r"\D", "", lead.get("phone", ""))]
    now = now_utc().isoformat()
    for k in filter(None, keys):
        col("dnc").document(k.lower()).set({"reason": "blocked by admin", "createdAt": now})
    ref.update({"status": "unsubscribed", "updatedAt": now})
    recompute_area_of([lead_id])
    activity.log("status_change", f"Blocked {lead.get('name', lead_id)}: will never be contacted.", lead_id)


def mark_searching(campaign_id: str) -> None:
    col("campaigns").document(campaign_id).update({"status": "searching", "error": None})
