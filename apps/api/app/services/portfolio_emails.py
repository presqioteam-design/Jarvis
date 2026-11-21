"""
Portfolio emails: Vinod offering to build a business's website. They go out from the Presqio outreach
mailbox (replies come back there and Jarvis reads them), and give Vinod's own email and phone in the
text. Fixed wording (not AI-written), so
every email is accurate; only the business's name, area, kind and what was found about its
website are filled in. Plain text, one link, an opt-out line: this keeps Gmail from flagging them.

Three emails: the first, then two short follow-ups sent as replies in the same thread.
"""

from dataclasses import dataclass

from . import categories, site_check


@dataclass
class Email:
    subject: str
    body: str


DEFAULTS = {"senderName": "Jatoth Vinod", "phone": "+91 63093 87321", "email": "vinodnayakj.321@gmail.com",
            "website": "https://jatothvinod.services"}

# per kind of business: who looks them up, and what those people want to see
AUDIENCE: dict[str, tuple[str, str]] = {
    "hotels": ("guests", "your rooms, photos, prices and location, with a button to call or book"),
    "hospitals": ("patients", "your doctors, timings, services and location, with a button to call or book an appointment"),
    "schools": ("parents", "your classes, facilities, fees and admissions, with an enquiry form that comes straight to you"),
    "restaurants": ("customers", "your menu, photos, timings and location, with a button to call or order"),
    "factories": ("buyers", "your products, capacity and certifications, with an enquiry form that comes straight to you"),
    "retail": ("customers", "what you sell, your timings and location, with a button to call or WhatsApp"),
    "it": ("clients", "your services, past work and team, with a contact form that comes straight to you"),
    "offices": ("clients", "your services and team, with a contact form that comes straight to you"),
    "security": ("clients", "your services, the sites you cover and your licences, with a contact form"),
    "gyms": ("members", "your plans, timings, trainers and photos, with a button to call or WhatsApp"),
    "coaching": ("students and parents", "your courses, batches, results and fees, with an enquiry form"),
}
DEFAULT_AUDIENCE = ("customers", "your services, timings and location, with a button to call or WhatsApp")

# how each website problem reads in a sentence ("A few things may be costing you visitors: ...")
ISSUE_PHRASES = {
    "no_https": "browsers mark it “Not secure”",
    "not_mobile": "it isn't set up for phones",
    "old": "it looks like it hasn't been updated since {d}",
    "slow": "it took about {d} seconds to open",
    "coming_soon": "it still says “coming soon”",
    "free_builder": "it's on a free site-builder address rather than your own name",
}
PLATFORMS = {
    "facebook": "Facebook", "fb.": "Facebook", "instagram": "Instagram", "wa.me": "WhatsApp", "whatsapp": "WhatsApp",
    "linktr.ee": "Linktree", "youtube": "YouTube", "linkedin": "LinkedIn", "justdial": "JustDial", "practo": "Practo",
    "sulekha": "Sulekha", "indiamart": "IndiaMART", "zomato": "Zomato", "swiggy": "Swiggy", "magicpin": "magicpin",
    "lybrate": "Lybrate", "shiksha": "Shiksha", "collegedunia": "Collegedunia", "tradeindia": "TradeIndia",
    "oyo": "OYO", "makemytrip": "MakeMyTrip", "booking.com": "Booking.com", "goibibo": "Goibibo", "tripadvisor": "Tripadvisor",
}

OPT_OUT = 'If you\'d rather not hear from me, reply "stop" and I won\'t email you again.'

SIGNATURE = """Regards,
{sender}
Web & app developer
{phone} (call or WhatsApp)
{email}
{website}"""


