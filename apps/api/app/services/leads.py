"""
Leads: scanning a city or area for one category of business, and keeping per-area totals.

A scan covers the place's map box with squares. TomTom returns at most 100
results per search, so a square that comes back full is split into four and
searched again. Progress is saved on the campaign, so a stopped scan resumes.

Jarvis only emails, so a business is saved only when an email is found for it
(on the map, or on its own website, read before saving).
"""

import logging
import math
from datetime import timedelta
import re
from collections import Counter, defaultdict

import httpx
from google.api_core.exceptions import ResourceExhausted
from google.cloud.firestore_v1.base_query import FieldFilter

from ..firebase import col, db
from ..timeutil import now_utc
from . import activity, categories, crawler, keepalive, prefs, sources, telegram

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
# Free Firestore allows 50k reads and 20k writes a day. A whole-city scan of a
# big city uses most of that, so: one city scan a day, one scan at a time.

QUOTA_STOPPED = "Firestore's free daily limit was reached. Progress is saved: press Resume after 12:30 PM IST."
# TomTom's free plan allows about 2,500 searches a day and the night explorer uses up to ~950 of them.
# Searching every category costs ~25 searches per square, so a big scan pauses here and resumes later.
SCAN_SEARCH_BUDGET = 1300
TOMTOM_STOPPED = ("Paused to stay within TomTom's free daily map searches. Progress is saved: "
                  "press Resume tomorrow to carry on from here.")


class ScanPaused(Exception):
    pass


def scan_blocked(whole_city: bool) -> str:
    """Why a new scan can't start right now, or "" if it can."""
    camps = [d.to_dict() for d in col("campaigns").stream()]
    if any(c.get("status") == "searching" for c in camps):
        return "Another scan is still running. Wait for it to finish (Jarvis messages you on Telegram)."
    if whole_city:
        day_ago = (now_utc() - timedelta(hours=24)).isoformat()
        if any(c.get("kind") == "city" and c.get("createdAt", "") >= day_ago for c in camps):
            return ("A whole-city scan already ran in the last 24 hours. To stay within the free database limit, "
                    "scan one city a day. Search around a spot instead, or try again tomorrow.")
    return ""


def create_campaign(place: str, radius_m: int | None, category: str = categories.ALL) -> str:
    """radius_m=None scans the whole city/town; otherwise a square around the spot."""
    _, ref = col("campaigns").add({
        "name": place,
        "kind": "area" if radius_m else "city",
        "area": {"label": place, "lat": 0, "lon": 0, "radiusM": radius_m or 0},
        "category": category if category == categories.ALL else categories.get(category).key,
        "query": category,
        "status": "searching",
        "createdAt": now_utc().isoformat(),
        "stats": {"found": 0, "withEmail": 0, "withPhone": 0, "emailed": 0, "replied": 0, "interested": 0},
        "scan": {"phase": "map", "queue": [], "squaresDone": 0, "found": 0},
    })
    return ref.id


async def run_campaign(campaign_id: str) -> None:
    """Background task. Safe to call again on a stopped campaign: it resumes."""
    async with keepalive.awake():
        await _run_campaign(campaign_id)


