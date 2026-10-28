"""
Chat with Jarvis. Used by both the web dashboard and Telegram.
The admin asks about leads and outreach; Jarvis answers from Firestore data.
"""

from datetime import timedelta

from firebase_admin import firestore

from ..firebase import col
from ..timeutil import now_local, now_utc
from . import activity, leads, llm

SYSTEM = """You are Jarvis, the sales assistant for Presqio, an attendance and payroll product.
You find hotels, email them about Presqio, track replies and report to the admin you are talking to.
Answer in 1-4 short sentences unless asked for detail. Use only the data given; never invent numbers or hotels.

Current local time: {now}
"""


def context_block() -> str:
    counts = leads.status_counts()
    pipeline = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "no leads yet"
    hot = leads.by_status("interested", 10) + leads.by_status("replied", 10)
    hot_lines = "\n".join(f"- {l['name']} ({l['status']})" for l in hot) or "- none"
    recent = activity.since((now_utc() - timedelta(hours=24)).isoformat())[-15:]
    recent_lines = "\n".join(f"- {a['text']}" for a in recent) or "- nothing yet"
    return (
        f"PIPELINE: {pipeline}\n\n"
        f"NEEDS ATTENTION:\n{hot_lines}\n\n"
        f"LAST 24 HOURS:\n{recent_lines}"
    )


def recent_history(limit: int = 10) -> list[dict]:
    docs = col("chats").order_by("createdAt", direction=firestore.Query.DESCENDING).limit(limit).stream()
    msgs = [d.to_dict() for d in docs][::-1]
    return [{"role": m["role"], "content": m["text"]} for m in msgs]


def save(role: str, text: str, channel: str) -> None:
    col("chats").add({"role": role, "text": text, "channel": channel, "createdAt": now_utc().isoformat()})


async def handle(text: str, channel: str) -> str:
    history = recent_history()
    save("user", text, channel)
    # data goes in the latest turn so history can start with any role
    messages = [*history, {"role": "user", "content": f"{context_block()}\n\nADMIN: {text}"}]
    reply = await llm.complete(SYSTEM.format(now=now_local().strftime("%A %d %b %Y, %H:%M")), messages)
    save("assistant", reply, channel)
    return reply
