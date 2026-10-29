"""
One-off maintenance, in a single pass over the leads (one read per lead):
    cd apps/api && .venv/bin/python -m scripts.rebuild_totals

- marks every lead hasEmail true/false (the Leads page and sending query on it)
- rebuilds each city's totals in cities/{city}
- removes leftovers of the first Madhapur test (leads with no city, its campaign)
- removes the old per-area docs (totals now live in cities/{city})
"""

from collections import defaultdict

from app.firebase import col, db
from app.services import leads


def commit_in_batches(ops) -> int:
    ops = list(ops)
    for i in range(0, len(ops), 400):
        batch = db().batch()
        for op in ops[i:i + 400]:
            op(batch)
        batch.commit()
    return len(ops)


if __name__ == "__main__":
    by_city: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    flags, orphans = [], []
    for d in col("leads").select(["city", "area", "areaKey", "status", "emails", "phone", "hasEmail"]).stream():
        l = d.to_dict()
        if not l.get("city"):
            orphans.append(d.reference)
            continue
        has = bool(l.get("emails"))
        if l.get("hasEmail") is not has:
            flags.append((d.reference, has))
        by_city[l["city"]][l["areaKey"]].append(l)

    print("hasEmail marked:", commit_in_batches(lambda b, r=r, h=h: b.update(r, {"hasEmail": h}) for r, h in flags))
    print("test leftovers removed:", commit_in_batches(lambda b, r=r: b.delete(r) for r in orphans), "leads")
    old_camps = [d.reference for d in col("campaigns").stream() if not d.to_dict().get("city")]
    print("old test campaigns removed:", commit_in_batches(lambda b, r=r: b.delete(r) for r in old_camps))
    print("old area docs removed:", commit_in_batches(lambda b, r=r: b.delete(r) for r in [d.reference for d in col("areas").select([]).stream()]))

    for city, groups in by_city.items():
        totals = leads.write_city(city, {key: leads.area_summary(rows, city) for key, rows in groups.items()})
        for c in col("campaigns").stream():
            if c.to_dict().get("city") == city:
                c.reference.update({"stats.found": totals["total"], "stats.withEmail": totals["withEmail"], "stats.withPhone": totals["withPhone"]})
        print(city, totals)
