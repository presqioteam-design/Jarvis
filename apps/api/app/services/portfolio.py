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
        c = _count_key(r, "new")
        counts[c] = counts.get(c, 0) + 1
        if added % 400 == 0:
            batch.commit()
            batch = db().batch()
    batch.commit()
    _add_counts(counts)
    return added


# ── statuses and counts ─────────────────────────────────────────────────────
# new (to review) -> ready (approved to email) -> emailed -> replied / interested / not_interested /
# unsubscribed / bounced. skipped and blocked leave the lists. Only approved ones are ever emailed.
TABS = {
    "review": ["new"],
    "approved": ["ready"],
    "contacted": ["emailed", "replied", "interested"],
    "closed": ["not_interested", "unsubscribed", "bounced"],
}
OFF_LIST = ("skipped", "blocked")


def _count_key(p: dict, status: str) -> tuple:
    return (p["city"], status, p["site"], p["reach"], p["category"])


def _add_counts(counts: dict[tuple, int], sign: int = 1) -> None:
    """counts: (city, status, site, reach, category) -> n. One write per city.
    The city doc keeps n.{status}.{site}.{reach} and c.{status}.{category}."""
    per_city: dict[str, dict] = {}
    for (city, status, site, reach, cat), n in counts.items():
        if status in OFF_LIST:
            continue
        u = per_city.setdefault(city, {})
        for field in (f"n.{status}.{site}.{reach}", f"c.{status}.{cat}"):
            u[field] = u.get(field, 0) + sign * n
    for city, u in per_city.items():
        data = {"city": city, "updatedAt": now_utc().isoformat(), **{f: firestore.Increment(n) for f, n in u.items() if n}}
        # update() reads dotted names as nested fields; create the doc first if it's new
        ref = summary_ref(city)
        try:
            ref.update(data)
        except Exception:
            ref.set({"city": city}, merge=True)
            ref.update(data)


def move(pid: str, p: dict, status: str, patch: dict | None = None) -> None:
    """Change a prospect's status and keep the city's counts right."""
    old = p.get("status", "new")
    col("prospects").document(pid).update({"status": status, "updatedAt": now_utc().isoformat(), **(patch or {})})
    if old != status:
        _add_counts({_count_key(p, old): -1, _count_key(p, status): 1})
    p["status"] = status


# ── the page ────────────────────────────────────────────────────────────────

def cities() -> list[dict]:
    out = []
    for d in col("portfolio").stream():
        x = d.to_dict()
        if "site" in x and "n" not in x:
            # saved before statuses were counted: those were all "to review"
            x["n"], x["c"] = {"new": x["site"]}, {"new": x.get("category", {})}
            d.reference.update({"n": x["n"], "c": x["c"], "site": firestore.DELETE_FIELD,
                                "category": firestore.DELETE_FIELD, "total": firestore.DELETE_FIELD})
        n = x.get("n", {})
        total = sum(v for by_site in n.values() for by_reach in by_site.values() for v in by_reach.values())
        if x.get("city") and total > 0:
            out.append({"city": x["city"], "total": total, "n": n, "c": x.get("c", {})})
    return sorted(out, key=lambda c: (-c["total"], c["city"]))


def view(p: dict, pid: str) -> dict:
    return {
        "id": pid, "name": p.get("name", ""), "category": p.get("category", categories.DEFAULT),
        "categoryLabel": categories.get(p.get("category")).label, "city": p.get("city", ""), "area": p.get("area", ""),
        "address": p.get("address", ""), "phone": p.get("phone", ""), "emails": p.get("emails", []),
        "website": p.get("website", ""), "site": p.get("site", ""), "siteLabel": site_check.GROUP_LABELS.get(p.get("site", ""), ""),
        "issues": [site_check.issue_text(i) for i in p.get("issues", [])], "reach": p.get("reach", ""),
        "status": p.get("status", "new"), "emailedTo": p.get("emailedTo", ""), "followUps": p.get("followUps", 0),
        "lastContactAt": p.get("lastContactAt"), "replySummary": p.get("replySummary", ""),
    }


def _query(city: str, status: str, site: str | None, reach: str | None, category: str | None):
    """Equality filters only: Firestore serves these without a composite index."""
    q = col("prospects").where(filter=FieldFilter("city", "==", city)).where(filter=FieldFilter("status", "==", status))
    for field, value in (("site", site), ("reach", reach), ("category", category)):
        if value:
            q = q.where(filter=FieldFilter(field, "==", value))
    return q


def list_prospects(city: str, tab: str, site: str | None, reach: str | None, category: str | None, after: str | None) -> dict:
    """One page of a tab. A tab with several statuses is read one status after another, like the
    Leads page; `after` is "<status index>:<last id>"."""
    statuses = TABS[tab]
    phase, last_id = 0, None
    if after:
        idx, _, last_id = after.partition(":")
        phase = int(idx) if idx.isdigit() else 0
    items = []
    while phase < len(statuses) and len(items) < PAGE:
        q = _query(city, statuses[phase], site, reach, category).order_by("__name__")
        if last_id:
            last = col("prospects").document(last_id).get()
            if last.exists:
                q = q.start_after(last)
        want = PAGE - len(items)
        docs = list(q.limit(want).stream())
        items += [view(d.to_dict(), d.id) for d in docs]
        if len(docs) == want:
            return {"items": items, "next": f"{phase}:{docs[-1].id}"}
        phase, last_id = phase + 1, None
    return {"items": items, "next": None}


def _get(pid: str) -> dict:
    p = col("prospects").document(pid).get().to_dict()
    if not p:
        raise ValueError("That business isn't in the list any more.")
    return p


def set_review(ids: list[str], approved: bool) -> int:
    """Approve businesses to be emailed (or take the approval back). Only ones with an email that
    haven't been contacted yet change. Returns how many changed."""
    changed = 0
    for pid in ids:
        p = col("prospects").document(pid).get().to_dict()
        if p and p.get("reach") == "email" and p.get("status") == ("new" if approved else "ready"):
            move(pid, p, "ready" if approved else "new")
            changed += 1
    return changed


def approve_all(city: str, site: str | None, category: str | None) -> int:
    """Approve every business with an email in this city (and group / kind) that's waiting for review."""
    docs = list(_query(city, "new", site, "email", category).stream())
    now, counts, batch = now_utc().isoformat(), {}, db().batch()
    for i, d in enumerate(docs, 1):
        p = d.to_dict()
        batch.update(d.reference, {"status": "ready", "updatedAt": now})
        for k, n in ((_count_key(p, "new"), -1), (_count_key(p, "ready"), 1)):
            counts[k] = counts.get(k, 0) + n
        if i % 400 == 0:
            batch.commit()
            batch = db().batch()
    batch.commit()
    _add_counts(counts)
    return len(docs)


def _remove(pid: str, status: str) -> dict:
    p = _get(pid)
    move(pid, p, status, {"nextActionAt": None})
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
