"""
Portfolio prospects: businesses that need a website (none, only a social or listing page, a dead
site, or a weak one), for marketing Vinod's own web development work. Nothing is sent from here yet.

Where they come from:
- every business search and night-explorer run: save_reachable hands over everything the map found,
  with the crawler's home-page reads (collect)
- the businesses already in Leads, once: check_saved_leads reads their sites in the background

Stored in prospects/{key}, keyed by phone digits (else the email), so the same business from
TomTom and OpenStreetMap is one prospect. Per-city counts live in portfolio/{city slug}, updated
with increments, so the page shows totals without reading every prospect.
Prospects need an email (to email later) or a phone (the call list); others can't be reached.
"""

import asyncio
import logging
import re

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from ..firebase import col, db
from ..timeutil import now_utc
from . import activity, categories, crawler, keepalive, prefs, site_check, telegram

log = logging.getLogger(__name__)
PAGE = 20
CHECK_BATCH = 150          # saved leads read per round of the background check
_check_task: asyncio.Task | None = None


def _digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "unknown"


def key_of(phone: str, emails: list[str]) -> str:
    d = _digits(phone)
    return f"p{d}" if len(d) >= 10 else (f"e{emails[0].lower()}" if emails else "")


def summary_ref(city: str):
    return col("portfolio").document(slug(city))


# ── settings ────────────────────────────────────────────────────────────────

def enabled() -> bool:
    """Collect prospects during business searches (on unless switched off on the Portfolio page)."""
    return prefs.portfolio().get("collect", True)


def set_enabled(on: bool) -> None:
    prefs.save_portfolio({"collect": on})


# ── saving ──────────────────────────────────────────────────────────────────

def needs_reading(h: dict) -> bool:
    """Is this business's site worth a home-page read? (no site, or a social/listing link, needs none)"""
    w = h.get("website") or ""
    return bool(w) and site_check.classify(w, None)[0] == "ok"


async def collect(found: list[dict], crawled: dict[str, dict], city: str, fallback_area: str = "") -> int:
    """Save the businesses among `found` that need a website. `crawled` maps website -> crawler result
    (with its "home" read). Returns how many new prospects were saved. Never raises: a failure here
    must not stop the Presqio search it rides along with."""
    try:
        return _collect(found, crawled, city, fallback_area)
    except Exception:
        log.exception("Portfolio: couldn't save prospects for %s", city)
        return 0


def _collect(found: list[dict], crawled: dict[str, dict], city: str, fallback_area: str) -> int:
    rows: dict[str, dict] = {}
    for h in found:
        if not h.get("name"):
            continue
        website = h.get("website") or ""
        info = crawled.get(website, {})
        group, issues = site_check.classify(website, info.get("home"))
        if group == "ok":
            continue
        emails = [e for e in (h.get("emails") or info.get("emails") or []) if crawler.usable(e)]
        phone = h.get("phone") or info.get("phone") or ""
        key = key_of(phone, emails)
        if not key:
            continue          # no way to reach them
        if key in rows:       # the same business from both maps: keep what each one knows
            r = rows[key]
            r["emails"] = r["emails"] or emails
            r["website"] = r["website"] or website
            continue
        area = h.get("area") or fallback_area or "Other"
        home = info.get("home") or {}
        rows[key] = {
            "name": h["name"], "category": h.get("category") or categories.DEFAULT, "city": city, "area": area,
            "address": h.get("address", ""), "lat": h.get("lat"), "lon": h.get("lon"), "phone": phone,
            "emails": emails, "website": website, "source": h.get("source", ""), "sourceId": h.get("id", ""),
            "site": group, "issues": issues,
            "siteRead": {k: home[k] for k in ("status", "https", "mobile", "year", "seconds") if k in home} or None,
        }
    if not rows:
        return 0

    refs = {k: col("prospects").document(k) for k in rows}
    keys = list(refs)
    known = {s.id for i in range(0, len(keys), 300) for s in db().get_all([refs[k] for k in keys[i:i + 300]]) if s.exists}
    blocked = {d.id for d in col("dnc").stream()}
    now = now_utc().isoformat()
    batch, added, counts = db().batch(), 0, {}
    for k, r in rows.items():
        if k in known or _digits(r["phone"]) in blocked or any(e.lower() in blocked for e in r["emails"]):
            continue
        r |= {"reach": "email" if r["emails"] else "call", "status": "new", "createdAt": now, "updatedAt": now}
        batch.set(refs[k], r)
        added += 1
        counts[(r["city"], r["site"], r["reach"], r["category"])] = counts.get((r["city"], r["site"], r["reach"], r["category"]), 0) + 1
        if added % 400 == 0:
            batch.commit()
            batch = db().batch()
    batch.commit()
    _add_counts(counts)
    return added


def _add_counts(counts: dict[tuple, int], sign: int = 1) -> None:
    """counts: (city, site, reach, category) -> n. One write per city."""
    per_city: dict[str, dict] = {}
    for (city, site, reach, cat), n in counts.items():
        u = per_city.setdefault(city, {"city": city})
        for field in ("total", f"site.{site}.{reach}", f"category.{cat}"):
            u[field] = u.get(field, 0) + sign * n
    for city, u in per_city.items():
        data = {"city": city, "updatedAt": now_utc().isoformat()}
        for field, n in u.items():
            if field != "city":
                data[field] = firestore.Increment(n)
        # update() reads dotted names as nested fields; create the doc first if it's new
        ref = summary_ref(city)
        try:
            ref.update(data)
        except Exception:
            ref.set({"city": city}, merge=True)
            ref.update(data)


# ── the page ────────────────────────────────────────────────────────────────

