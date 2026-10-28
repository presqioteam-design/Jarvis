from ..firebase import col
from ..timeutil import now_utc


def open_tasks() -> list[dict]:
    docs = col("tasks").where("status", "in", ["todo", "in_progress"]).stream()
    return [{"id": d.id, **d.to_dict()} for d in docs]


def tasks_for(date: str) -> list[dict]:
    docs = col("tasks").where("plannedFor", "==", date).stream()
    return [{"id": d.id, **d.to_dict()} for d in docs]


def add_task(title: str, planned_for: str, remind_at: str | None = None) -> str:
    data = {
        "title": title,
        "status": "todo",
        "plannedFor": planned_for,
        "createdAt": now_utc().isoformat(),
    }
    if remind_at:
        data["remindAt"] = remind_at
        data["reminded"] = False
    _, ref = col("tasks").add(data)
    return ref.id


def carry_over(tasks: list[dict], to_date: str) -> int:
    n = 0
    for t in tasks:
        if t.get("status") != "done":
            col("tasks").document(t["id"]).update({"plannedFor": to_date, "carriedOver": True})
            n += 1
    return n


def due_reminders() -> list[dict]:
    now = now_utc().isoformat()
    docs = col("tasks").where("reminded", "==", False).stream()
    return [{"id": d.id, **d.to_dict()} for d in docs if d.to_dict().get("remindAt", "9999") <= now]


def mark_reminded(task_id: str) -> None:
    col("tasks").document(task_id).update({"reminded": True})
