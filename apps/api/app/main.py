import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import chat, jobs, telegram

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Jarvis API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_list,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(chat.router)
app.include_router(jobs.router)
app.include_router(telegram.router)


@app.get("/health")
def health():
    return {"ok": True}
