"""
Voice for Telegram, using Gemini on the free API key.
speak(): text → audio for a voice note. hear(): a voice note → text.
Telegram voice notes must be OGG/Opus; ffmpeg converts (it's in the Docker
image). Without ffmpeg the audio goes out as a WAV file instead.
"""

import asyncio
import base64
import shutil
import subprocess

import httpx

from ..config import get_settings

API = "https://generativelanguage.googleapis.com/v1beta/models"
TTS_MODEL = "gemini-3.8-flash-tts"
VOICE = "Kore"


async def speak(text: str) -> tuple[bytes, str]:
    """-> (audio, "ogg" or "wav")."""
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{API}/{TTS_MODEL}:generateContent", headers={"x-goog-api-key": get_settings().gemini_api_key}, json={
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE}}}},
        })
        r.raise_for_status()
    wav = base64.b64decode(r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
    if not shutil.which("ffmpeg"):
        return wav, "wav"
    return await asyncio.to_thread(_to_ogg, wav), "ogg"


def _to_ogg(wav: bytes) -> bytes:
    done = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-c:a", "libopus", "-b:a", "32k", "-f", "ogg", "pipe:1"],
        input=wav, capture_output=True, check=True,
    )
    return done.stdout


async def hear(audio: bytes, mime: str = "audio/ogg") -> str:
    """Transcribe a voice note (English, Hindi or Telugu speech; answer in the language spoken)."""
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{API}/gemini-3.5-flash-lite:generateContent", headers={"x-goog-api-key": get_settings().gemini_api_key}, json={
            "contents": [{"parts": [
                {"inlineData": {"mimeType": mime, "data": base64.b64encode(audio).decode()}},
                {"text": "Transcribe this voice message exactly. Reply with only the words spoken."},
            ]}],
        })
        r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
