import logging

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)


def enabled() -> bool:
    s = get_settings()
    return bool(s.telegram_bot_token and s.telegram_chat_id)


async def send(text: str) -> None:
    """Send a message to your own chat. No-op if Telegram isn't configured."""
    if not enabled():
        return
    s = get_settings()
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
            json={"chat_id": s.telegram_chat_id, "text": text[:4000]},
        )
        if r.status_code != 200:
            log.warning("Telegram send failed: %s %s", r.status_code, r.text)