async def _run_campaign(campaign_id: str) -> None:
    ref = col("campaigns").document(campaign_id)
    camp = ref.get().to_dict()
    # "all" means the kinds switched on in Settings; naming one kind always works
    named = camp.get("category") not in (None, categories.ALL)
    cats = categories.resolve(camp.get("category")) if named else prefs.enabled_categories()
    what = categories.label_of(camp.get("category"))
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
            await scan_squares(ref, scan, campaign_id, city, cats)
            scan["phase"] = "osm"
            ref.update({"scan.phase": "osm"})
        if scan["phase"] == "osm":
            await add_osm(await sources.osm_places(camp["box"], cats), campaign_id, city, camp["box"])
            ref.update({"scan.phase": "websites"})

        if camp.get("kind") == "area":
            # a spot search only touches nearby areas: don't re-read the whole city
            nearby = leads_in_box(camp["box"], ["areaKey", "emails", "phone", "name", "area", "city", "category"])
            merge_search_index(city, [l for l in nearby if l.get("city") == city])
            for key in {l["areaKey"] for l in nearby if l.get("areaKey")}:
                recompute_area(key)
            totals = {
                "total": len(nearby), "withEmail": sum(1 for l in nearby if l.get("emails")),
                "withPhone": sum(1 for l in nearby if l.get("phone")),
                "areas": len({l.get("areaKey") for l in nearby}),
            }
        else:
            totals = recompute_areas(city)
        ref.update({
            "status": "ready", "scan.phase": "done",
            "stats.found": totals["total"], "stats.withEmail": totals["withEmail"], "stats.withPhone": totals["withPhone"],
        })
        new = scan.get("found", 0)
        text = (
            f"Scan of {camp['name']} for {what} finished: {new} new with an email. "
            f"The area now has {totals['withEmail']} businesses to email across {totals['areas']} areas."
        )
        activity.log("lead_found", text)
        await telegram.send(f"🔎 {text}")
    except ScanPaused:
        ref.update({"status": "failed", "error": TOMTOM_STOPPED})
        await telegram.send(f"⏸ Scan of {camp['name']}: {TOMTOM_STOPPED}")
    except ResourceExhausted:
        ref.update({"status": "failed", "error": QUOTA_STOPPED})
        await telegram.send(f"⏸ Scan of {camp['name']} paused: {QUOTA_STOPPED}")
    except Exception as e:
        log.exception("Campaign %s failed", campaign_id)
        msg = str(e) if isinstance(e, ValueError) else "Search stopped. Start it again to resume."
        ref.update({"status": "failed", "error": msg})
        activity.log("error", f"Scan of {camp['area']['label']} stopped: {msg}")


def leads_in_box(box: dict, fields: list[str]) -> list[dict]:
    """Leads inside a map box. One range filter (latitude) needs no composite index; longitude is checked here."""
    q = (col("leads").where(filter=FieldFilter("lat", ">=", box["s"])).where(filter=FieldFilter("lat", "<=", box["n"]))
         .select(sorted({*fields, "lon"})))
    return [d.to_dict() | {"id": d.id} for d in q.stream() if box["w"] <= d.to_dict().get("lon", 999) <= box["e"]]


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


async def scan_squares(ref, scan: dict, campaign_id: str, city: str, cats: list[categories.Category]) -> None:
    """Every category in each square. Raises ScanPaused (progress saved) when this run's share of
    TomTom's free daily searches is used, or TomTom refuses; Resume carries on from the same square."""
    queue, pending, searches = scan["queue"], [], 0

    async def checkpoint():
        nonlocal pending
        # save what these squares found before recording progress, so a resume doesn't lose it
        scan["found"] += len(await save_reachable(pending, campaign_id, city))
        pending = []
        ref.update({"scan.queue": queue, "scan.squaresDone": scan["squaresDone"], "scan.found": scan["found"]})

    async with httpx.AsyncClient(timeout=30) as client:
        while queue:
            box = queue.pop(0)
            # a smaller square only repeats the categories that filled its parent (usually restaurants)
            todo = [c for c in cats if not box.get("only") or c.key in box["only"]]
            found, full_keys = [], []
            try:
                for cat in todo:
                    places, full = await sources.tomtom_box(client, box, cat)
                    searches += len(cat.tomtom)
                    found += places
                    if full:
                        full_keys.append(cat.key)
            except sources.TomTomLimit:
                queue.insert(0, box)   # do this square again on resume
                await checkpoint()
                raise ScanPaused()
            if full_keys and width_km(box) > MIN_SQUARE_KM:
                queue.extend(sq | {"only": full_keys} for sq in grid(box, width_km(box) / 2))
            pending += found
            scan["squaresDone"] += 1
            if scan["squaresDone"] % SAVE_EVERY == 0 or not queue or searches >= SCAN_SEARCH_BUDGET:
                await checkpoint()
            if queue and searches >= SCAN_SEARCH_BUDGET:
                raise ScanPaused()


