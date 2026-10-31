"""
Where businesses come from: TomTom (main) and OpenStreetMap (backup), one category at a time.
Each source returns plain dicts with the Lead fields it knows about.
"""

import asyncio
import logging
import re

import httpx

from ..config import get_settings
from . import categories, usage
from .categories import Category

log = logging.getLogger(__name__)

TOMTOM = "https://api.tomtom.com/search/2"
OVERPASS = ["https://maps.mail.ru/osm/tools/overpass/api/interpreter", "https://overpass-api.de/api/interpreter",
            "https://overpass.private.coffee/api/interpreter"]


async def geocode(place: str) -> dict:
    """'Hyderabad' or 'Madhapur, Hyderabad' -> {label, city, lat, lon, box}. Raises ValueError if not found."""
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            f"{TOMTOM}/geocode/{place}.json",
            params={"key": get_settings().tomtom_api_key, "countrySet": "IN", "limit": 1},
        )
        if r.status_code in (403, 429):
            raise TomTomLimit()
        r.raise_for_status()
        results = r.json().get("results", [])
    if not results:
        raise ValueError(f"Couldn't find '{place}' on the map")
    top = results[0]
    bb = top.get("boundingBox") or top["viewport"]
    return {
        "label": top["address"]["freeformAddress"],
        "city": top["address"].get("municipality") or place.split(",")[-1].strip(),
        "lat": top["position"]["lat"],
        "lon": top["position"]["lon"],
        "box": {"n": bb["topLeftPoint"]["lat"], "w": bb["topLeftPoint"]["lon"], "s": bb["btmRightPoint"]["lat"], "e": bb["btmRightPoint"]["lon"]},
    }


class TomTomLimit(Exception):
    """TomTom refused: the free daily searches are used up (or the key is over its rate)."""


async def tomtom_box(client: httpx.AsyncClient, box: dict, cat: Category) -> tuple[list[dict], bool]:
    """One category inside one box -> (places, full). TomTom caps a search at 100 results,
    so `full` (any search came back with 100) means: split the box."""
    params = {"key": get_settings().tomtom_api_key, "countrySet": "IN", "limit": 100,
              "topLeft": f"{box['n']},{box['w']}", "btmRight": f"{box['s']},{box['e']}"}
    out, full = {}, False
    for word, ids in cat.tomtom:
        if ids:
            r = await client.get(f"{TOMTOM}/categorySearch/{word}.json", params={**params, "categorySet": ids})
        else:   # no TomTom category for it: search by name inside the box
            r = await client.get(f"{TOMTOM}/poiSearch/{word}.json", params=params)
        usage.count_map_searches(1)
        r.raise_for_status()
        results = r.json().get("results", [])
        full = full or len(results) >= 100
        for x in results:
            poi, addr = x.get("poi", {}), x.get("address", {})
            name = poi.get("name", "").strip()
            if cat.name_must and not re.search(cat.name_must, name, re.I):
                continue
            out[f"tomtom_{x['id']}"] = {
                "id": f"tomtom_{x['id']}",
                "source": "tomtom",
                "name": name,
                "address": addr.get("freeformAddress", ""),
                "area": addr.get("municipalitySubdivision") or addr.get("municipalitySecondarySubdivision") or addr.get("municipality") or "",
                "lat": x["position"]["lat"],
                "lon": x["position"]["lon"],
                "phone": clean_phone(poi.get("phone", "")),
                "website": clean_url(poi.get("url", "")),
                "emails": [],
                "category": cat.key,
            }
    return list(out.values()), full


OSM_BUDGET_S = 150   # public Overpass servers are often busy: give up after this


async def osm_places(box: dict, cats: list[Category]) -> list[dict]:
    """Named places of these categories from OpenStreetMap (one query for all). Failures return []."""
    rules = [(k, rx) for c in cats for k, rx in c.osm]
    if not rules:
        return []
    bbox = f"({box['s']},{box['w']},{box['n']},{box['e']})"
    query = "[out:json][timeout:90];(" + "".join(f'nwr["{k}"~"{rx}"]["name"]{bbox};' for k, rx in rules) + ");out center tags;"
    task = asyncio.ensure_future(_overpass(query))
    done, _ = await asyncio.wait({task}, timeout=OSM_BUDGET_S)   # walk away from a stuck server at once
    if task not in done or task.exception():
        task.cancel()
        log.warning("OpenStreetMap unavailable; using the map search only")
        return []

    out = []
    for e in task.result():
        tags = e.get("tags", {})
        name = tags.get("name", "").strip()
        cat = categories.from_osm_tags(tags, cats)
        if not name or not cat:
            continue
        pos = e.get("center") or e
        email = tags.get("email") or tags.get("contact:email") or ""
        address = ", ".join(p for p in (tags.get("addr:housenumber"), tags.get("addr:street"), tags.get("addr:suburb"), tags.get("addr:city")) if p)
        out.append({
            "id": f"osm_{e['type']}{e['id']}",
            "source": "osm",
            "name": name,
            "address": address,
            "area": tags.get("addr:suburb", ""),
            "lat": pos["lat"],
            "lon": pos["lon"],
            "phone": clean_phone(tags.get("phone") or tags.get("contact:phone") or ""),
            "website": clean_url(tags.get("website") or tags.get("contact:website") or ""),
            "emails": [m.strip().lower() for m in re.split(r"[;,]", email) if "@" in m][:3],
            "category": cat.key,
        })
    return out


async def _overpass(query: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=100, headers={"User-Agent": "presqio-jarvis/0.1"}) as client:
        for url in OVERPASS:
            try:
                r = await client.post(url, data={"data": query})
                if r.status_code == 200:
                    return r.json()["elements"]
            except (httpx.HTTPError, ValueError) as e:
                log.warning("Overpass %s failed: %s", url, type(e).__name__)
    raise RuntimeError("OpenStreetMap servers are busy")


def clean_phone(raw: str) -> str:
    """Keep the first number, formatted as +91XXXXXXXXXX when it looks Indian."""
    first = re.split(r"[;,/]", raw)[0]
    digits = re.sub(r"\D", "", first)
    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    if len(digits) == 11 and digits.startswith("0"):
        return f"+91{digits[1:]}"
    return f"+{digits}" if digits else ""


def clean_url(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    return raw if raw.startswith(("http://", "https://")) else f"http://{raw}"
