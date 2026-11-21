"""
The portfolio site check: does a business have a website of its own, and is it any good?

Every business falls in one group:
  none     no website at all
  social   the "website" is a Facebook / Instagram / WhatsApp / Linktree page
  listing  the "website" is a listing (JustDial, Practo, Zomato, IndiaMART...) or a chain's page
  dead     the site doesn't load, has expired, or is a parked domain
  weak     it loads, but: no https, not set up for phones, not updated in years, slow,
           "coming soon", or on a free site-builder address
  ok       a working site with none of those problems (not a target)

The home page is read by the crawler (one request it makes anyway); this file only looks at it.
"""

import re
from urllib.parse import urlparse

import httpx

from ..timeutil import now_local

GROUPS = ("none", "social", "listing", "dead", "weak")
GROUP_LABELS = {
    "none": "No website",
    "social": "Social page only",
    "listing": "Listing page only",
    "dead": "Site doesn't work",
    "weak": "Weak website",
}

SOCIAL = ("facebook.com", "fb.com", "fb.me", "instagram.com", "wa.me", "whatsapp.com", "linktr.ee", "youtube.com",
          "twitter.com", "x.com", "linkedin.com", "t.me", "threads.net")
# free builder addresses: the business has a site, but not its own name on the web
FREE_BUILDERS = ("sites.google.com", ".wixsite.com", ".wordpress.com", ".blogspot.", ".weebly.com", ".godaddysites.com",
                 ".webnode.", ".jimdosite.com", ".mystrikingly.com", ".business.site", ".carrd.co", ".site123.me")
PARKED = ("domain is for sale", "buy this domain", "this domain may be for sale", "domain has expired", "domain expired",
          "sedoparking", "parkingcrew", "hugedomains", "account has been suspended", "account suspended",
          "this site can't be reached", "website is under maintenance", "default web site page",
          "apache2 ubuntu default page", "welcome to nginx", "index of /")
COMING_SOON = ("coming soon", "under construction", "launching soon", "website is being built")
YEAR_RE = re.compile(r"(?:©|&copy;|&#169;|copyright)[^0-9<]{0,30}((?:19|20)\d{2})(?:\s*(?:-|–|&ndash;|to)\s*((?:19|20)\d{2}))?", re.I)
VIEWPORT_RE = re.compile(r"<meta[^>]+name=[\"']?viewport", re.I)
SLOW_SECONDS = 8
OLD_YEARS = 3          # copyright this many years behind (or more) counts as not updated
# a site that refuses robots like us isn't broken: don't call it dead
BOT_BLOCKED = (401, 403, 406, 429, 503)

ISSUE_LABELS = {
    "no_https": "Not secure (no https)",
    "not_mobile": "Not set up for phones",
    "old": "Not updated since {year}",
    "slow": "Slow to load ({seconds}s)",
    "coming_soon": "Says “coming soon”",
    "free_builder": "On a free site-builder address",
    "parked": "Domain parked or expired",
    "error": "Shows an error ({status})",
    "no_load": "Doesn't load",
}


def host(url: str) -> str:
    h = urlparse(url if "//" in url else f"//{url}").netloc.lower()
    return h.removeprefix("www.")


def _on(h: str, domains: tuple[str, ...]) -> bool:
    return any(h == d or h.endswith("." + d) for d in domains)


def read_home(r: httpx.Response, seconds: float) -> dict:
    """What the home page shows, kept small: it's stored on the prospect."""
    out = {"status": r.status_code, "https": str(r.url).startswith("https://"), "seconds": round(seconds, 1),
           "finalHost": host(str(r.url))}
    if "html" not in r.headers.get("content-type", "") or r.status_code >= 400:
        return out
    html = r.text[:400_000]
    low = html.lower()
    years = [int(y) for pair in YEAR_RE.findall(html) for y in pair if y]
    text_len = len(re.sub(r"<[^>]+>|\s+", "", re.sub(r"<(script|style)[^>]*>.*?</\1>", "", low, flags=re.S)))
    return out | {
        "mobile": bool(VIEWPORT_RE.search(html)),
        "year": max(years) if years else None,
        "parked": any(p in low for p in PARKED),
        # "coming soon" on a near-empty page; a full page may mention a new branch coming soon
        "comingSoon": text_len < 1500 and any(c in low for c in COMING_SOON),
    }


def failed_home(e: Exception) -> dict:
    return {"status": 0, "error": type(e).__name__}


def classify(website: str, home: dict | None) -> tuple[str, list[str]]:
    """-> (group, issue codes). `home` is the crawler's "home" (None when the site wasn't read).
    Issue codes carry their detail: "old:2019", "slow:11.2", "error:404"."""
    from .crawler import is_aggregator   # crawler imports this module

    if not website:
        return "none", []
    h = host(website)
    if _on(h, SOCIAL):
        return "social", []
    if is_aggregator(website):
        return "listing", []
    if home is None:
        return "ok", []            # not read (e.g. the check was off): say nothing about it
    final = home.get("finalHost") or h
    if final != h and (_on(final, SOCIAL) or is_aggregator(final)):
        return ("social" if _on(final, SOCIAL) else "listing"), []   # the domain only forwards to a page elsewhere
    status = home.get("status", 0)
    if status in BOT_BLOCKED:
        return "ok", []            # it's there; it just won't talk to robots
    if status == 0:
        return "dead", ["no_load"]
    if status >= 400:
        return "dead", [f"error:{status}"]
    if home.get("parked"):
        return "dead", ["parked"]
    issues = []
    if home.get("comingSoon"):
        issues.append("coming_soon")
    if any(f".{d.strip('.')}." in f".{final}." for d in FREE_BUILDERS):
        issues.append("free_builder")
    if not home.get("https"):
        issues.append("no_https")
    if home.get("mobile") is False:
        issues.append("not_mobile")
    year = home.get("year")
    if year and year <= now_local().year - OLD_YEARS:
        issues.append(f"old:{year}")
    if home.get("seconds", 0) >= SLOW_SECONDS:
        issues.append(f"slow:{home['seconds']:g}")
    return ("weak" if issues else "ok"), issues


def issue_text(code: str) -> str:
    key, _, detail = code.partition(":")
    label = ISSUE_LABELS.get(key, key)
    return label.format(year=detail, seconds=detail, status=detail)
