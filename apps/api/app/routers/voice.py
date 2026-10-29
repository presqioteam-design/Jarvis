"""
Live voice calls with Jarvis from the dashboard (Gemini Live API).

The browser never sees the Gemini key: /voice/session hands out a short-lived,
single-use token whose setup (model, voice, Jarvis's instructions with today's
data, and the one tool) is locked on the server. When Gemini wants to act, the
browser relays the tool call to /voice/command, which runs the same commands
as Telegram.
"""

from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
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
Speak like a calm, capable assistant: short, natural sentences, one to three at a time. This is a spoken conversation:
no lists, no markdown, no reading out email addresses unless asked. Say numbers naturally.

You find hotels, email them about Presqio, track replies and report. Use only the DATA below for facts and numbers;
if something isn't there, say you don't have it. When the admin asks you to DO something, call the tool
`jarvis_command` with a short command, then tell them the result in one or two sentences. Commands it understands:
  send <n> | send <n> in <area> | send follow ups | check replies | pause auto | resume auto | auto status | report
  show leads in <area> | approve all with email in <area> | scan <area> <n>km
For a question about something that changed during the call (like "did anyone reply?"), you may also use the tool with
the question itself. Never send more than 50 emails. If they ask you to send without a number, ask how many.

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
    }]
}


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


@router.post("/session")
async def session():
    """A single-use token for one call, valid to start within 2 minutes."""
    s = get_settings()
    try:
        left = usage.take("voiceCalls")
    except usage.LimitReached as e:
        raise HTTPException(429, str(e))
    now = datetime.now(timezone.utc)
    setup = {
        "model": f"models/{MODEL}",
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"languageCode": "en-US", "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE}}},
        },
        "systemInstruction": {"parts": [{"text": INSTRUCTIONS.format(
            facts=presqio.FACTS, now=now_local().strftime("%A %d %b, %I:%M %p"), data=chat.context_block())}]},
        "tools": [TOOL],
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post("https://generativelanguage.googleapis.com/v1alpha/auth_tokens",
                              headers={"x-goog-api-key": s.gemini_api_key},
                              json={"uses": 1, "expireTime": _iso(now + timedelta(minutes=30)),
                                    "newSessionExpireTime": _iso(now + timedelta(minutes=2)),
                                    "bidiGenerateContentSetup": setup})
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
