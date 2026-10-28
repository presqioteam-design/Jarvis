import hmac

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from ..config import get_settings
from ..services import chat

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
    text = msg.get("text")
    chat_id = str(msg.get("chat", {}).get("id", ""))

    # only answer you; reply in the background so Telegram never retries the update
    if text and chat_id == s.telegram_chat_id:
        background.add_task(chat.on_telegram, text)
    return {"ok": True}
