"""
The night explorer: Jarvis finds India's biggest cities and their areas on
OpenStreetMap, then searches a few areas every night (cron, 12:30–5 AM IST)
for every business category, and saves only businesses it can email.

Built to stay inside the free limits:
- one small doc per city in explore/{city}: name, position, its areas and their progress
  (area["cats"] lists the categories already searched there, so new categories get
  searched in areas explored before)
- per area and category: a 4 km square on TomTom (at most MAX_SQUARES_PER_CATEGORY calls),
  website reads before saving, database writes only for businesses with an email
- EXPLORE_AREAS_PER_NIGHT areas a night (default 6); the summary goes to Telegram
  in the morning (with the first daytime cron run), not at 3 AM
"""

import asyncio
import logging
import math
import re
from collections import Counter
from datetime import datetime

import httpx
from google.cloud.firestore_v1.base_query import FieldFilter

from ..config import get_settings
from ..firebase import col, db
from ..timeutil import now_local, now_utc
from . import activity, categories, keepalive, leads, prefs, sources, telegram, usage

log = logging.getLogger(__name__)
OVERPASS = ["https://maps.mail.ru/osm/tools/overpass/api/interpreter", "https://overpass-api.de/api/interpreter",
            "https://overpass.private.coffee/api/interpreter"]
TOP_CITIES = 50
AREA_RADIUS_M = 2000          # each area search covers a 4 km square
AREA_SPACING_KM = 2.0         # areas closer than this to one already listed are skipped (they'd overlap)
MAX_AREAS_PER_CITY = 80
MAX_SQUARES_PER_CATEGORY = 6  # dense centres split into many small squares; this caps TomTom calls per category
LATIN = re.compile(r"^[A-Za-z0-9 .,'()&/-]+$")
_running: asyncio.Task | None = None


# ── OpenStreetMap ────────────────────────────────────────────────────────────

OVERPASS_BUDGET_S = 120   # give up on OpenStreetMap after this and use the fallback


async def overpass(query: str) -> list[dict]:
    """Public Overpass servers are often busy or down: try them, but never for more than two minutes.
    (wait_for would wait for a stuck connection to finish cancelling; this walks away at once.)"""
    task = asyncio.ensure_future(_overpass(query))
    done, _ = await asyncio.wait({task}, timeout=OVERPASS_BUDGET_S)
    if task in done and not task.exception():
        return task.result()
    task.cancel()
    raise RuntimeError("OpenStreetMap servers are busy")


async def _overpass(query: str, attempts: int = 2) -> list[dict]:
    async with httpx.AsyncClient(timeout=60, headers={"User-Agent": "presqio-jarvis/0.1"}) as client:
        for attempt in range(attempts):
            for url in OVERPASS:
                try:
                    r = await client.post(url, data={"data": query})
                    if r.status_code == 200:
                        return r.json()["elements"]
                except (httpx.HTTPError, ValueError):
                    pass
            await asyncio.sleep(5 * (attempt + 1))
    raise RuntimeError("OpenStreetMap servers are busy; will retry next time")


def english_name(tags: dict) -> str:
    name = (tags.get("name:en") or tags.get("name") or "").strip()
    return name if LATIN.match(name) and len(name) <= 40 else ""


def population(tags: dict) -> int:
    digits = re.sub(r"[^\d]", "", tags.get("population", ""))
    return int(digits) if digits else 0


def city_radius_km(pop: int) -> int:
    return 20 if pop > 5_000_000 else 15 if pop > 2_000_000 else 12 if pop > 1_000_000 else 8


