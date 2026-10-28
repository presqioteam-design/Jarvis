"""
One-off maintenance after the first Hyderabad scan. Run once Firestore's daily
quota has reset:  cd apps/api && .venv/bin/python -m scripts.rebuild_totals

- removes the leftovers of the first Madhapur test (leads with no city, its campaign)
- removes the old per-area docs (totals now live in cities/{city})
- rebuilds each city's totals and flags leads that have an email
"""

from app.firebase import col, db
from app.services import leads


def delete_all(refs) -> int:
    refs = list(refs)
    for i in range(0, len(refs), 400):
        batch = db().batch()
        for r in refs[i:i + 400]:
            batch.delete(r)
        batch.commit()
    return len(refs)


if __name__ == "__main__":
    orphans = [d.reference for d in col("leads").select(["city"]).stream() if not d.to_dict().get("city")]
    cities = set()
    print("test leftovers removed:", delete_all(orphans), "leads,",
          delete_all(d.reference for d in col("campaigns").stream() if not d.to_dict().get("city")), "campaigns")
    print("old area docs removed:", delete_all(d.reference for d in col("areas").stream()))
    for c in col("campaigns").stream():
        if c.to_dict().get("city"):
            cities.add(c.to_dict()["city"])
    for city in sorted(cities):
        totals = leads.recompute_areas(city)
        for c in col("campaigns").where("city", "==", city).stream():
            c.reference.update({"stats.found": totals["total"], "stats.withEmail": totals["withEmail"], "stats.withPhone": totals["withPhone"]})
        print(city, totals)