async def save_reachable(found: list[dict], campaign_id: str, city: str, fallback_area: str = "") -> list[dict]:
    """Save the businesses we can email, and return the saved rows.

    Websites are read first and only businesses with an email are written: Jarvis can only email,
    and this keeps database writes (and reads, which happen only for these) low. Businesses already
    saved, and addresses on the do-not-contact list, are skipped."""
    places = {h["id"]: h for h in found if h["name"] and (h["emails"] or h["website"])}
    sites = list({h["website"] for h in places.values() if not h["emails"] and not crawler.is_aggregator(h["website"])})
    crawled = await crawler.crawl_many(sites) if sites else {}
    reachable = []
    for h in places.values():
        info = crawled.get(h["website"], {})
        emails = [e for e in (h["emails"] or info.get("emails", [])) if crawler.usable(e)]
        if emails:
            reachable.append(h | {"emails": emails, "phone": h["phone"] or info.get("phone", "")})
    if not reachable:
        return []

    refs = [col("leads").document(h["id"]) for h in reachable]
    known = {snap.id for i in range(0, len(refs), 300) for snap in db().get_all(refs[i:i + 300]) if snap.exists}
    blocked = {d.id for d in col("dnc").stream()}
    # the same business can come from both maps under different ids: match on the email
    new_emails = sorted({e for h in reachable if h["id"] not in known for e in h["emails"]})
    saved_emails = set()
    for i in range(0, len(new_emails), 30):   # Firestore allows 30 values per array-contains-any
        q = col("leads").where(filter=FieldFilter("emails", "array_contains_any", new_emails[i:i + 30])).select(["emails"])
        saved_emails |= {e for d in q.stream() for e in d.to_dict().get("emails", [])}
    now = now_utc().isoformat()
    rows, used, batch = [], set(saved_emails), db().batch()
    for h in reachable:
        # one lead per address: branches sharing a website would otherwise get the same email twice
        if h["id"] in known or any(e in blocked or e in used for e in h["emails"]):
            continue
        used.update(h["emails"])
        area = h["area"] or fallback_area or "Other"
        row = {
            "campaignId": campaign_id, "name": h["name"], "address": h["address"], "lat": h["lat"], "lon": h["lon"],
            "city": city, "area": area, "areaKey": area_key(city, area), "category": h.get("category", categories.DEFAULT),
            "phone": h["phone"], "website": h["website"], "emails": h["emails"], "hasEmail": True, "source": h["source"],
            "status": "new", "crawled": True, "followUps": 0, "createdAt": now, "updatedAt": now,
        }
        batch.set(col("leads").document(h["id"]), row)
        rows.append(row | {"id": h["id"]})
        if len(rows) % 400 == 0:
            batch.commit()
            batch = db().batch()
    batch.commit()
    return rows


async def add_osm(osm: list[dict], campaign_id: str, city: str, box: dict) -> None:
    """Add OpenStreetMap places the map scan missed; give them the nearest known area."""
    if not osm:
        return
    known = leads_in_box(box, ["name", "lat", "area", "phone"])
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
        await save_reachable(fresh[i:i + 200], campaign_id, city)