# Used when OpenStreetMap is unreachable: India's biggest cities (name, lat, lon, population).
FALLBACK_CITIES = [
    ("Mumbai", 19.076, 72.8777, 12_400_000), ("Delhi", 28.6139, 77.209, 11_000_000), ("Bengaluru", 12.9716, 77.5946, 8_400_000),
    ("Hyderabad", 17.385, 78.4867, 6_800_000), ("Ahmedabad", 23.0225, 72.5714, 5_600_000), ("Chennai", 13.0827, 80.2707, 4_600_000),
    ("Kolkata", 22.5726, 88.3639, 4_500_000), ("Surat", 21.1702, 72.8311, 4_500_000), ("Pune", 18.5204, 73.8567, 3_100_000),
    ("Jaipur", 26.9124, 75.7873, 3_000_000), ("Lucknow", 26.8467, 80.9462, 2_800_000), ("Kanpur", 26.4499, 80.3319, 2_700_000),
    ("Nagpur", 21.1458, 79.0882, 2_400_000), ("Indore", 22.7196, 75.8577, 1_960_000), ("Thane", 19.2183, 72.9781, 1_840_000),
    ("Bhopal", 23.2599, 77.4126, 1_800_000), ("Visakhapatnam", 17.6868, 83.2185, 1_730_000), ("Patna", 25.5941, 85.1376, 1_680_000),
    ("Vadodara", 22.3072, 73.1812, 1_670_000), ("Ghaziabad", 28.6692, 77.4538, 1_640_000), ("Ludhiana", 30.901, 75.8573, 1_610_000),
    ("Agra", 27.1767, 78.0081, 1_580_000), ("Nashik", 19.9975, 73.7898, 1_480_000), ("Faridabad", 28.4089, 77.3178, 1_410_000),
    ("Meerut", 28.9845, 77.7064, 1_310_000), ("Rajkot", 22.3039, 70.8022, 1_290_000), ("Varanasi", 25.3176, 82.9739, 1_200_000),
    ("Srinagar", 34.0837, 74.7973, 1_180_000), ("Aurangabad", 19.8762, 75.3433, 1_170_000), ("Amritsar", 31.634, 74.8723, 1_130_000),
    ("Navi Mumbai", 19.033, 73.0297, 1_120_000), ("Prayagraj", 25.4358, 81.8463, 1_110_000), ("Ranchi", 23.3441, 85.3096, 1_070_000),
    ("Coimbatore", 11.0168, 76.9558, 1_060_000), ("Jabalpur", 23.1815, 79.9864, 1_050_000), ("Gwalior", 26.2183, 78.1828, 1_050_000),
    ("Vijayawada", 16.5062, 80.648, 1_040_000), ("Jodhpur", 26.2389, 73.0243, 1_030_000), ("Madurai", 9.9252, 78.1198, 1_020_000),
    ("Raipur", 21.2514, 81.6296, 1_010_000), ("Kota", 25.2138, 75.8648, 1_000_000), ("Guwahati", 26.1445, 91.7362, 960_000),
    ("Chandigarh", 30.7333, 76.7794, 960_000), ("Mysuru", 12.2958, 76.6394, 920_000), ("Bhubaneswar", 20.2961, 85.8245, 840_000),
    ("Kochi", 9.9312, 76.2673, 680_000), ("Thiruvananthapuram", 8.5241, 76.9366, 960_000), ("Dehradun", 30.3165, 78.0322, 580_000),
    ("Udaipur", 24.5854, 73.7125, 450_000), ("Goa", 15.4909, 73.8278, 400_000),
]


async def city_list() -> list[tuple[str, float, float, int]]:
    """India's cities by population from OpenStreetMap, or the built-in list if it's unreachable."""
    try:
        elements = await overpass('[out:json][timeout:80];node["place"="city"]["population"](6.5,68.0,35.7,97.5);out;')
    except RuntimeError:
        log.warning("Overpass unreachable; using the built-in city list")
        return FALLBACK_CITIES
    india = [e for e in elements if e.get("tags", {}).get("is_in:country", "India") in ("India", "IN") and english_name(e["tags"])]
    ranked = sorted(india, key=lambda e: -population(e["tags"]))
    return [(english_name(e["tags"]), e["lat"], e["lon"], population(e["tags"])) for e in ranked] or FALLBACK_CITIES


async def build_cities() -> int:
    """The top cities by population. Cities already scanned as a whole are marked done."""
    ranked = await city_list()
    whole_city_scans = {d.to_dict().get("city") for d in col("campaigns").stream() if d.to_dict().get("kind") == "city"}
    listed = [(c["lat"], c["lon"]) for c in (d.to_dict() for d in col("explore").stream())]
    batch, seen = db().batch(), set()
    for name, lat, lon, pop in ranked:
        # one entry per place: "Bhubaneshwar"/"Bhubaneswar" or an old and new name sit within a few km
        if name in seen or any(math.hypot(lat - a, (lon - b) * math.cos(math.radians(lat))) * 111 < 8 for a, b in listed):
            continue
        listed.append((lat, lon))
        seen.add(name)
        ref = col("explore").document(leads.slug(name))
        if not ref.get().exists:
            batch.set(ref, {
                "city": name, "state": "", "lat": lat, "lon": lon,
                "population": pop, "order": len(seen), "priority": 0,
                "areas": [], "areasBuilt": False, "done": name in whole_city_scans, "createdAt": now_utc().isoformat(),
            })
        if len(seen) >= TOP_CITIES:
            break
    batch.commit()
    return len(seen)


