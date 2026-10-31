"""
The kinds of business Jarvis looks for. Each has where to find it on the map and the few
words that make the outreach email fit that business. Leads saved before categories
existed are hotels.

Where to find it:
- tomtom: (word, category id) pairs. TomTom's category search needs the category's own name
  in the URL, and one request returns one category, so each pair is one request. An empty
  id means a plain text search, kept only when the name matches `name_must`.
- osm: OpenStreetMap (tag, regex) rules. In India OpenStreetMap lists far more websites and
  emails than TomTom for hospitals, schools and restaurants, so both are searched.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    key: str
    label: str          # plural, for the UI and messages: "Hospitals & clinics"
    one: str            # one of them, lower case: "hospital or clinic"
    tomtom: tuple[tuple[str, str], ...]
    osm: tuple[tuple[str, str], ...]
    name_must: str      # regex a name must match for text searches ("" = keep all)
    # email wording
    fit: str            # "...a staff attendance and payroll tool that suits {fit} in {area}"
    place: str          # "a selfie and a GPS reading at your {place}"
    shifts: str         # one sentence on their kind of shifts and staff
    branch: str         # "If you run more than one {branch}..."


CATEGORIES: list[Category] = [
    Category("hotels", "Hotels", "hotel",
             (("hotel", "7314"),),
             (("tourism", "^(hotel|guest_house|motel|hostel)$"),), "",
             "hotels like yours", "hotel",
             "It works for night and overnight shifts.", "property"),
    Category("hospitals", "Hospitals & clinics", "hospital or clinic",
             (("hospital", "7321"), ("health care service", "9663"), ("doctor", "9373")),
             (("amenity", "^(hospital|clinic|doctors)$"), ("healthcare", "^(hospital|clinic|centre)$")), "",
             "hospitals and clinics like yours", "hospital",
             "It handles day, night and rotating shifts for doctors, nurses and support staff.", "branch or clinic"),
    Category("schools", "Schools & colleges", "school or college",
             (("school", "7372"), ("college", "7377")),
             (("amenity", "^(school|college|university)$"),), "",
             "schools and colleges like yours", "campus",
             "It covers teaching and non-teaching staff, and leave is applied for and approved from the phone.", "campus"),
    Category("restaurants", "Restaurants & cafés", "restaurant or café",
             (("restaurant", "7315"), ("cafe", "9376")),
             (("amenity", "^(restaurant|cafe)$"),), "",
             "restaurants and cafés like yours", "restaurant",
             "It handles late-night shifts and staff who check in more than once a day.", "outlet"),
    Category("factories", "Factories & warehouses", "factory or warehouse",
             (("manufacturing company", "9352011"), ("industrial building", "9383"),
              ("manufacturing facility", "9156"), ("warehouse", "9159")),
             (("man_made", "^works$"), ("building", "^(industrial|warehouse)$"), ("industrial", ".")), "",
             "factories and warehouses like yours", "site",
             "It handles day, night and rotating shifts for your whole workforce.", "site"),
    Category("retail", "Supermarkets & retail", "store",
             (("supermarket", "7332005"), ("department store", "7327"), ("shopping center", "7373")),
             (("shop", "^(supermarket|department_store|mall)$"),), "",
             "stores like yours", "store",
             "It handles opening and closing shifts and part-time staff.", "store"),
    Category("it", "IT & software companies", "IT company",
             (("software company", "9352005"),),
             (("office", "^(it|software|telecommunication)$"),), "",
             "IT and software companies like yours", "office",
             "It handles day and night shifts, and teams spread across more than one office.", "office"),
    Category("offices", "Corporate offices", "company",
             (("insurance company", "9352007"), ("construction company", "9352032"), ("real estate company", "9352009"),
              ("transport company", "9352024"), ("business services", "9352039"), ("electronics company", "9352015")),
             (("office", "^(company|insurance|estate_agent|logistics|financial|consulting|construction_company|accountant|employment_agency)$"),), "",
             "companies like yours", "office",
             "It handles shifts with grace time for late arrivals, and leave is applied for and approved from the phone.", "office or site"),
    Category("security", "Security agencies", "security agency",
             (("security services", ""),),
             (("office", "^security$"),), r"secur|guard|detective|facility management",
             "security agencies like yours", "site",
             "Guards check in at the site they're posted to, on day or night shifts, and each site gets its own check-in area.",
             "client site"),
    Category("gyms", "Gyms, salons & spas", "gym, salon or spa",
             (("fitness club", "7320002"), ("beauty salon", "9361067"), ("hairdresser", "9361027")),
             (("leisure", "^fitness_centre$"), ("shop", "^(beauty|hairdresser)$")), "",
             "gyms, salons and spas like yours", "centre",
             "It handles morning and evening shifts for trainers, stylists and front-desk staff.", "centre"),
    Category("coaching", "Coaching & training centres", "coaching centre",
             (("coaching centre", ""),),
             (("amenity", "^(prep_school|training)$"),), r"coach|academy|institute|classes|tutorial|tuition|training|iit|neet",
             "coaching and training centres like yours", "centre",
             "It covers faculty and office staff, and leave is applied for and approved from the phone.", "centre"),
]

BY_KEY = {c.key: c for c in CATEGORIES}
DEFAULT = "hotels"   # what leads saved before categories existed are
ALL = "all"          # a scan of every category


def get(key: str | None) -> Category:
    return BY_KEY.get((key or DEFAULT).lower(), BY_KEY[DEFAULT])


def resolve(key: str | None) -> list[Category]:
    """A scan's categories: every one for "all" (and for scans that don't say), else that one."""
    return CATEGORIES if not key or key == ALL else [get(key)]


def label_of(key: str | None) -> str:
    return "all businesses" if not key or key == ALL else get(key).label.lower()


def find(text: str) -> Category | None:
    """'schools', 'Hospitals & clinics', 'gym' -> the category; None if nothing matches."""
    t = (text or "").lower().strip()
    if not t:
        return None
    for c in CATEGORIES:
        words = {c.key, c.key.rstrip("s"), *c.label.lower().replace("&", " ").replace(",", " ").split(), *c.one.replace(",", " ").split()}
        words -= {"or", "and"}
        if t in words or t.rstrip("s") in words or t == c.label.lower():
            return c
    return None


def from_osm_tags(tags: dict, among: list["Category"]) -> "Category | None":
    """Which of these categories an OpenStreetMap place belongs to, by its tags."""
    for c in among:
        if any(re.search(rx, tags.get(k, "")) for k, rx in c.osm):
            return c
    return None
