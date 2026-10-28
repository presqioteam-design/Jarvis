"""
Find emails and phone numbers on a hotel's own website.
Reads the home page plus up to two contact/about pages; nothing else.
"""

import asyncio
import re
from urllib.parse import urljoin, urlparse

import httpx

from .sources import clean_phone

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
TEL_RE = re.compile(r'href=["\']tel:([^"\']+)', re.I)
LINK_RE = re.compile(r'href=["\']([^"\'#]+)', re.I)
CONTACT_WORDS = ("contact", "about", "reach", "enquiry", "inquiry", "booking")

# addresses that show up on websites but aren't the hotel's
JUNK_DOMAINS = ("example.com", "sentry.io", "wixpress.com", "domain.com", "email.com", "yourdomain", "godaddy.com", "w3.org")
JUNK_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")
# chains and booking sites: their emails reach head office, not the hotel owner
AGGREGATORS = (
    "oyorooms.com", "oyohotels.com", "fabhotels.com", "treebo", "staybloom.com", "zostel.com", "goibibo.com",
    "makemytrip.com", "booking.com", "agoda.com", "airbnb.", "expedia.", "tripadvisor.", "trivago.", "cleartrip.com",
)


def is_aggregator(url_or_email: str) -> bool:
    return any(a in url_or_email.lower() for a in AGGREGATORS)


HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PresqioJarvis/0.1; +https://presqio.pages.dev)"}


def extract_emails(html: str) -> list[str]:
    found = []
    html = re.sub(r"\\?u003[ce]", " ", html, flags=re.I)   # JSON-escaped < and > glue onto addresses
    for e in EMAIL_RE.findall(html):
        e = e.lower().strip(".")
        if e.endswith(JUNK_SUFFIXES) or any(d in e for d in JUNK_DOMAINS) or is_aggregator(e) or e in found:
            continue
        found.append(e)
    return found


def contact_links(html: str, base: str) -> list[str]:
    host = urlparse(base).netloc
    links = []
    for href in LINK_RE.findall(html):
        url = urljoin(base, href)
        if urlparse(url).netloc == host and any(w in url.lower() for w in CONTACT_WORDS) and url not in links:
            links.append(url)
    return links[:2]


async def crawl(client: httpx.AsyncClient, website: str) -> dict:
    """-> {"emails": [...], "phone": "+91..." or ""}; never raises."""
    emails: list[str] = []
    phone = ""
    pages = [website]
    seen = set()
    while pages and len(seen) < 3:
        url = pages.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            r = await client.get(url)
            if r.status_code >= 400 or "html" not in r.headers.get("content-type", ""):
                continue
        except (httpx.HTTPError, ValueError):
            continue
        html = r.text
        emails += [e for e in extract_emails(html) if e not in emails]
        if not phone:
            tels = TEL_RE.findall(html)
            phone = clean_phone(tels[0]) if tels else ""
        if len(seen) == 1:
            pages += contact_links(html, str(r.url))
    return {"emails": emails[:3], "phone": phone}


async def crawl_many(websites: list[str], concurrency: int = 6) -> dict[str, dict]:
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers=HEADERS) as client:
        async def one(site: str):
            async with sem:
                return site, await crawl(client, site)
        return dict(await asyncio.gather(*(one(s) for s in websites)))