def grid_areas(city: dict, km: int) -> list[dict]:
    """Fallback when OpenStreetMap is down: cover the city with points 4 km apart, centre first.
    Hotels still get real area names from TomTom's addresses."""
    step = 4
    n = max(1, km // step)
    points = []
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            if math.hypot(i, j) * step <= km:
                ns = "North" if i > 0 else "South" if i < 0 else ""
                ew = "East" if j > 0 else "West" if j < 0 else ""
                label = f"{city['city']} {ns}{'-' if ns and ew else ''}{ew}".strip() if (ns or ew) else f"{city['city']} Centre"
                points.append((math.hypot(i, j), {
                    "name": f"{label} ({abs(i) * step}/{abs(j) * step} km)" if (ns or ew) else label,
                    "lat": round(city["lat"] + i * step / 111, 5),
                    "lon": round(city["lon"] + j * step / (111 * math.cos(math.radians(city["lat"]))), 5),
                    "status": "todo",
                }))
    return [p for _, p in sorted(points, key=lambda t: t[0])][:MAX_AREAS_PER_CITY]


async def build_areas(ref, city: dict) -> int:
    km = city_radius_km(city["population"])
    try:
        elements = await overpass(f'[out:json][timeout:80];node["place"~"^(suburb|quarter|neighbourhood)$"]["name"]'
                                  f'(around:{km * 1000},{city["lat"]},{city["lon"]});out;')
    except RuntimeError:
        log.warning("Overpass unreachable; covering %s with a grid", city["city"])
        chosen = grid_areas(city, km)
        ref.update({"areas": chosen, "areasBuilt": True})
        return len(chosen)
    rank = {"suburb": 0, "quarter": 1, "neighbourhood": 2}

    def dist(e):
        return math.hypot(e["lat"] - city["lat"], (e["lon"] - city["lon"]) * math.cos(math.radians(city["lat"]))) * 111

    chosen: list[dict] = []
    # suburbs first, then nearer the centre (where hotels cluster); skip areas overlapping one already chosen
    for e in sorted(elements, key=lambda e: (rank.get(e["tags"].get("place"), 3), dist(e))):
        name = english_name(e["tags"])
        if not name or any(math.hypot(e["lat"] - a["lat"], (e["lon"] - a["lon"]) * math.cos(math.radians(a["lat"]))) * 111 < AREA_SPACING_KM
                           for a in chosen):
            continue
        chosen.append({"name": name, "lat": round(e["lat"], 5), "lon": round(e["lon"], 5), "status": "todo"})
        if len(chosen) >= MAX_AREAS_PER_CITY:
            break
    if not chosen:   # a small city with no named areas: search its centre
        chosen = [{"name": city["city"], "lat": city["lat"], "lon": city["lon"], "status": "todo"}]
    ref.update({"areas": chosen, "areasBuilt": True})
    return len(chosen)


# ── one area ─────────────────────────────────────────────────────────────────

def pending_cats(area: dict, wanted: list[str]) -> list[str]:
    """Kinds (of those switched on) not yet searched in this area. Areas explored before categories existed did hotels."""
    done = set(area.get("cats") or (["hotels"] if area.get("status") == "done" else []))
    return [k for k in wanted if k not in done]


async def explore_area(city: str, area: dict, cats: list[str]) -> dict:
    box = leads.square_around(area["lat"], area["lon"], AREA_RADIUS_M)
    found, squares = {}, 0
    async with httpx.AsyncClient(timeout=30) as client:
        for key in cats:
            cat = categories.get(key)
            queue, used = leads.grid(box, leads.START_SQUARE_KM), 0
            while queue and used < MAX_SQUARES_PER_CATEGORY:
                square = queue.pop(0)
                places, full = await sources.tomtom_box(client, square, cat)
                used += 1
                if full and leads.width_km(square) > leads.MIN_SQUARE_KM:
                    queue.extend(leads.grid(square, leads.width_km(square) / 2))
                for h in places:
                    found.setdefault(h["id"], h)
            squares += used
    # OpenStreetMap lists many more websites and emails than TomTom for most categories
    for h in await sources.osm_places(box, [categories.get(k) for k in cats]):
        found.setdefault(h["id"], h)

    usage.save_map_searches()
    rows = await leads.save_reachable(list(found.values()), "explore", city, area["name"])
    add_to_city(city, rows)
    by_cat = dict(Counter(r["category"] for r in rows))
    return {"found": len(found), "added": len(rows), "withEmail": len(rows), "squares": squares, "byCategory": by_cat}


def add_to_city(city: str, rows: list[dict]) -> None:
    """Add new leads to the city's totals and search list without re-reading the city."""
    if not rows:
        return
    snap = leads.city_doc(city).get()
    area_map = (snap.to_dict() or {}).get("areas", {}) if snap.exists else {}
    for r in rows:
        a = area_map.setdefault(r["areaKey"], {"city": city, "area": r["area"], "total": 0, "withEmail": 0, "withPhone": 0, "statuses": {}})
        a["total"] += 1
        a["withEmail"] += bool(r["emails"])
        a["withPhone"] += bool(r["phone"])
        a["statuses"]["new"] = a["statuses"].get("new", 0) + 1
        cats = a.setdefault("categories", {})
        cats[r["category"]] = cats.get(r["category"], 0) + 1
    leads.write_city(city, area_map)
    leads.merge_search_index(city, rows)


# ── the nightly run ──────────────────────────────────────────────────────────

def settings_ref():
    return col("settings").document("main")


def enabled() -> bool:
    snap = settings_ref().get()
    return (snap.to_dict() or {}).get("exploreEnabled", True) if snap.exists else True


def set_enabled(on: bool) -> None:
    settings_ref().set({"exploreEnabled": on}, merge=True)


def night() -> dict:
    """Tonight's progress (reset when the date changes)."""
    today = now_local().date().isoformat()
    state = (settings_ref().get().to_dict() or {}).get("exploreNight") or {}
    if state.get("date") != today:
        state = {"date": today, "areas": 0, "added": 0, "withEmail": 0, "done": [], "summarySent": False}
    return state


def next_area(wanted: list[str] | None = None) -> tuple | None:
    """(city ref, city doc, area index) to explore next: priority cities first, then by size; skipped
    cities are left out. A city is done when every area has been searched for every kind switched on."""
    wanted = wanted if wanted is not None else prefs.finding()["categories"]
    cities = sorted(col("explore").stream(), key=lambda d: (-d.to_dict().get("priority", 0), d.to_dict().get("order", 999)))
    for d in cities:
        c = d.to_dict()
        if c.get("skipped"):
            continue
        if not c.get("areasBuilt"):
            return d.reference, c, None
        idx = next((i for i, a in enumerate(c["areas"]) if pending_cats(a, wanted)), None)
        if idx is not None:
            return d.reference, c, idx
        if not c.get("done"):
            d.reference.update({"done": True})
    return None


def busy() -> bool:
    return _running is not None and not _running.done()


def tick() -> str:
    """Cron, every 30 min from 12:30 to 5:00 AM IST. Starts one area in the background."""
    global _running
    if not enabled():
        return "paused"
    if not (0 <= now_local().hour < 6):
        return "outside the night window"
    if busy():
        return "still exploring the previous area"
    state = night()
    if state["areas"] >= prefs.finding()["areasPerNight"]:
        return "tonight's areas are done"
    _running = asyncio.create_task(_run_one())
    return "started"


async def _run_one() -> None:
    async with keepalive.awake():
        try:
            if not any(True for _ in col("explore").limit(1).stream()):
                n = await build_cities()
                activity.log("lead_found", f"Explorer: listed the top {n} cities to explore.")
            wanted = prefs.finding()["categories"]
            pick = next_area(wanted)
            if pick is None:
                return await telegram.send("🌍 Explorer: every listed city has been explored. Add a city with “explore <city> next”.")
            ref, city, idx = pick
            if idx is None:
                n = await build_areas(ref, city)
                activity.log("lead_found", f"Explorer: found {n} areas to explore in {city['city']}.")
                city = ref.get().to_dict()
                idx = 0
            area = city["areas"][idx]
            cats = pending_cats(area, wanted)
            stats = await explore_area(city["city"], area, cats)
            done_cats = sorted(set(area.get("cats") or (["hotels"] if area.get("status") == "done" else [])) | set(cats))
            city["areas"][idx] |= {"status": "done", "cats": done_cats, "doneAt": now_utc().isoformat(),
                                   **{k: v for k, v in stats.items() if k != "byCategory"}}
            ref.update({"areas": city["areas"]})
            record(city["city"], area["name"], stats)
        except Exception:
            log.exception("Explorer run failed")


def by_category_text(counts: dict) -> str:
    return ", ".join(f"{n} {categories.get(k).label.lower()}" for k, n in sorted(counts.items(), key=lambda t: -t[1]))


def record(city: str, area: str, stats: dict) -> None:
    state = night()
    state["areas"] += 1
    state["added"] += stats["added"]
    state["withEmail"] = state.get("withEmail", 0) + stats["withEmail"]
    detail = f" ({by_category_text(stats['byCategory'])})" if stats["byCategory"] else ""
    state["done"].append(f"{area}, {city}: +{stats['added']}{detail}")
    settings_ref().set({"exploreNight": state}, merge=True)
    activity.log("lead_found", f"Explored {area}, {city}: {stats['added']} new businesses with an email{detail}.")



async def morning_summary() -> None:
    """Called by the daytime cron: tells the admin what the explorer did overnight, once."""
    state = (settings_ref().get().to_dict() or {}).get("exploreNight") or {}
    if state.get("areas") and not state.get("summarySent"):
        settings_ref().set({"exploreNight": {"summarySent": True}}, merge=True)
        await telegram.send(summary(state))


def summary(state: dict) -> str:
    nxt = next_area()
    upcoming = ""
    if nxt and nxt[2] is not None:
        ref, c, i = nxt
        names = [a["name"] for a in c["areas"][i:i + 4]]
        upcoming = f"\nNext: {', '.join(names)} ({c['city']})"
    lines = "\n".join(f"• {d}" for d in state["done"])
    return (f"🌃 Overnight exploring: {state['areas']} areas, {state['added']} new businesses with an email.\n"
            f"{lines}{upcoming}")


def status() -> str:
    cities = [d.to_dict() for d in col("explore").stream()]
    if not cities:
        return "🌍 Explorer hasn't started yet. It runs at night (12:30–5 AM IST) and lists the top cities on its first run."
    find = prefs.finding()
    done_c = sum(1 for c in cities if c.get("done"))
    areas = [a for c in cities for a in c.get("areas", [])]
    done_a = sum(1 for a in areas if not pending_cats(a, find["categories"]))
    nxt = next_area(find["categories"])
    if nxt is None:
        where = "every listed city is done"
    elif nxt[2] is None:
        where = f"{nxt[1]['city']} (its areas get listed on the next run)"
    else:
        where = f"{nxt[1]['city']}, next area {nxt[1]['areas'][nxt[2]]['name']}"
    state = night()
    return (f"🌍 Explorer is {'ON' if find['exploreEnabled'] else 'PAUSED'}: {find['areasPerNight']} areas a night, 12:30–5 AM IST.\n"
            f"Cities: {done_c} of {len(cities)} done · areas explored: {done_a} of {len(areas)} listed so far.\n"
            f"Tonight so far: {state['areas']} areas, {state['added']} new businesses with an email.\nNow on: {where}")


async def prioritise(name: str) -> str:
    """Put a city first in line; a city that isn't listed yet is looked up and added."""
    want = leads.slug(name)
    stamp = int(datetime.now().timestamp())
    for d in col("explore").stream():
        if leads.slug(d.to_dict()["city"]) == want:
            d.reference.update({"priority": stamp, "done": False, "skipped": False})
            return f"🌍 {d.to_dict()['city']} is next in line for the explorer (tonight from 12:30 AM)."
    try:
        place = await sources.geocode(f"{name}, India")
    except ValueError:
        return f"I couldn't find a city called {name} on the map."
    city = name.strip().title()
    col("explore").document(leads.slug(city)).set({
        "city": city, "state": "", "lat": place["lat"], "lon": place["lon"], "population": 500_000, "order": 999,
        "priority": stamp, "areas": [], "areasBuilt": False, "done": False, "createdAt": now_utc().isoformat(),
    })
    return f"🌍 Added {city} and put it first in line for the explorer (tonight from 12:30 AM)."


# ── the Settings page ────────────────────────────────────────────────────────

def queue() -> list[dict]:
    """Every listed city in the order the explorer takes them, with its progress."""
    wanted = prefs.finding()["categories"]
    docs = sorted(col("explore").stream(), key=lambda d: (-d.to_dict().get("priority", 0), d.to_dict().get("order", 999)))
    out = []
    for d in docs:
        c = d.to_dict()
        areas = c.get("areas", [])
        left = [a for a in areas if pending_cats(a, wanted)]
        out.append({
            "id": d.id, "city": c["city"], "skipped": bool(c.get("skipped")), "prioritised": bool(c.get("priority")),
            "areasListed": c.get("areasBuilt", False), "areas": len(areas), "areasDone": len(areas) - len(left),
            "next": left[0]["name"] if left else None,
            "found": sum(a.get("added", 0) for a in areas),
        })
    return out


def set_skipped(city_id: str, skipped: bool) -> None:
    ref = col("explore").document(city_id)
    if not ref.get().exists:
        raise ValueError("That city isn't in the explorer's list.")
    ref.update({"skipped": skipped})
