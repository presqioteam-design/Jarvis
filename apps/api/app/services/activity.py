"""Turn raw activity events into daily stats."""

from collections import Counter
from datetime import timedelta

from ..firebase import col
from ..timeutil import now_utc, parse


def load_events(date: str) -> list[dict]:
    docs = col("events").where("date", "==", date).stream()
    events = [d.to_dict() for d in docs]
    # browser events duplicate window time; use window events for totals
    events = [e for e in events if not e.get("source", "").startswith("aw-watcher-web")]
    events.sort(key=lambda e: e["start"])
    return events


def count_switches(events: list[dict]) -> int:
    switches, last = 0, None
    for e in events:
        if e.get("afk") or e.get("duration", 0) < 5:   # ignore blips under 5s
            continue
        if last is not None and e["app"] != last:
            switches += 1
        last = e["app"]
    return switches


def build_timeline(events: list[dict]) -> list[dict]:
    blocks: list[dict] = []
    for e in events:
        cat = "away" if e.get("afk") else e.get("category", "other")
        if blocks and blocks[-1]["category"] == cat:
            blocks[-1]["seconds"] += e["duration"]
        else:
            blocks.append({"category": cat, "start": e["start"], "seconds": e["duration"]})
    for b in blocks:
        b["seconds"] = round(b["seconds"])
    return blocks


def summarize(date: str) -> dict:
    events = load_events(date)
    active = [e for e in events if not e.get("afk")]

    def total(cat: str) -> float:
        return sum(e["duration"] for e in active if e.get("category") == cat)

    apps = Counter()
    for e in active:
        apps[e["app"]] += e["duration"]

    return {
        "date": date,
        "focusSeconds": round(total("deep")),
        "meetingSeconds": round(total("meeting")),
        "activeSeconds": round(sum(e["duration"] for e in active)),
        "contextSwitches": count_switches(events),
        "topApps": [{"app": a, "seconds": round(s)} for a, s in apps.most_common(6)],
        "timeline": build_timeline(events),
        "updatedAt": now_utc().isoformat(),
    }


def recent_switches(date: str, minutes: int = 30) -> tuple[int, list[str]]:
    """App switches in the last N minutes, plus the apps involved."""
    cutoff = now_utc() - timedelta(minutes=minutes)
    recent = [e for e in load_events(date) if parse(e["start"]) >= cutoff]
    apps = [a for a, _ in Counter(e["app"] for e in recent if not e.get("afk")).most_common(3)]
    return count_switches(recent), apps


def save_summary(summary: dict, **extra) -> None:
    col("summaries").document(summary["date"]).set({**summary, **extra}, merge=True)
