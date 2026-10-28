import { useEffect, useState, type FormEvent } from "react";
import type { User } from "firebase/auth";
import {
  addDoc,
  collection,
  doc,
  onSnapshot,
  query,
  updateDoc,
  where,
} from "firebase/firestore";
import type { DailySummary, Nudge, Task } from "@jarvis/shared";
import { db, userPath } from "../lib/firebase";
import { CATEGORY_COLORS, CATEGORY_LABELS, duration, greeting, localDate } from "../lib/format";

type WithId<T> = T & { id: string };

export default function Today({ user, onAsk }: { user: User; onAsk: () => void }) {
  const uid = user.uid;
  const today = localDate();
  const [summary, setSummary] = useState<DailySummary | null>(null);
  const [tasks, setTasks] = useState<WithId<Task>[]>([]);
  const [nudge, setNudge] = useState<WithId<Nudge> | null>(null);
  const [newTask, setNewTask] = useState("");

  useEffect(() => {
    const unsubs = [
      onSnapshot(doc(db, userPath(uid, "summaries", today)), (s) =>
        setSummary(s.exists() ? (s.data() as DailySummary) : null),
      ),
      onSnapshot(query(collection(db, userPath(uid, "tasks")), where("plannedFor", "==", today)), (s) =>
        setTasks(s.docs.map((d) => ({ id: d.id, ...(d.data() as Task) }))),
      ),
      onSnapshot(query(collection(db, userPath(uid, "nudges")), where("dismissed", "==", false)), (s) => {
        const all = s.docs.map((d) => ({ id: d.id, ...(d.data() as Nudge) }));
        all.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
        setNudge(all[0] ?? null);
      }),
    ];
    return () => unsubs.forEach((u) => u());
  }, [uid, today]);

  async function addTask(e: FormEvent) {
    e.preventDefault();
    const title = newTask.trim();
    if (!title) return;
    setNewTask("");
    await addDoc(collection(db, userPath(uid, "tasks")), {
      title,
      status: "todo",
      plannedFor: today,
      createdAt: new Date().toISOString(),
    } satisfies Task);
  }

  const toggle = (t: WithId<Task>) =>
    updateDoc(doc(db, userPath(uid, "tasks", t.id)), { status: t.status === "done" ? "todo" : "done" });

  const dismiss = (n: WithId<Nudge>) => updateDoc(doc(db, userPath(uid, "nudges", n.id)), { dismissed: true });

  const done = tasks.filter((t) => t.status === "done").length;
  const timelineTotal = summary?.timeline.reduce((a, b) => a + b.seconds, 0) || 1;
  const topSeconds = summary?.topApps[0]?.seconds || 1;

  return (
    <div className="stack">
      <header className="row between wrap">
        <div>
          <div className="muted">{new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}</div>
          <h1 className="title">
            {greeting()}, {user.displayName?.split(" ")[0] ?? "there"}
          </h1>
        </div>
        <button className="btn primary" onClick={onAsk}>
          Ask Jarvis
        </button>
      </header>

      <section className="card">
        <div className="eyebrow">MORNING BRIEF</div>
        <p className="lead">{summary?.morningBrief ?? "No brief yet. It arrives at 8:00 AM on weekdays."}</p>
      </section>

      <section className="kpis" aria-label="Today at a glance">
        <Kpi label="Focus time" value={duration(summary?.focusSeconds)} />
        <Kpi label="Meetings" value={duration(summary?.meetingSeconds)} />
        <Kpi label="Context switches" value={String(summary?.contextSwitches ?? 0)} />
        <Kpi label="Tasks done" value={`${done} / ${tasks.length}`} />
      </section>

      <section className="card">
        <div className="row between wrap">
          <h2>Your day so far</h2>
          <span className="muted small">
            {summary ? `Updated ${new Date(summary.updatedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : "No activity yet"}
          </span>
        </div>
        <div className="timeline">
          {summary?.timeline.map((b, i) => (
            <div
              key={i}
              title={`${CATEGORY_LABELS[b.category]} · ${duration(b.seconds)}`}
              style={{ flexGrow: b.seconds / timelineTotal, background: CATEGORY_COLORS[b.category] }}
            />
          ))}
        </div>
        <div className="legend">
          {Object.entries(CATEGORY_LABELS).map(([k, label]) => (
            <span key={k}>
              <i style={{ background: CATEGORY_COLORS[k] }} />
              {label}
            </span>
          ))}
        </div>
      </section>

      <div className="grid3">
        <section className="card">
          <h2>Where your time went</h2>
          {summary?.topApps.map((a) => (
            <div key={a.app} className="bar">
              <div className="row between">
                <span>{a.app}</span>
                <span className="mono muted">{duration(a.seconds)}</span>
              </div>
              <div className="track">
                <div style={{ width: `${(a.seconds / topSeconds) * 100}%` }} />
              </div>
            </div>
          ))}
        </section>

        <section className="card">
          <h2>Plan vs. actual</h2>
          <ul className="tasks">
            {tasks.map((t) => (
              <li key={t.id}>
                <label>
                  <input type="checkbox" checked={t.status === "done"} onChange={() => toggle(t)} />
                  <span className={t.status === "done" ? "struck" : ""}>{t.title}</span>
                </label>
                {t.carriedOver && <span className="pill">Carried over</span>}
              </li>
            ))}
          </ul>
          <form onSubmit={addTask} className="row">
            <label htmlFor="new-task" className="sr-only">New task</label>
            <input id="new-task" className="input" placeholder="Add a task for today" value={newTask} onChange={(e) => setNewTask(e.target.value)} />
            <button className="btn" type="submit">Add</button>
          </form>
        </section>

        {nudge && (
          <section className="card nudge">
            <div className="eyebrow">JARVIS NOTICED</div>
            <p>{nudge.text}</p>
            <button className="btn" onClick={() => dismiss(nudge)}>Dismiss</button>
          </section>
        )}
      </div>
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="card kpi">
      <span className="muted">{label}</span>
      <span className="kpi-value">{value}</span>
    </div>
  );
}
