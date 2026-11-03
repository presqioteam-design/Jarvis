"""
Send email from the outreach Gmail account.
Uses the Gmail API (HTTPS) when it's set up, otherwise SMTP with an App Password.
Render's free plan blocks SMTP ports, so deployments need the Gmail API.
"""

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import httpx

from ..config import get_settings
from . import gmail
from .gmail import SendingLimited   # re-exported: callers catch mailer.SendingLimited


class MailSetupError(RuntimeError):
    """Sending can't work with the current settings; stop the batch instead of retrying."""


def mode() -> str:
    return "gmail-api" if gmail.enabled() else "smtp"


def build(to: str, subject: str, body: str, in_reply_to: str | None, sender_name: str | None = None) -> EmailMessage:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = formataddr((sender_name or s.sender_name, s.email_address))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=s.email_address.split("@")[-1])
    # lets Gmail/Outlook show their own "unsubscribe" button, which helps deliverability
    msg["List-Unsubscribe"] = f"<mailto:{s.email_address}?subject=stop>"
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)
    return msg


def _smtp_send(msg: EmailMessage) -> None:
    s = get_settings()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as smtp:
        smtp.login(s.email_address, s.email_app_password)
        smtp.send_message(msg)


async def send(to: str, subject: str, body: str, in_reply_to: str | None = None, thread_id: str | None = None,
               sender_name: str | None = None) -> tuple[str, str | None]:
    """-> (Message-ID, Gmail thread id or None). Both are stored to match replies and thread follow-ups."""
    msg = build(to, subject, body, in_reply_to, sender_name)
    if gmail.enabled():
        return await gmail.send(msg, thread_id)
    if get_settings().render_external_url:
        # Render's free plan blocks SMTP ports, so trying would only fail with OSError
        raise MailSetupError(
            "The Gmail API isn't set up on Render. Add GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET and GMAIL_REFRESH_TOKEN "
            "in Render → Environment, then redeploy."
        )
    await asyncio.to_thread(_smtp_send, msg)
    return msg["Message-ID"], None


# ── is the address worth sending to? ─────────────────────────────────────────
# A domain that doesn't exist or takes no email gives an instant bounce, and bounces are what
# make Google throttle the account. One free DNS lookup per domain (Google's DNS over HTTPS)
# catches them before sending. Answers are kept for the life of the server.

BIG_PROVIDERS = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "outlook.com", "hotmail.com", "live.com",
                 "rediffmail.com", "icloud.com", "zoho.com", "protonmail.com", "aol.com"}
_domain_ok: dict[str, bool] = {}


async def accepts_email(address: str) -> bool:
    """False only when DNS says the domain doesn't exist or has no mail server. Unsure -> True."""
    domain = address.rsplit("@", 1)[-1].lower().strip()
    if domain in BIG_PROVIDERS:
        return True
    if domain in _domain_ok:
        return _domain_ok[domain]
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            mx = (await client.get("https://dns.google/resolve", params={"name": domain, "type": "MX"})).json()
            if mx.get("Status") == 3:   # NXDOMAIN: the domain doesn't exist
                ok = False
            elif any(a.get("type") == 15 for a in mx.get("Answer", [])):
                ok = True
            else:   # no MX: mail falls back to the domain's own address, if it has one
                a = (await client.get("https://dns.google/resolve", params={"name": domain, "type": "A"})).json()
                ok = any(x.get("type") == 1 for x in a.get("Answer", []))
    except (httpx.HTTPError, ValueError):
        return True   # can't tell: don't hold the email back
    _domain_ok[domain] = ok
    return ok
