"""
Chat with Jarvis. Used by both the web dashboard and Telegram.

The model can ask for one action by ending its reply with a line like:
ACTION: {"type": "add_task", "title": "...", "remindAt": "2026-10-28T16:00:00+05:30"}
We strip that line, run the action, and save the visible reply.
"""

import json
import logging
import re

from firebase_admin import firestore

from ..firebase import col
from ..timeutil import fmt_duration, now_local, now_utc, today
from . import activity, llm, tasks

log = logging.getLogger(__name__)
ACTION_RE = re.compile(r"^ACTION:\s*(\{.*\})\s*$", re.MULTILINE)

SYSTEM = """You are Jarvis, a concise personal work assistant.
You can see the user's computer activity for today and their task list.
Answer in 1-4 short sentences unless asked for detail. Use the data given; never invent numbers.

If the user asks you to add a task or set a reminder, end your reply with exactly one line:
ACTION: {{"type": "add_task", "title": "<task>", "remindAt": "<ISO 8601 with offset, or null>"}}

Current local time: {now}
"""


def context_block() -> str:
    s = activity.summarize(today())
    apps = ", ".join(f"{a['app']} {fmt_duration(a['seconds'])}" for a in s["topApps"]) or "no data yet"
    open_t = tasks.open_tasks()
    task_lines = "\n".join(f"- [{t['status']}] {t['title']}" for t in open_t) or "- none"
    return (
        f"TODAY ({s['date']}):\n"
        f"Focus {fmt_duration(s['focusSeconds'])}, meetings {fmt_duration(s['meetingSeconds'])}, "
        f"active {fmt_duration(s['activeSeconds'])}, context switches {s['contextSwitches']}.\n"
        f"Top apps: {apps}\n\nOPEN TASKS:\n{task_lines}"
    )


def recent_history(limit: int = 10) -> list[dict]:
    docs = col("chats").order_by("createdAt", direction=firestore.Query.DESCENDING).limit(limit).stream()
    msgs = [d.to_dict() for d in docs][::-1]
    return [{"role": m["role"], "content": m["text"]} for m in msgs]


def save(role: str, text: str, channel: str) -> None:
    col("chats").add({"role": role, "text": text, "channel": channel, "createdAt": now_utc().isoformat()})


def run_action(reply: str) -> str:
    m = ACTION_RE.search(reply)
    if not m:
        return reply
    visible = ACTION_RE.sub("", reply).strip()
    try:
        action = json.loads(m.group(1))
        if action.get("type") == "add_task" and action.get("title"):
            tasks.add_task(action["title"], today(), action.get("remindAt") or None)
    except (json.JSONDecodeError, KeyError):
        log.warning("Could not parse action: %s", m.group(1))
    return visible


async def handle(text: str, channel: str) -> str:
    history = recent_history()
    save("user", text, channel)
    messages = [
        {"role": "user", "content": context_block()},
        {"role": "assistant", "content": "Got it, I have today's data."},
        *history,
        {"role": "user", "content": text},
    ]
    reply = await llm.complete(SYSTEM.format(now=now_local().strftime("%A %d %b %Y, %H:%M")), messages)
    reply = run_action(reply)
    save("assistant", reply, channel)
    return reply
