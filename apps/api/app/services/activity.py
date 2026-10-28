"""Log of what Jarvis did. Feeds the dashboard and the daily report."""

from ..firebase import col
from ..timeutil import now_utc


def log(type_: str, text: str, lead_id: str | None = None) -> None:
    data = {"type": type_, "text": text, "at": now_utc().isoformat()}
    if lead_id:
        data["leadId"] = lead_id
    col("activity").add(data)


def since(iso: str) -> list[dict]:
    docs = col("activity").where("at", ">=", iso).stream()
    return sorted((d.to_dict() for d in docs), key=lambda a: a["at"])
