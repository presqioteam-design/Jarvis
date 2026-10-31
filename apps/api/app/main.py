import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google.api_core.exceptions import ResourceExhausted

from .config import get_settings
from .routers import campaigns, chat, jobs, settings, telegram, voice
from .services import chat as chat_service, inbox, leads, telegram as telegram_service

logging.basicConfig(level=logging.INFO)
# httpx logs full request URLs, and Telegram URLs contain the bot token
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # locally there's no public URL for a webhook, so listen to Telegram by polling
    s = get_settings()
    tasks = [asyncio.create_task(inbox.watch())]   # runs while awake; the cron worker covers sleep
    # a deploy or restart kills running scans; their progress is saved, so carry on
    try:
        for campaign_id in leads.interrupted():
            logging.info("Resuming interrupted scan %s", campaign_id)
            tasks.append(asyncio.create_task(leads.run_campaign(campaign_id)))
    except Exception:
        # e.g. Firestore over its daily quota; the server must still start (voice, Telegram, health)
        logging.exception("Couldn't look for interrupted scans; they resume after the next restart")
    if telegram_service.enabled():
        if s.telegram_mode == "webhook" and s.render_external_url and s.telegram_webhook_secret:
            await telegram_service.set_webhook()
        elif s.telegram_mode == "polling":
            tasks.append(asyncio.create_task(telegram_service.poll(chat_service.on_telegram_message)))
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



@app.exception_handler(ResourceExhausted)
async def database_quota_used_up(_request: Request, _exc: ResourceExhausted):
    # handled here (not as a bare 500) so the reply keeps its CORS headers and the page shows why
    return JSONResponse(status_code=503, content={"detail": (
        "Jarvis's free database limit for today is used up. It resets around 12:30 PM IST.")})


app.include_router(campaigns.router)
app.include_router(chat.router)
app.include_router(jobs.router)
app.include_router(settings.router)
app.include_router(telegram.router)
app.include_router(voice.router)


@app.get("/health")
def health():
    # shows which way email goes out; on Render it must be "gmail-api"
    from .services import mailer
    return {"ok": True, "mail": mailer.mode()}
