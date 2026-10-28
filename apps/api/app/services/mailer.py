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

from ..config import get_settings
from . import gmail


def build(to: str, subject: str, body: str, in_reply_to: str | None) -> EmailMessage:
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
    return msg


def _smtp_send(msg: EmailMessage) -> None:
    s = get_settings()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as smtp:
        smtp.login(s.email_address, s.email_app_password)
        smtp.send_message(msg)


async def send(to: str, subject: str, body: str, in_reply_to: str | None = None, thread_id: str | None = None) -> tuple[str, str | None]:
    """-> (Message-ID, Gmail thread id or None). Both are stored to match replies and thread follow-ups."""
    msg = build(to, subject, body, in_reply_to)
    if gmail.enabled():
        return await gmail.send(msg, thread_id)
    await asyncio.to_thread(_smtp_send, msg)
    return msg["Message-ID"], None
