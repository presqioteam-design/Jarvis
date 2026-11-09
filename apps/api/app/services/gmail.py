"""
Gmail API over HTTPS, for hosts that block email ports (Render's free plan).
Uses a refresh token from a one-time sign-in: python -m scripts.gmail_token
"""

import base64
import time
from email.message import EmailMessage

import httpx

from ..config import get_settings

API = "https://gmail.googleapis.com/gmail/v1/users/me"
_token: dict = {"value": "", "expires": 0.0}


def enabled() -> bool:
    s = get_settings()
    return bool(s.gmail_client_id and s.gmail_client_secret and s.gmail_refresh_token)


async def _access_token(client: httpx.AsyncClient) -> str:
    if _token["value"] and _token["expires"] > time.time() + 60:
        return _token["value"]
    s = get_settings()
    r = await client.post("https://oauth2.googleapis.com/token", data={
        "client_id": s.gmail_client_id, "client_secret": s.gmail_client_secret,
        "refresh_token": s.gmail_refresh_token, "grant_type": "refresh_token",
    })
    r.raise_for_status()
    data = r.json()
    _token.update(value=data["access_token"], expires=time.time() + data.get("expires_in", 3600))
    return _token["value"]


async def _headers(client: httpx.AsyncClient) -> dict:
    return {"Authorization": f"Bearer {await _access_token(client)}"}


class SendingLimited(Exception):
    """Gmail is refusing to send for now (403/429): a sending limit or a temporary spam hold.
    The message is Google's own reason, in a sentence."""


class ReadRefused(Exception):
    """Gmail is refusing to let us read the inbox (403/429). The message is Google's own reason."""


def _reason(r: httpx.Response) -> str:
    try:
        err = r.json().get("error", {})
        why = (err.get("errors") or [{}])[0].get("reason", "")
        return f"{err.get('message', '').strip()} ({why})" if why else err.get("message", "").strip()
    except ValueError:
        return r.text[:200]


async def send(msg: EmailMessage, thread_id: str | None) -> tuple[str, str]:
    """-> (Message-ID header as delivered, Gmail thread id)."""
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{API}/messages/send", headers=await _headers(client),
                              json={"raw": raw, **({"threadId": thread_id} if thread_id else {})})
        if r.status_code in (403, 429):
            raise SendingLimited(_reason(r) or f"Gmail refused with {r.status_code}")
        r.raise_for_status()
        sent = r.json()
        # read back the Message-ID Gmail kept, so replies and follow-ups match it
        m = await client.get(f"{API}/messages/{sent['id']}", headers=await _headers(client),
                             params={"format": "metadata", "metadataHeaders": "Message-ID"})
        m.raise_for_status()
        header = next((h["value"] for h in m.json()["payload"].get("headers", []) if h["name"].lower() == "message-id"), msg["Message-ID"])
    return header, sent["threadId"]


def _check_read(r: httpx.Response) -> None:
    if r.status_code in (403, 429):
        raise ReadRefused(_reason(r) or f"Gmail refused with {r.status_code}")
    r.raise_for_status()


async def recent_raw(days: int) -> list[bytes]:
    """Raw RFC 822 bytes of inbox messages from the last `days` days."""
    out: list[bytes] = []
    async with httpx.AsyncClient(timeout=30) as client:
        ids, page = [], None
        while True:
            r = await client.get(f"{API}/messages", headers=await _headers(client),
                                 params={"q": f"in:inbox newer_than:{days}d", "maxResults": 100, **({"pageToken": page} if page else {})})
            _check_read(r)
            data = r.json()
            ids += [m["id"] for m in data.get("messages", [])]
            page = data.get("nextPageToken")
            if not page or len(ids) >= 500:
                break
        for mid in ids:
            r = await client.get(f"{API}/messages/{mid}", headers=await _headers(client), params={"format": "raw"})
            _check_read(r)
            out.append(base64.urlsafe_b64decode(r.json()["raw"]))
    return out