def area_summary(rows: list[dict], city: str) -> dict:
    statuses = Counter(l["status"] for l in rows)
    return {
        "city": city, "area": rows[0]["area"], "total": len(rows),
        "withEmail": sum(1 for l in rows if l.get("emails")), "withPhone": sum(1 for l in rows if l.get("phone")),
        "statuses": dict(statuses),
        "categories": dict(Counter(l.get("category") or categories.DEFAULT for l in rows)),
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
    everyone = []
    for d in col("leads").where(filter=FieldFilter("city", "==", city)).select(["name", "area", "areaKey", "status", "emails", "phone", "hasEmail", "category"]).stream():
        l = d.to_dict()
        everyone.append(l | {"id": d.id})
        groups[l["areaKey"]].append(l)
        if l.get("emails") and not l.get("hasEmail"):
            unflagged.append(d.reference)
    for i in range(0, len(unflagged), 400):
        batch = db().batch()
        for r in unflagged[i:i + 400]:
            batch.update(r, {"hasEmail": True})
        batch.commit()
    write_search_index(city, everyone)
    return write_city(city, {k: area_summary(rows, city) for k, rows in groups.items()})


# ── search list ──────────────────────────────────────────────────────────────
# Firestore can't search inside text, so each city keeps a compact list of
# every lead (id, name, email, phone, area) in a few docs. The dashboard loads
# it once and searches in the browser: no reads while typing.

SEARCH_SHARD = 2500   # entries per doc, well under Firestore's 1 MiB doc limit


def search_entry(l: dict) -> dict:
    return {"i": l["id"], "n": l.get("name", ""), "e": (l.get("emails") or [""])[0], "p": l.get("phone", ""), "a": l.get("area", ""),
            "c": l.get("category") or categories.DEFAULT}


def write_search_index(city: str, rows: list[dict]) -> None:
    entries = sorted((search_entry(l) for l in rows), key=lambda e: e["n"].lower())
    shards = [entries[i:i + SEARCH_SHARD] for i in range(0, len(entries), SEARCH_SHARD)] or [[]]
    batch = db().batch()
    for n, part in enumerate(shards):
        batch.set(col("search").document(f"{slug(city)}-{n}"), {"city": city, "part": n, "entries": part, "updatedAt": now_utc().isoformat()})
    batch.commit()
    # drop shards left over from a bigger list
    for d in col("search").where(filter=FieldFilter("city", "==", city)).select(["part"]).stream():
        if d.to_dict().get("part", 0) >= len(shards):
            d.reference.delete()


def merge_search_index(city: str, rows: list[dict]) -> None:
    """Add or update a few leads without re-reading the whole city."""
    if not rows:
        return
    current = {}
    for d in col("search").where(filter=FieldFilter("city", "==", city)).stream():
        for e in d.to_dict().get("entries", []):
            current[e["i"]] = e
    for l in rows:
        current[l["id"]] = search_entry(l)
    write_search_index(city, [{"id": e["i"], "name": e["n"], "emails": [e["e"]] if e["e"] else [], "phone": e["p"], "area": e["a"],
                               "category": e.get("c")} for e in current.values()])


def recompute_area(key: str) -> None:
    """Refresh one area's totals (reads only that area's leads)."""
    rows = [d.to_dict() for d in col("leads").where(filter=FieldFilter("areaKey", "==", key)).select(["area", "city", "status", "emails", "phone", "category"]).stream()]
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


def approve_all_with_email(city: str, area: str | None, category: str | None = None) -> int:
    q = (col("leads").where(filter=FieldFilter("city", "==", city))
         .where(filter=FieldFilter("status", "==", "new")).where(filter=FieldFilter("hasEmail", "==", True)))
    if area:
        q = q.where(filter=FieldFilter("areaKey", "==", area_key(city, area)))
    if category:
        q = q.where(filter=FieldFilter("category", "==", category))
    refs = [d.reference for d in q.select(["areaKey"]).stream()]
    now = now_utc().isoformat()
    for i in range(0, len(refs), 400):
        batch = db().batch()
        for r in refs[i:i + 400]:
            batch.update(r, {"status": "ready", "updatedAt": now})
        batch.commit()
    if refs:
        recompute_area_of([r.id for r in refs])
        activity.log("status_change", f"Approved {len(refs)} businesses with email in {area or city}.")
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


def interrupted() -> list[str]:
    """Scans left "searching" by a restart (every deploy restarts Render and kills running tasks)."""
    return [d.id for d in col("campaigns").where(filter=FieldFilter("status", "==", "searching")).select(["status"]).stream()]


def mark_searching(campaign_id: str) -> None:
    col("campaigns").document(campaign_id).update({"status": "searching", "error": None})
