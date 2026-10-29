import hmac

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from ..config import get_settings
from ..services import chat, telegram

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks, x_telegram_bot_api_secret_token: str = Header(default="")):
    """Used when deployed (TELEGRAM_MODE=webhook). Locally the API polls Telegram instead."""
    s = get_settings()
    if not s.telegram_webhook_secret or not hmac.compare_digest(
        x_telegram_bot_api_secret_token, s.telegram_webhook_secret
    ):
        raise HTTPException(401, "Bad secret")

    update = await request.json()
    msg = update.get("message") or {}
    # only answer you; reply in the background so Telegram never retries the update
    if telegram.wanted(msg):
        background.add_task(chat.on_telegram_message, msg)
    return {"ok": True}
