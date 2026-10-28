"""
Where hotels come from: TomTom (main) and OpenStreetMap (backup).
Each source returns plain dicts with the Lead fields it knows about.
"""

import logging
import re

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)

TOMTOM = "https://api.tomtom.com/search/2"
HOTEL_CATEGORY = "7314"  # TomTom "Hotel/Motel", includes guest houses and serviced apartments
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter"]


async def geocode(area: str) -> dict:
    """'Madhapur, Hyderabad' -> {label, lat, lon}. Raises ValueError if not found."""
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            f"{TOMTOM}/geocode/{area}.json",
            params={"key": get_settings().tomtom_api_key, "countrySet": "IN", "limit": 1},
        )
        r.raise_for_status()
        results = r.json().get("results", [])
    if not results:
        raise ValueError(f"Couldn't find '{area}' on the map")
    top = results[0]
    return {"label": top["address"]["freeformAddress"], "lat": top["position"]["lat"], "lon": top["position"]["lon"]}


async def tomtom_hotels(lat: float, lon: float, radius_m: int) -> list[dict]:
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for offset in range(0, 500, 100):   # TomTom pages are 100 results max
            r = await client.get(
                f"{TOMTOM}/categorySearch/hotel.json",
                params={
                    "key": get_settings().tomtom_api_key, "lat": lat, "lon": lon, "radius": radius_m,
                    "categorySet": HOTEL_CATEGORY, "countrySet": "IN", "limit": 100, "ofs": offset,
                },
            )
            r.raise_for_status()
            page = r.json().get("results", [])
            for x in page:
                poi = x.get("poi", {})
                out.append({
                    "id": f"tomtom_{x['id']}",
                    "source": "tomtom",
                    "name": poi.get("name", "").strip(),
                    "address": x.get("address", {}).get("freeformAddress", ""),
                    "lat": x["position"]["lat"],
                    "lon": x["position"]["lon"],
                    "phone": clean_phone(poi.get("phone", "")),
                    "website": clean_url(poi.get("url", "")),
                    "emails": [],
                })
            if len(page) < 100:
                break
    return out


async def osm_hotels(lat: float, lon: float, radius_m: int) -> list[dict]:
    """OpenStreetMap via Overpass. Slow and often busy, so failures return []."""
    query = (
        f'[out:json][timeout:50];nwr["tourism"~"^(hotel|guest_house|motel|hostel)$"]'
        f"(around:{radius_m},{lat},{lon});out center tags;"
    )
    for url in OVERPASS:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(url, data={"data": query}, headers={"User-Agent": "presqio-jarvis/0.1"})
                r.raise_for_status()
                elements = r.json()["elements"]
            break
        except Exception as e:
            log.warning("Overpass %s failed: %s", url, type(e).__name__)
    else:
        return []

    out = []
    for e in elements:
        tags = e.get("tags", {})
        name = tags.get("name", "").strip()
        if not name:
            continue
        pos = e.get("center") or e
        email = tags.get("email") or tags.get("contact:email") or ""
        address = ", ".join(p for p in (tags.get("addr:housenumber"), tags.get("addr:street"), tags.get("addr:suburb"), tags.get("addr:city")) if p)
        out.append({
            "id": f"osm_{e['type']}{e['id']}",
            "source": "osm",
            "name": name,
            "address": address,
            "lat": pos["lat"],
            "lon": pos["lon"],
            "phone": clean_phone(tags.get("phone") or tags.get("contact:phone") or ""),
            "website": clean_url(tags.get("website") or tags.get("contact:website") or ""),
            "emails": [email.lower()] if email else [],
        })
    return out


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
