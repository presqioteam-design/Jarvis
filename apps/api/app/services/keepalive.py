"""
Render's free plan sleeps after 15 minutes without incoming requests, even if a
job is still running. While a long job runs, ping our own public URL so the
instance counts as busy. Does nothing locally (no public URL).
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)
EVERY_SECONDS = 240


async def _ping_forever(url: str) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        while True:
            await asyncio.sleep(EVERY_SECONDS)
            try:
                await client.get(f"{url}/health")
            except httpx.HTTPError:
                log.warning("Keep-alive ping failed")


@asynccontextmanager
async def awake():
    url = get_settings().render_external_url.rstrip("/")
    task = asyncio.create_task(_ping_forever(url)) if url else None
    try:
        yield
    finally:
        if task:
            task.cancel()
