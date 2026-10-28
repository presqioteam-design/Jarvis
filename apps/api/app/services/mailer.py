"""Send email through the outreach Gmail account (SMTP with an App Password)."""

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from ..config import get_settings


def _send(to: str, subject: str, body: str, in_reply_to: str | None) -> str:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = formataddr((s.sender_name, s.email_address))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=s.email_address.split("@")[-1])
    # lets Gmail/Outlook show their own "unsubscribe" button, which helps deliverability
    msg["List-Unsubscribe"] = f"<mailto:{s.email_address}?subject=stop>"
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as smtp:
        smtp.login(s.email_address, s.email_app_password)
        smtp.send_message(msg)
    return msg["Message-ID"]


async def send(to: str, subject: str, body: str, in_reply_to: str | None = None) -> str:
    """Returns the Message-ID, used later to match replies and thread follow-ups."""
    return await asyncio.to_thread(_send, to, subject, body, in_reply_to)
