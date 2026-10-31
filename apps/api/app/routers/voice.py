"""
Live voice calls with Jarvis from the dashboard (Gemini Live API).

The browser never sees the Gemini key: /voice/session hands out a short-lived,
single-use token whose setup (model, voice, Jarvis's instructions with today's
data, and the one tool) is locked on the server. When Gemini wants to act, the
browser relays the tool call to /voice/command, which runs the same commands
as Telegram.
"""

import asyncio
import time
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from google.api_core.exceptions import ResourceExhausted
from pydantic import BaseModel, Field

from ..config import get_settings
from ..deps import require_user
from ..services import chat, presqio, usage
from ..timeutil import now_local

router = APIRouter(prefix="/voice", tags=["voice"], dependencies=[Depends(require_user)])

MODEL = "gemini-3.8-live"
VOICE = "Charon"   # a calm, deep voice
WS_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContentConstrained"

INSTRUCTIONS = """You are J.A.R.V.I.S., the voice of Presqio's sales assistant, talking live with the admin (the Presqio owner).
LANGUAGE: always speak English, every single reply, with a clear neutral accent. If the admin speaks Hindi, Telugu or any
other language, understand it but answer in English. Never switch languages, even for one word or a greeting.
Address the admin as "Boss" (for example "Good morning, Boss" or "Done, Boss"), naturally and not in every sentence.
Speak like a calm, capable assistant: short, natural sentences, one to three at a time. This is a spoken conversation:
no lists, no markdown, no reading out email addresses unless asked. Say numbers naturally.

You find businesses with an email (hotels, hospitals, schools, restaurants, factories, stores, IT companies, corporate
offices, security agencies, gyms and salons, coaching centres), email them about Presqio, track replies and report. Use only the DATA below for facts and numbers;
if something isn't there, say you don't have it. When the admin asks you to DO something, call the tool
`jarvis_command` with a short command, then tell them the result in one or two sentences. Commands it understands:
  send <n> | send <n> in <area> | send follow ups | check replies | pause auto | resume auto | auto status | report
  show leads in <area> | approve all with email in <area> | scan <area> <n>km (every kind) | scan <kind> in <area> <n>km
  explore status | pause explore | resume explore | explore <city> next
For a question about something that changed during the call (like "did anyone reply?"), you may also use the tool with
the question itself. Never send more than 50 emails. If they ask you to send without a number, ask how many.
ENDING THE CALL: when the admin wants to stop talking ("cut the call", "hang up", "end the call", "bye", "that's all",
"stop the call"), say one short goodbye like "Okay Boss, talk soon." and then call the tool `end_call`. Don't ask to confirm.

PRODUCT FACTS (only these):
{facts}

DATA at the start of this call ({now}):
{data}
"""

TOOL = {
    "functionDeclarations": [{
        "name": "jarvis_command",
        "description": "Run a Jarvis command (send emails, pause/resume auto-send, reports, leads) or ask about live data.",
        "parameters": {"type": "OBJECT", "properties": {"command": {"type": "STRING", "description": "e.g. 'send 5 in Hitech City'"}},
                       "required": ["command"]},
    }, {
        "name": "end_call",
        "description": "Hang up this call, after saying a short goodbye. Use when the admin asks to cut, end or stop the call.",
    }]
}


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


# Jarvis's briefing (today's numbers) takes a dozen Firestore lookups, 2-3 s from Render. The page asks
# for it in the background when Talk to Jarvis opens (/voice/prepare), so tapping Call doesn't wait.
BRIEFING_FRESH_SECONDS = 120
QUOTA_NOTE = ("(Today's numbers are unavailable: the free database limit is used up until it resets around "
              "12:30 PM IST. Say so if asked about numbers; commands may also fail until then.)")
_briefing: tuple[float, str] | None = None
_building: asyncio.Task | None = None


async def _briefing_text() -> str:
    global _briefing, _building
    if _briefing and time.monotonic() - _briefing[0] < BRIEFING_FRESH_SECONDS:
        return _briefing[1]
    if _building is None or _building.done():   # one build at a time, shared by prepare and session
        _building = asyncio.create_task(asyncio.to_thread(chat.context_block))
    try:
        data = await asyncio.shield(_building)
    except ResourceExhausted:
        return QUOTA_NOTE
    _briefing = (time.monotonic(), data)
    return data


@router.post("/prepare")
async def prepare():
    """Build the briefing ahead of the call; called when the voice page opens."""
    await _briefing_text()
    return {"ok": True}


def _take_call() -> int | None:
    try:
        return usage.take("voiceCalls")
    except ResourceExhausted:
        return None   # the database is over its free daily quota; still let the call happen


@router.post("/session")
async def session():
    """A single-use token for one call, valid to start within 2 minutes."""
    s = get_settings()
    # count the call while the briefing is fetched (usually already prepared)
    counting = asyncio.create_task(asyncio.to_thread(_take_call))
    data = await _briefing_text()
    now = datetime.now(timezone.utc)
    setup = {
        "model": f"models/{MODEL}",
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"languageCode": "en-US", "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE}}},
        },
        "systemInstruction": {"parts": [{"text": INSTRUCTIONS.format(
            facts=presqio.facts(), now=now_local().strftime("%A %d %b, %I:%M %p"), data=data)}]},
        "tools": [TOOL],
        # end your turn after a short pause even with background noise, so Jarvis doesn't keep waiting
        "realtimeInputConfig": {"automaticActivityDetection": {
            "endOfSpeechSensitivity": "END_SENSITIVITY_HIGH", "silenceDurationMs": 700}},
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post("https://generativelanguage.googleapis.com/v1alpha/auth_tokens",
                              headers={"x-goog-api-key": s.gemini_api_key},
                              json={"uses": 1, "expireTime": _iso(now + timedelta(minutes=30)),
                                    "newSessionExpireTime": _iso(now + timedelta(minutes=2)),
                                    "bidiGenerateContentSetup": setup})
    try:
        left = await counting
    except usage.LimitReached as e:
        raise HTTPException(429, str(e))   # the unused token simply expires
    if r.status_code != 200:
        raise HTTPException(502, "Couldn't start a voice session with Gemini. Try again in a minute.")
    return {"url": f"{WS_URL}?access_token={r.json()['name']}", "maxSeconds": s.voice_minutes_per_call * 60,
            "callsLeft": left, "callsPerDay": s.voice_calls_per_day}


class CommandIn(BaseModel):
    command: str = Field(min_length=1, max_length=300)


@router.post("/command")
async def command(body: CommandIn):
    """Runs what Jarvis decided to do during the call; the reply is spoken back."""
    action = chat.command(body.command)
    if action:
        started, note = chat.run_action(action)
        return {"result": note or ("Started. I'll message the details on Telegram." if started else "Done.")}
    try:
        reply, _ = await chat.handle(body.command, channel="voice")
    except usage.LimitReached as e:
        reply = str(e)
    return {"result": reply}
