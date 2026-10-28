import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from ..config import get_settings
from ..services import chat, telegram

log = logging.getLogger(__name__)
router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post("/webhook")
async def webhook(request: Request, x_telegram_bot_api_secret_token: str = Header(default="")):
    s = get_settings()
    if not s.telegram_webhook_secret or not hmac.compare_digest(
        x_telegram_bot_api_secret_token, s.telegram_webhook_secret
    ):
        raise HTTPException(401, "Bad secret")

    update = await request.json()
    msg = update.get("message") or {}
    text = msg.get("text")
    chat_id = str(msg.get("chat", {}).get("id", ""))

    # only answer you
    if not text or chat_id != s.telegram_chat_id:
        return {"ok": True}

    # always answer 200: on an error Telegram would resend the update and duplicate the message
    try:
        reply = await chat.handle(text, channel="telegram")
    except Exception:
        log.exception("Chat failed for Telegram message")
        reply = "Sorry, I hit an error answering that. Try again in a minute."
    await telegram.send(reply)
    return {"ok": True}
