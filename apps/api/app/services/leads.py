"""Read helpers for leads. Finding and enriching leads comes in step 2."""

from collections import Counter

from ..firebase import col


def status_counts() -> dict[str, int]:
    return dict(Counter(d.to_dict().get("status", "new") for d in col("leads").stream()))


def by_status(status: str, limit: int = 20) -> list[dict]:
    docs = col("leads").where("status", "==", status).limit(limit).stream()
    return [{"id": d.id, **d.to_dict()} for d in docs]
