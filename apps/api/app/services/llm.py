"""
One `complete()` call for every provider, so the rest of the code doesn't care
which LLM is behind it. Switch with LLM_PROVIDER / LLM_MODEL.
"""

import asyncio

import httpx

from ..config import get_settings

DEFAULT_MODELS = {
    "anthropic": "claude-haiku-5-5",
    "gemini": "gemini-3.5-flash-lite",   # fast, free tier
}

Message = dict  # {"role": "user" | "assistant", "content": str}


async def complete(system: str, messages: list[Message], max_tokens: int = 800) -> str:
    s = get_settings()
    provider = s.llm_provider.lower()
    model = s.llm_model or DEFAULT_MODELS.get(provider, "")

    async with httpx.AsyncClient(timeout=60) as client:
        if provider == "anthropic":
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": s.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={"model": model, "max_tokens": max_tokens, "system": system, "messages": messages},
            )
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json()["content"]).strip()

        if provider == "gemini":
            # the free tier answers 429/503 when busy; those clear up within seconds
            for attempt in range(3):
                r = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": s.gemini_api_key},
                    json={
                        "systemInstruction": {"parts": [{"text": system}]},
                        "contents": [
                            {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                            for m in messages
                        ],
                        "generationConfig": {"maxOutputTokens": max_tokens},
                    },
                )
                if r.status_code not in (429, 503) or attempt == 2:
                    break
                await asyncio.sleep(2 * (attempt + 1))
            r.raise_for_status()
            parts = r.json()["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()

    raise ValueError(f"Unknown LLM_PROVIDER: {s.llm_provider}")