def platform(url: str) -> str:
    low = url.lower()
    return next((name for key, name in PLATFORMS.items() if key in low), "a listing site")


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def finding(p: dict) -> str:
    """The one sentence about their website that makes the email about them."""
    name, site, url = p["name"].strip(), p.get("site"), p.get("website", "")
    host = site_check.host(url) if url else ""
    if site == "social":
        return (f"I came across {name}'s {platform(url)} page. It's a good start, but it isn't a website of your own, "
                "so people searching on Google often don't find it, and it can't show everything you offer.")
    if site == "listing":
        return (f"I found {name} on {platform(url)}, but couldn't find a website of your own. On a listing site, "
                "your page sits right next to your competitors', and you can't make it look like you.")
    if site == "dead":
        codes = [i.split(":")[0] for i in p.get("issues", [])]
        what = ("shows that the domain has expired or is parked" if "parked" in codes
                else "shows an error" if "error" in codes else "doesn't load")
        return f"I tried to open {host} and it {what}. Anyone who looks you up sees the same, and may go elsewhere."
    if site == "weak":
        phrases = []
        for code in p.get("issues", []):
            key, _, d = code.partition(":")
            if key in ISSUE_PHRASES:
                phrases.append(ISSUE_PHRASES[key].format(d=d))
        if phrases:
            return f"I had a look at {host}. A few things may be costing you visitors: {_join(phrases[:3])}."
        return f"I had a look at {host}, and I think it could be bringing you a lot more enquiries."
    area = p.get("area") or "your area"
    return (f"I was looking at businesses in {area} and couldn't find a website for {name}, so people searching "
            "on Google only find a map pin and a phone number.")


def subject_for(p: dict) -> str:
    name = p["name"].strip()
    return {
        "none": f"A website for {name}",
        "social": f"A website of your own for {name}",
        "listing": f"A website of your own for {name}",
        "dead": f"{name}'s website isn't working",
        "weak": f"A quick note on {name}'s website",
    }.get(p.get("site", ""), f"A website for {name}")


FIRST = """Hello {name} team,

{finding}

I'm Vinod, an independent web developer (IIT Kharagpur). I build fast, mobile-friendly websites that help {audience} find you on Google and see {shows}. You get a site on your own name that's easy to update, without paying an agency.

I also build online stores and QR ordering, booking and admin tools, Android and iOS apps, SEO, and automations like automated emails and AI assistants. You can see my work here: {website}

For a free quote for {name}, just reply to this email, write to me at {email}, or call or WhatsApp me on {phone}.

{signature}

{opt_out}"""

FOLLOW_UP_1 = """Hello again,

A quick follow-up about a website for {name}.

Most people now check a business on Google before they call or visit. A simple website of your own turns those searches into enquiries, and it works for you all day, even when you're busy.

Happy to send a free quote with no obligation. Just reply with a good time to talk, write to me at {email}, or call or WhatsApp me on {phone}.

{signature}

{opt_out}"""

FOLLOW_UP_2 = """Hello,

This is my last note about a website for {name}.

If it isn't a priority right now, no problem, and I won't follow up again. If it ever is, you can reach me on {phone} or at {email}, and see my work at {website}.

Thank you for your time.

{signature}"""

SEQUENCE = [FIRST, FOLLOW_UP_1, FOLLOW_UP_2]


def render(step: int, p: dict, me: dict | None = None) -> Email:
    """step 0 = first email; 1 and 2 are follow-ups sent as replies in the same thread.
    `p` is a prospect (name, category, area, site, issues, website); `me` the sender details."""
    me = DEFAULTS | {k: v for k, v in (me or {}).items() if v}
    audience, shows = AUDIENCE.get(categories.get(p.get("category")).key, DEFAULT_AUDIENCE)
    fields = {"name": p["name"].strip(), "finding": finding(p), "audience": audience, "shows": shows,
              "phone": me["phone"], "email": me["email"], "website": me["website"]}
    signature = SIGNATURE.format(sender=me["senderName"], phone=me["phone"], email=me["email"], website=me["website"])
    subject = subject_for(p)
    body = SEQUENCE[step].format(**fields, signature=signature, opt_out=OPT_OUT)
    return Email(subject=subject if step == 0 else f"Re: {subject}", body=body)
