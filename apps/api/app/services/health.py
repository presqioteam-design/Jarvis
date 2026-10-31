"""
Whether each outside service Jarvis depends on is working, for the Settings page.
Checks use free calls (no email is sent, no AI is used) and are cached for a minute;
TomTom's check costs one map search, so it only runs when asked. Keys are never returned.
"""

import asyncio
import time
from datetime import datetime, timedelta

import httpx

from ..config import get_settings
from ..timeutil import now_local, now_utc
from . import dbusage, gmail, prefs, telegram

_cache: tuple[float, dict] | None = None
_tomtom: dict | None = None


def _ok(detail: str) -> dict:
    return {"ok": True, "detail": detail}


def _bad(detail: str) -> dict:
    return {"ok": False, "detail": detail}


async def _gmail(client: httpx.AsyncClient) -> dict:
    if not gmail.enabled():
        return _bad("The Gmail API isn't set up: add GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET and GMAIL_REFRESH_TOKEN in Render.")
    try:
        r = await client.get(f"{gmail.API}/profile", headers=await gmail._headers(client))
        r.raise_for_status()
        return _ok(f"Sending as {r.json().get('emailAddress', get_settings().email_address)}")
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (400, 401):
            return _bad("Google refused the sign-in: the refresh token has expired or was revoked. Run scripts/gmail_token again.")
        return _bad(f"Gmail answered with an error ({e.response.status_code}).")
    except httpx.HTTPError:
        return _bad("Couldn't reach Gmail.")


async def _telegram(client: httpx.AsyncClient) -> dict:
    if not telegram.enabled():
        return _bad("Telegram isn't set up: add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in Render.")
    try:
        me = (await client.get(telegram.api("getMe"))).json()
        if not me.get("ok"):
            return _bad("Telegram refused the bot token: create a new one with @BotFather and update Render.")
        name = f"@{me['result']['username']}"
        if get_settings().telegram_mode != "webhook":
            return _ok(f"{name}, listening by polling")
        hook = (await client.get(telegram.api("getWebhookInfo"))).json().get("result", {})
        if not hook.get("url"):
            return _bad(f"{name} has no webhook: messages to the bot won't reach Jarvis. Restart the server to register it.")
        if hook.get("last_error_date") and time.time() - hook["last_error_date"] < 3600:
            return _bad(f"{name}: Telegram couldn't deliver a message recently ({hook.get('last_error_message', 'unknown error')}).")
        return _ok(f"{name}, receiving messages")
    except httpx.HTTPError:
        return _bad("Couldn't reach Telegram.")


async def _gemini(client: httpx.AsyncClient) -> dict:
    key = get_settings().gemini_api_key
    if not key:
        return _bad("No Gemini key: add GEMINI_API_KEY in Render.")
    try:
        r = await client.get("https://generativelanguage.googleapis.com/v1beta/models", params={"pageSize": 1},
                             headers={"x-goog-api-key": key})
        if r.status_code in (400, 401, 403):
            return _bad("Google refused the Gemini key: make a new one in Google AI Studio and update Render.")
        r.raise_for_status()
        return _ok("Key works (chat, voice calls, voice notes)")
    except httpx.HTTPError:
        return _bad("Couldn't reach Gemini.")


def _usage_permission() -> dict:
    db = dbusage.today()
    if db.get("error") == "permission":
        return _bad("Not granted yet: the database meters on the Usage tab show how (Monitoring Viewer role).")
    if db.get("error"):
        return _bad("Google Cloud didn't answer just now.")
    return _ok("Database usage numbers are readable")


# ── scheduled jobs (the Cloudflare cron) ─────────────────────────────────────

def record_run(job: str) -> None:
    """Each cron job stamps when it ran, so the page can tell if the schedule stopped."""
    prefs.ref().set({"lastRun": {job: now_utc().isoformat()}}, merge=True)


def _jobs() -> dict:
    runs = (prefs.ref().get().to_dict() or {}).get("lastRun") or {}
    now, local = now_utc(), now_local()
    # when each job should have run in the last ~45 minutes (schedule in apps/cron/wrangler.toml)
    minute = local.hour * 60 + local.minute
    tick_due = local.weekday() < 6 and 9 * 60 + 30 + 45 <= minute <= 20 * 60
    explore_due = 30 + 45 <= minute <= 5 * 60 + 30
    out = {}
    for job, label, due in (("tick", "Sending and reply checks (every 30 min, 9:30 AM–8 PM Mon–Sat)", tick_due),
                            ("explore", "Night explorer (every 30 min, 12:30–5 AM)", explore_due),
                            ("report", "Daily report (7 PM Mon–Sat)", False)):
        last = runs.get(job)
        if not last:   # runs are recorded from this version on
            out[job] = {"label": label, "lastRun": None, "ok": None, "detail": "No run recorded yet; the next one shows here."}
            continue
        late = due and now - datetime.fromisoformat(last) > timedelta(minutes=45)
        out[job] = {"label": label, "lastRun": last, "ok": not late,
                    "detail": "Hasn't run in the last 45 minutes: check the jarvis-cron worker in Cloudflare." if late else ""}
    return out


async def check(force: bool = False) -> dict:
    global _cache
    if _cache and not force and time.monotonic() - _cache[0] < 60:
        return _cache[1]
    async with httpx.AsyncClient(timeout=10) as client:
        g, t, m = await asyncio.gather(_gmail(client), _telegram(client), _gemini(client))
    usage_perm, jobs = await asyncio.gather(asyncio.to_thread(_usage_permission), asyncio.to_thread(_jobs))
    result = {
        "services": {"gmail": g, "telegram": t, "gemini": m, "usagePermission": usage_perm,
                     **({"tomtom": _tomtom} if _tomtom else {})},
        "jobs": jobs,
        "checkedAt": now_utc().isoformat(),
    }
    _cache = (time.monotonic(), result)
    return result


async def check_tomtom() -> dict:
    """Costs one of TomTom's daily searches, so only on request."""
    global _tomtom, _cache
    from . import sources, usage
    key = get_settings().tomtom_api_key
    if not key:
        _tomtom = _bad("No TomTom key: add TOMTOM_API_KEY in Render.")
    else:
        try:
            await sources.geocode("Hyderabad")
            usage.count_map_searches(1)
            _tomtom = _ok("Key works (map searches for scans and the night explorer)")
        except httpx.HTTPStatusError as e:
            _tomtom = _bad("TomTom refused the key, or today's free searches are used up." if e.response.status_code in (401, 403, 429)
                           else f"TomTom answered with an error ({e.response.status_code}).")
        except (httpx.HTTPError, ValueError):
            _tomtom = _bad("Couldn't reach TomTom.")
    _tomtom["checkedAt"] = now_utc().isoformat()
    _cache = None
    return _tomtom
