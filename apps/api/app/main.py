import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import campaigns, chat, jobs, telegram
from .services import chat as chat_service, inbox, telegram as telegram_service

logging.basicConfig(level=logging.INFO)
# httpx logs full request URLs, and Telegram URLs contain the bot token
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # locally there's no public URL for a webhook, so listen to Telegram by polling
    s = get_settings()
    tasks = [asyncio.create_task(inbox.watch())]   # runs while awake; the cron worker covers sleep
    if telegram_service.enabled():
        if s.telegram_mode == "webhook" and s.render_external_url and s.telegram_webhook_secret:
            await telegram_service.set_webhook()
        elif s.telegram_mode == "polling":
            tasks.append(asyncio.create_task(telegram_service.poll(chat_service.on_telegram)))
            logging.info("Listening for Telegram messages (polling)")
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Jarvis API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(campaigns.router)
app.include_router(chat.router)
app.include_router(jobs.router)
app.include_router(telegram.router)


@app.get("/health")
def health():
    return {"ok": True}
