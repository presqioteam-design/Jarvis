"""
Scheduled jobs. Called by the Cloudflare cron worker with X-Cron-Secret.
You can also trigger them by hand with curl while developing.
"""

from fastapi import APIRouter, Depends

from ..deps import require_cron
from ..firebase import col
from ..config import get_settings
from ..timeutil import fmt_duration, now_utc, today, tomorrow, yesterday
from ..services import activity, calendar, llm, tasks, telegram

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(require_cron)])


def stats_text(s: dict) -> str:
    apps = ", ".join(f"{a['app']} {fmt_duration(a['seconds'])}" for a in s["topApps"][:5]) or "none"
    return (
        f"Focus {fmt_duration(s['focusSeconds'])}, meetings {fmt_duration(s['meetingSeconds'])}, "
        f"active {fmt_duration(s['activeSeconds'])}, {s['contextSwitches']} context switches. Top apps: {apps}."
    )


@router.post("/morning-brief")
async def morning_brief():
    y = activity.summarize(yesterday())
    planned = [t for t in tasks.open_tasks() if t.get("plannedFor", "") <= today()]
    meetings = await calendar.events_for(today())

    prompt = (
        f"Yesterday: {stats_text(y)}\n"
        f"Open tasks for today: {[t['title'] + (' (carried over)' if t.get('carriedOver') else '') for t in planned]}\n"
        f"Today's meetings: {[m['title'] + ' at ' + m['start'] for m in meetings] or 'none (calendar not connected)'}\n\n"
        "Write a morning brief in 3-4 sentences: what's on today, what carried over, "
        "and one suggestion for when to do focused work."
    )
    brief = await llm.complete("You are Jarvis, a concise personal work assistant.", [{"role": "user", "content": prompt}])
    col("summaries").document(today()).set({"date": today(), "morningBrief": brief}, merge=True)
    await telegram.send(f"☀️ Morning brief\n\n{brief}")
    return {"ok": True, "brief": brief}


@router.post("/focus-check")
async def focus_check():
    # keep today's dashboard numbers fresh
    activity.save_summary(activity.summarize(today()))

    # reminders that are due
    for t in tasks.due_reminders():
        await telegram.send(f"⏰ Reminder: {t['title']}")
        tasks.mark_reminded(t["id"])

    switches, apps = activity.recent_switches(today(), minutes=30)
    nudged = False
    if switches >= get_settings().focus_switch_threshold:
        text = (
            f"You've switched apps {switches} times in the last 30 minutes "
            f"({', '.join(apps)}). Want to pick one thing and mute the rest for a while?"
        )
        col("nudges").add({"text": text, "kind": "focus", "createdAt": now_utc().isoformat(), "dismissed": False})
        await telegram.send(f"🎯 {text}")
        nudged = True
    return {"ok": True, "switches": switches, "nudged": nudged}


@router.post("/daily-review")
async def daily_review():
    s = activity.summarize(today())
    todays = tasks.tasks_for(today())
    done = [t["title"] for t in todays if t.get("status") == "done"]
    not_done = [t["title"] for t in todays if t.get("status") != "done"]

    prompt = (
        f"Today: {stats_text(s)}\nDone: {done}\nNot done: {not_done}\n\n"
        "Write an end-of-day review in 4-5 sentences: where the time went, what got done, "
        "what slipped and why it might have, and one concrete tip for tomorrow."
    )
    review = await llm.complete("You are Jarvis, a concise personal work assistant.", [{"role": "user", "content": prompt}])
    activity.save_summary(s, eveningReview=review)
    moved = tasks.carry_over(todays, tomorrow())
    await telegram.send(f"🌙 Daily review\n\n{review}\n\n{moved} task(s) moved to tomorrow.")
    return {"ok": True, "review": review, "carriedOver": moved}
