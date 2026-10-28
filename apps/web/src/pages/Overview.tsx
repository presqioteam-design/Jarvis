import { useEffect, useState } from "react";
import type { User } from "firebase/auth";
import { collection, limit, onSnapshot, orderBy, query } from "firebase/firestore";
import type { Activity, Lead, LeadStatus } from "@jarvis/shared";
import { db, userPath } from "../lib/firebase";
import { greeting, timeAgo } from "../lib/format";

const PIPELINE: { label: string; statuses: LeadStatus[] }[] = [
  { label: "Leads found", statuses: ["new", "ready", "no_contact"] },
  { label: "Emailed", statuses: ["emailed"] },
  { label: "Replied", statuses: ["replied"] },
  { label: "Interested", statuses: ["interested", "demo"] },
  { label: "Customers", statuses: ["customer"] },
];

export default function Overview({ user, onAsk }: { user: User; onAsk: () => void }) {
  const uid = user.uid;
  const [leads, setLeads] = useState<Lead[]>([]);
  const [feed, setFeed] = useState<(Activity & { id: string })[]>([]);

  useEffect(() => {
    const unsubs = [
      onSnapshot(collection(db, userPath(uid, "leads")), (s) => setLeads(s.docs.map((d) => d.data() as Lead))),
      onSnapshot(query(collection(db, userPath(uid, "activity")), orderBy("at", "desc"), limit(30)), (s) =>
        setFeed(s.docs.map((d) => ({ id: d.id, ...(d.data() as Activity) }))),
      ),
    ];
    return () => unsubs.forEach((u) => u());
  }, [uid]);

  const count = (statuses: LeadStatus[]) => leads.filter((l) => statuses.includes(l.status)).length;

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

      <section className="kpis" aria-label="Pipeline">
        {PIPELINE.map((p) => (
          <div key={p.label} className="card kpi">
            <span className="muted">{p.label}</span>
            <span className="kpi-value">{count(p.statuses)}</span>
          </div>
        ))}
      </section>

      <section className="card">
        <h2>What Jarvis did</h2>
        {feed.length === 0 ? (
          <p className="muted">Nothing yet. Start a campaign to find hotels.</p>
        ) : (
          <ul className="feed">
            {feed.map((a) => (
              <li key={a.id}>
                <span>{a.text}</span>
                <span className="muted small">{timeAgo(a.at)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
