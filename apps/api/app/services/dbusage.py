"""
How much of Firestore's free daily allowance is used, from Google Cloud Monitoring.
The allowance (50k reads, 20k writes, 20k deletes) resets at midnight US Pacific time.

Reading it needs the "Monitoring Viewer" role on the Firebase service account; without it
this returns {"error": "permission"} and the Settings page explains how to grant it.
Numbers lag a few minutes behind and are cached here for 5 minutes.
"""

import json
import logging
import time
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from ..config import get_settings

log = logging.getLogger(__name__)
FREE = {"reads": 50_000, "writes": 20_000, "deletes": 20_000}
METRICS = {"reads": "document/read_count", "writes": "document/write_count", "deletes": "document/delete_count"}
PACIFIC = ZoneInfo("America/Los_Angeles")
_cache: tuple[float, dict] | None = None
_creds = None


def _credentials():
    global _creds
    if _creds is None:
        s = get_settings()
        info = (json.loads(s.firebase_service_account_json) if s.firebase_service_account_json
                else json.load(open(s.google_application_credentials)))
        _creds = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/monitoring.read"])
    if not _creds.valid:
        _creds.refresh(Request())
    return _creds


def reset_time() -> tuple[datetime, datetime]:
    """(last reset, next reset): midnight in California (handles the clock change)."""
    now = datetime.now(PACIFIC)
    last = now.replace(hour=0, minute=0, second=0, microsecond=0)
    nxt = datetime.combine(last.date() + timedelta(days=1), dtime.min, tzinfo=PACIFIC)
    return last, nxt


def today() -> dict:
    global _cache
    if _cache and time.monotonic() - _cache[0] < 300:
        return _cache[1]
    try:
        creds = _credentials()
        last, nxt = reset_time()
        start, end = last.astimezone(ZoneInfo("UTC")), datetime.now(ZoneInfo("UTC"))
        period = max(60, int((end - start).total_seconds()) // 60 * 60)
        out = {"limits": FREE, "resetsAt": nxt.isoformat()}
        with httpx.Client(timeout=10) as client:
            for key, metric in METRICS.items():
                r = client.get(
                    f"https://monitoring.googleapis.com/v3/projects/{creds.project_id}/timeSeries",
                    headers={"Authorization": f"Bearer {creds.token}"},
                    params={
                        "filter": f'metric.type="firestore.googleapis.com/{metric}"',
                        "interval.startTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "interval.endTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "aggregation.alignmentPeriod": f"{period}s",
                        "aggregation.perSeriesAligner": "ALIGN_SUM",
                        "aggregation.crossSeriesReducer": "REDUCE_SUM",
                    },
                )
                if r.status_code == 403:
                    result = {"error": "permission", "serviceAccount": creds.service_account_email, "project": creds.project_id,
                              "resetsAt": nxt.isoformat()}
                    _cache = (time.monotonic(), result)
                    return result
                r.raise_for_status()
                points = [p for ts in r.json().get("timeSeries", []) for p in ts.get("points", [])]
                out[key] = sum(int(p["value"].get("int64Value", 0)) for p in points)
        _cache = (time.monotonic(), out)
        return out
    except Exception as e:   # never break the page over a usage number
        log.warning("Firestore usage unavailable: %s", type(e).__name__)
        return {"error": "unavailable", "resetsAt": reset_time()[1].isoformat()}