def cities() -> list[dict]:
    out = []
    for d in col("portfolio").stream():
        x = d.to_dict()
        if x.get("city") and x.get("total", 0) > 0:
            out.append({"city": x["city"], "total": x.get("total", 0), "site": x.get("site", {}), "category": x.get("category", {})})
    return sorted(out, key=lambda c: (-c["total"], c["city"]))


def view(p: dict, pid: str) -> dict:
    return {
        "id": pid, "name": p.get("name", ""), "category": p.get("category", categories.DEFAULT),
        "categoryLabel": categories.get(p.get("category")).label, "city": p.get("city", ""), "area": p.get("area", ""),
        "address": p.get("address", ""), "phone": p.get("phone", ""), "emails": p.get("emails", []),
        "website": p.get("website", ""), "site": p.get("site", ""), "siteLabel": site_check.GROUP_LABELS.get(p.get("site", ""), ""),
        "issues": [site_check.issue_text(i) for i in p.get("issues", [])], "reach": p.get("reach", ""),
        "status": p.get("status", "new"),
    }


def list_prospects(city: str, site: str | None, reach: str | None, category: str | None, after: str | None) -> dict:
    """One page, equality filters only (no composite index needed), in document order."""
    q = col("prospects").where(filter=FieldFilter("city", "==", city)).where(filter=FieldFilter("status", "==", "new"))
    if site:
        q = q.where(filter=FieldFilter("site", "==", site))
    if reach:
        q = q.where(filter=FieldFilter("reach", "==", reach))
    if category:
        q = q.where(filter=FieldFilter("category", "==", category))
    q = q.order_by("__name__")
    if after:
        last = col("prospects").document(after).get()
        if last.exists:
            q = q.start_after(last)
    docs = list(q.limit(PAGE).stream())
    return {"items": [view(d.to_dict(), d.id) for d in docs], "next": docs[-1].id if len(docs) == PAGE else None}


def _remove(pid: str, status: str) -> dict:
    ref = col("prospects").document(pid)
    p = ref.get().to_dict()
    if not p:
        raise ValueError("That business isn't in the list any more.")
    if p.get("status") == "new":
        _add_counts({(p["city"], p["site"], p["reach"], p["category"]): 1}, sign=-1)
    ref.update({"status": status, "updatedAt": now_utc().isoformat()})
    return p


def skip(pid: str) -> None:
    """Not a fit (e.g. a big chain, or already has a good site elsewhere): leave it off the lists."""
    _remove(pid, "skipped")


def block(pid: str) -> None:
    """Never contact: its email and phone go on the do-not-contact list Presqio uses too."""
    p = _remove(pid, "blocked")
    now = now_utc().isoformat()
    for k in filter(None, [*p.get("emails", []), _digits(p.get("phone", ""))]):
        col("dnc").document(k.lower()).set({"reason": "blocked by admin (portfolio)", "business": p.get("name", ""), "createdAt": now})
    activity.log("status_change", f"Blocked {p.get('name', pid)} from the portfolio lists: will never be contacted.")


# ── checking the businesses already in Leads ────────────────────────────────

def check_state() -> dict:
    s = prefs.portfolio().get("check") or {}
    running = _check_task is not None and not _check_task.done()
    return {"running": running, "checked": s.get("checked", 0), "added": s.get("added", 0),
            "finished": s.get("finished", False), "finishedAt": s.get("finishedAt"), "error": s.get("error", "")}


def start_check(restart: bool = False) -> bool:
    """Start (or resume) reading the websites of the saved leads. False when it's already running."""
    global _check_task
    if _check_task is not None and not _check_task.done():
        return False
    if restart:
        prefs.save_portfolio({"check": {}})
    _check_task = asyncio.create_task(_check_saved_leads())
    return True


async def _check_saved_leads() -> None:
    state = dict(prefs.portfolio().get("check") or {})
    state.update(error="", finished=False)
    fields = ["name", "category", "city", "area", "address", "lat", "lon", "phone", "emails", "website", "source", "status"]
    try:
        async with keepalive.awake():
            while True:
                q = col("leads").order_by("__name__").select(fields)
                if state.get("cursor"):
                    last = col("leads").document(state["cursor"]).get()
                    if last.exists:
                        q = q.start_after(last)
                docs = list(q.limit(CHECK_BATCH).stream())
                if not docs:
                    break
                leads = [d.to_dict() | {"id": d.id} for d in docs]
                leads = [l for l in leads if l.get("status") not in ("unsubscribed", "bounced", "customer") and l.get("city")]
                sites = list({l["website"] for l in leads if needs_reading(l)})
                crawled = await crawler.crawl_many(sites) if sites else {}
                by_city: dict[str, list[dict]] = {}
                for l in leads:
                    by_city.setdefault(l["city"], []).append(l)
                for city, rows in by_city.items():
                    state["added"] = state.get("added", 0) + await collect(rows, crawled, city)
                state["checked"] = state.get("checked", 0) + len(docs)
                state["cursor"] = docs[-1].id
                prefs.save_portfolio({"check": state})
                if len(docs) < CHECK_BATCH:
                    break
        state.update(finished=True, finishedAt=now_utc().isoformat())
        prefs.save_portfolio({"check": state})
        text = (f"Portfolio: checked the websites of {state['checked']:,} saved businesses; "
                f"{state['added']:,} need a website and are on the Portfolio page.")
        activity.log("lead_found", text)
        await telegram.send(f"🌐 {text}")
    except Exception as e:
        log.exception("Portfolio check of saved leads stopped")
        state["error"] = "Stopped part-way. Press Continue to carry on from where it stopped."
        prefs.save_portfolio({"check": state})
        activity.log("error", f"Portfolio website check stopped: {type(e).__name__}")
