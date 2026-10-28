"""
Telegram: send messages to the admin, and (in polling mode) receive them.

Polling is for running on your own computer: no public URL needed. When the
API is deployed, set TELEGRAM_MODE=webhook and register /telegram/webhook.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)
LIMIT = 4000   # Telegram allows 4096 characters per message


def enabled() -> bool:
    s = get_settings()
    return bool(s.telegram_bot_token and s.telegram_chat_id)


def api(method: str) -> str:
    return f"https://api.telegram.org/bot{get_settings().telegram_bot_token}/{method}"


def chunks(text: str) -> list[str]:
    """Split on line breaks so long lists arrive as several readable messages."""
    out, current = [], ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > LIMIT and current:
            out.append(current)
            current = ""
        current += line[:LIMIT]
    return [*out, current] if current else out


async def send(text: str) -> None:
    """Send a message to your own chat. No-op if Telegram isn't configured."""
    if not enabled():
        return
    async with httpx.AsyncClient(timeout=15) as client:
        for part in chunks(text):
            r = await client.post(api("sendMessage"), json={"chat_id": get_settings().telegram_chat_id, "text": part})
            if r.status_code != 200:
                log.warning("Telegram send failed: %s %s", r.status_code, r.text)


async def typing() -> None:
    if enabled():
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(api("sendChatAction"), json={"chat_id": get_settings().telegram_chat_id, "action": "typing"})


async def set_webhook() -> None:
    """When deployed, point Telegram at /telegram/webhook (with our secret) on startup."""
    s = get_settings()
    url = f"{s.render_external_url.rstrip('/')}/telegram/webhook"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(api("setWebhook"), json={
            "url": url, "secret_token": s.telegram_webhook_secret, "allowed_updates": ["message"],
        })
    log.info("Telegram webhook -> %s: %s", url, r.json().get("description", r.status_code))


async def poll(handle: Callable[[str], Awaitable[None]]) -> None:
    """Long-poll for the admin's messages forever. Messages from anyone else are ignored."""
    s = get_settings()
    async with httpx.AsyncClient(timeout=40) as client:
        await client.post(api("deleteWebhook"))   # polling and a webhook can't both be active
        offset = 0
        while True:
            try:
                r = await client.get(api("getUpdates"), params={"timeout": 30, "offset": offset})
                updates = r.json().get("result", [])
            except (httpx.HTTPError, ValueError):
                await asyncio.sleep(5)
                continue
            for u in updates:
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                if msg.get("text") and str(msg.get("chat", {}).get("id")) == s.telegram_chat_id:
                    asyncio.create_task(handle(msg["text"]))
