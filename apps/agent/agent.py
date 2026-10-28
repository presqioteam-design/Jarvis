"""
Jarvis desktop agent.

Reads window, AFK and browser events from ActivityWatch's local API and
upserts them into Firestore under users/{uid}/events. Safe to restart:
document IDs are derived from ActivityWatch event IDs, so re-syncing the
same window overwrites instead of duplicating.

Run:  python agent.py          (loops forever)
      python agent.py --once   (single sync, handy for testing)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

import firebase_admin
from firebase_admin import credentials, firestore

from categories import DEFAULT_RULES, categorize

HERE = Path(__file__).parent
STATE_FILE = HERE / "state.json"
OVERLAP = timedelta(minutes=10)      # re-read recent events: AW keeps extending the latest one
BATCH_LIMIT = 450                    # Firestore batches max out at 500 writes

log = logging.getLogger("jarvis-agent")


@dataclass
class Config:
    uid: str
    aw_url: str
    interval: int
    tz: ZoneInfo

    @classmethod
    def load(cls) -> "Config":
        load_dotenv(HERE / ".env")
        uid = os.environ.get("JARVIS_UID", "").strip()
        if not uid:
            sys.exit("JARVIS_UID is not set. Copy .env.example to .env and fill it in.")
        return cls(
            uid=uid,
            aw_url=os.environ.get("AW_URL", "http://localhost:5600").rstrip("/"),
            interval=int(os.environ.get("SYNC_INTERVAL", "300")),
            tz=ZoneInfo(os.environ.get("TIMEZONE", "Asia/Kolkata")),
        )


# ── ActivityWatch ────────────────────────────────────────────────────────────

class ActivityWatch:
    def __init__(self, base_url: str):
        self.base = f"{base_url}/api/0"

    def buckets(self) -> dict:
        r = requests.get(f"{self.base}/buckets/", timeout=10)
        r.raise_for_status()
        return r.json()

    def events(self, bucket_id: str, start: datetime, end: datetime) -> list[dict]:
        r = requests.get(
            f"{self.base}/buckets/{bucket_id}/events",
            params={"start": start.isoformat(), "end": end.isoformat(), "limit": -1},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def afk_intervals(events: list[dict]) -> list[tuple[datetime, datetime]]:
    spans = []
    for e in events:
        if e.get("data", {}).get("status") == "afk":
            start = parse_ts(e["timestamp"])
            spans.append((start, start + timedelta(seconds=e.get("duration", 0))))
    return spans


def was_afk(start: datetime, spans: list[tuple[datetime, datetime]]) -> bool:
    return any(a <= start < b for a, b in spans)


# ── State ────────────────────────────────────────────────────────────────────

def load_last_sync(tz: ZoneInfo) -> datetime:
    if STATE_FILE.exists():
        return parse_ts(json.loads(STATE_FILE.read_text())["last_sync"])
    # first run: start from local midnight today
    midnight = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc)


def save_last_sync(ts: datetime) -> None:
    STATE_FILE.write_text(json.dumps({"last_sync": ts.isoformat()}))


# ── Sync ─────────────────────────────────────────────────────────────────────

def load_rules(db, uid: str) -> list[dict]:
    snap = db.document(f"users/{uid}/settings/main").get()
    rules = (snap.to_dict() or {}).get("categoryRules") if snap.exists else None
    return rules or DEFAULT_RULES


def sync_once(cfg: Config, aw: ActivityWatch, db) -> int:
    now = datetime.now(timezone.utc)
    start = load_last_sync(cfg.tz) - OVERLAP
    buckets = aw.buckets()

    window_ids = [b for b in buckets if b.startswith("aw-watcher-window")]
    afk_ids = [b for b in buckets if b.startswith("aw-watcher-afk")]
    web_ids = [b for b in buckets if b.startswith("aw-watcher-web")]
    if not window_ids:
        log.warning("No aw-watcher-window bucket found. Is ActivityWatch running?")
        return 0

    afk = []
    for b in afk_ids:
        afk += afk_intervals(aw.events(b, start, now))

    rules = load_rules(db, cfg.uid)
    events_col = db.collection(f"users/{cfg.uid}/events")
    batch, pending, written = db.batch(), 0, 0

    def add(doc_id: str, payload: dict):
        nonlocal batch, pending, written
        batch.set(events_col.document(doc_id), payload)
        pending += 1
        written += 1
        if pending >= BATCH_LIMIT:
            batch.commit()
            batch, pending = db.batch(), 0

    for bucket in window_ids:
        for e in aw.events(bucket, start, now):
            ts = parse_ts(e["timestamp"])
            app = e["data"].get("app", "unknown")
            title = e["data"].get("title", "")
            is_afk = was_afk(ts, afk)
            add(f"{bucket}_{e['id']}", {
                "start": ts.isoformat(),
                "duration": round(e.get("duration", 0), 1),
                "app": app,
                "title": title,
                "afk": is_afk,
                "category": "away" if is_afk else categorize(app, title, rules),
                "date": ts.astimezone(cfg.tz).date().isoformat(),
                "source": bucket,
            })

    for bucket in web_ids:
        for e in aw.events(bucket, start, now):
            ts = parse_ts(e["timestamp"])
            title = e["data"].get("title", "")
            url = e["data"].get("url", "")
            add(f"{bucket}_{e['id']}", {
                "start": ts.isoformat(),
                "duration": round(e.get("duration", 0), 1),
                "app": "browser",
                "title": title,
                "url": url,
                "afk": was_afk(ts, afk),
                "category": categorize("browser", f"{title} {url}", rules),
                "date": ts.astimezone(cfg.tz).date().isoformat(),
                "source": bucket,
            })

    if pending:
        batch.commit()
    save_last_sync(now)
    return written


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config.load()

    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "service-account.json")
    firebase_admin.initialize_app(credentials.Certificate(str(HERE / cred_path)))
    db = firestore.client()
    aw = ActivityWatch(cfg.aw_url)

    once = "--once" in sys.argv
    while True:
        try:
            n = sync_once(cfg, aw, db)
            log.info("Synced %d events", n)
        except requests.ConnectionError:
            log.warning("Can't reach ActivityWatch at %s, retrying later", cfg.aw_url)
        except Exception:  # keep the agent alive; log and retry next tick
            log.exception("Sync failed")
        if once:
            break
        time.sleep(cfg.interval)


if __name__ == "__main__":
    main()
