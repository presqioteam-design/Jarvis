"""
One-off: delete leads that have no email and no phone (status no_contact),
then rebuild each city's totals and search list.
    cd apps/api && .venv/bin/python -m scripts.remove_no_contact
"""

from google.cloud.firestore_v1.base_query import FieldFilter

from app.firebase import col, db
from app.services import leads

if __name__ == "__main__":
    refs, cities = [], set()
    for d in col("leads").where(filter=FieldFilter("status", "==", "no_contact")).select(["city"]).stream():
        refs.append(d.reference)
        cities.add(d.to_dict().get("city"))
    for i in range(0, len(refs), 400):
        batch = db().batch()
        for r in refs[i:i + 400]:
            batch.delete(r)
        batch.commit()
    print("deleted", len(refs), "leads with no contact details")
    for city in filter(None, cities):
        print(city, leads.recompute_areas(city))
