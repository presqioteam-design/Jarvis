"""
Live progress of a business search (a scan, or the night explorer), for the "Scanning now" panel and
for Jarvis to explain. Everything here is reported by the search itself as it works: which kind of
business and map square it is on, how many places, which website it is reading, what it found.

The search and the API run in the same server, so the page polls the live state from memory (every
second or two, no database reads). A copy is saved to Firestore at most every few seconds and at each
step, so the last result survives a restart and can be described later.

A search sets `current` (a context variable) for the code it calls, so the deeper steps (the website
reader, the saving) report without being handed anything.
"""

import time
import uuid
from contextvars import ContextVar

from ..firebase import col
from ..timeutil import now_utc

STEPS = [("map", "Map search"), ("osm", "OpenStreetMap"), ("websites", "Reading websites for emails"), ("saving", "Saving")]
SAVE_EVERY_S = 4
KEEP_EVENTS = 14
_runs: dict[str, "Live"] = {}          # newest runs, in memory (the live view)
current: ContextVar["Live | None"] = ContextVar("scanlive_current", default=None)


class Live:
    def __init__(self, kind: str, place: str, city: str = "", what: str = ""):
        self.id = uuid.uuid4().hex[:12]
        self._saved_at = 0.0
        self.data = {
            "id": self.id, "kind": kind, "place": place, "city": city, "what": what, "status": "running",
            "step": "map", "startedAt": now_utc().isoformat(), "updatedAt": now_utc().isoformat(), "finishedAt": None,
            "map": {"kind": "", "kindsDone": 0, "kindsTotal": 0, "square": 0, "searches": 0, "places": 0},
            "osm": {"places": None},
            "websites": {"total": 0, "done": 0, "withEmail": 0, "startedAt": None},
            "saved": 0, "events": [], "result": "", "error": "",
        }
        _runs[self.id] = self
        while len(_runs) > 5:
            _runs.pop(next(iter(_runs)))
        self._save(force=True)

    # ── reported by the search ──────────────────────────────────────────────
    def map_search(self, kind: str, kinds_done: int, kinds_total: int, square: int, places: int) -> None:
        m = self.data["map"]
        m.update(kind=kind, kindsDone=kinds_done, kindsTotal=kinds_total, square=square)
        m["searches"] += 1
        m["places"] += places
        self._step("map")

    def kinds_done(self, done: int, total: int) -> None:
        self.data["map"].update(kindsDone=done, kindsTotal=total)
        self._save()

    def osm(self, places: int | None = None) -> None:
        if places is None:
            self._step("osm")
        else:
            self.data["osm"]["places"] = places
            self.event("🗺", f"OpenStreetMap added {places:,} places")

    def websites(self, total: int) -> None:
        w = self.data["websites"]
        w["total"] += total
        w["startedAt"] = w["startedAt"] or now_utc().isoformat()
        self._step("websites")

    def site(self, name: str, category: str, emails: list[str]) -> None:
        w = self.data["websites"]
        w["done"] += 1
        if emails:
            w["withEmail"] += 1
            self.event("✉", f"{name} ({category}) · {emails[0]}")
        else:
            self.event("✗", f"{name}: no email on its website", save=False)
        self._save()

    def saving(self) -> None:
        self._step("saving")

    def saved(self, rows: list[dict]) -> None:
        self.data["saved"] += len(rows)
        if rows:
            self.event("💾", f"Saved {len(rows)} new business{'es' if len(rows) != 1 else ''} with an email")
        self._save(force=True)

    def event(self, icon: str, text: str, save: bool = True) -> None:
        ev = self.data["events"]
        ev.insert(0, {"at": now_utc().isoformat(), "icon": icon, "text": text})
        del ev[KEEP_EVENTS:]
        if save:
            self._save()

    def finish(self, result: str) -> None:
        self.data.update(status="done", step="done", result=result, finishedAt=now_utc().isoformat())
        self._save(force=True)
        self._tell_chat(f"🔎 The scan of {self.data['place']} has finished: {result}"
                        + (f" They're on the Leads page under {self.data['city']}." if self.data["saved"] and self.data["city"] else ""))

    def fail(self, why: str) -> None:
        self.data.update(status="failed", error=why, finishedAt=now_utc().isoformat())
        self._save(force=True)
        self._tell_chat(f"⚠️ The scan of {self.data['place']} stopped: {why}")

    def _tell_chat(self, text: str) -> None:
        """A scan you asked for reports back in Ask Jarvis by itself (the chat shows new messages live).
        The night explorer's areas aren't added: its morning summary covers them."""
        if self.data["kind"] != "scan":
            return
        try:
            from .chat import save   # chat imports this module; import here to avoid a loop
            save("assistant", text, "web")
        except Exception:
            pass

    # ── internals ───────────────────────────────────────────────────────────
    def _step(self, step: str) -> None:
        changed = self.data["step"] != step
        self.data["step"] = step
        self._save(force=changed)

    def _save(self, force: bool = False) -> None:
        self.data["updatedAt"] = now_utc().isoformat()
        if not force and time.monotonic() - self._saved_at < SAVE_EVERY_S:
            return
        self._saved_at = time.monotonic()
        try:
            col("scan_live").document(self.id).set(self.data)
        except Exception:
            pass   # the live view works from memory; a missed copy only matters after a restart


def start(kind: str, place: str, city: str = "", what: str = "") -> Live:
    run = Live(kind, place, city, what)
    current.set(run)
    return run


def get() -> "Live | None":
    return current.get()


def runs(limit: int = 3) -> list[dict]:
    """Newest first: from memory, else (after a restart) the last saved copies."""
    if _runs:
        return [r.data for r in reversed(list(_runs.values()))][:limit]
    try:
        docs = col("scan_live").order_by("startedAt", direction="DESCENDING").limit(limit).stream()
        out = [d.to_dict() for d in docs]
    except Exception:
        return []
    for d in out:   # a run that was going when the server restarted didn't finish
        if d.get("status") == "running":
            d.update(status="failed", error="The server restarted during this search; it carries on next time.")
    return out


def text() -> str:
    """For Jarvis: what the search is doing right now (or the last one's result)."""
    rs = runs(1)
    if not rs:
        return "No business search has run since the server started."
    r = rs[0]
    who = "the night explorer" if r["kind"] == "explorer" else "a scan"
    if r["status"] == "running":
        m, w = r["map"], r["websites"]
        step = {"map": f"map search: {m['kind'] or 'starting'} ({m['kindsDone']} of {m['kindsTotal']} kinds done, "
                       f"{m['searches']} searches, {m['places']:,} places so far)",
                "osm": "checking OpenStreetMap for more places",
                "websites": f"reading websites for emails: {w['done']} of {w['total']} read, {w['withEmail']} with an email",
                "saving": "saving the new businesses"}.get(r["step"], r["step"])
        found = [e["text"] for e in r["events"] if e["icon"] == "✉"][:3]
        return (f"SCANNING NOW ({who}, {r['place']}, started {r['startedAt'][11:16]} UTC): {step}. "
                f"Saved so far: {r['saved']}." + (f" Recently found: {'; '.join(found)}." if found else ""))
    if r["status"] == "failed":
        return f"LAST SEARCH ({who}, {r['place']}): stopped: {r['error']}"
    return f"LAST SEARCH ({who}, {r['place']}, finished {str(r['finishedAt'])[11:16]} UTC): {r['result']}"
