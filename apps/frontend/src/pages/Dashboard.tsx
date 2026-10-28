import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { collection, limit, onSnapshot, orderBy, query, type FirestoreError } from "firebase/firestore";
import type { Activity, Lead, LeadStatus } from "@jarvis/shared";
import { db, userPath } from "../lib/firebase";
import { useUser } from "../lib/auth";
import { greeting, percent, timeAgo } from "../lib/format";
import Icon, { type IconName } from "../components/Icon";

type WithId<T> = T & { id: string };

const STAGES: { key: string; label: string; statuses: LeadStatus[]; color: string }[] = [
  { key: "found", label: "Found", statuses: ["new", "ready", "no_contact"], color: "var(--c-found)" },
  { key: "emailed", label: "Emailed", statuses: ["emailed"], color: "var(--c-emailed)" },
  { key: "replied", label: "Replied", statuses: ["replied"], color: "var(--c-replied)" },
  { key: "interested", label: "Interested", statuses: ["interested", "demo"], color: "var(--c-interested)" },
  { key: "customer", label: "Customers", statuses: ["customer"], color: "var(--c-customer)" },
];

const ACTIVITY_ICON: Record<Activity["type"], IconName> = {
  lead_found: "search",
  email_sent: "mail",
  reply: "reply",
  alert: "bolt",
  status_change: "check",
  error: "alert",
};

const STATUS_LABEL: Partial<Record<LeadStatus, string>> = {
  replied: "Replied",
  interested: "Interested",
  demo: "Demo booked",
};

export default function Dashboard() {
  const user = useUser()!;
  const [leads, setLeads] = useState<WithId<Lead>[]>([]);
  const [feed, setFeed] = useState<WithId<Activity>[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const onError = (e: FirestoreError) =>
      setError(
        e.code === "permission-denied"
          ? "Jarvis can't read your data yet: the Firestore security rules haven't been published."
          : `Couldn't load data (${e.code}).`,
      );
    const unsubs = [
      onSnapshot(
        collection(db, userPath(user.uid, "leads")),
        (s) => {
          setLeads(s.docs.map((d) => ({ id: d.id, ...(d.data() as Lead) })));
          setLoaded(true);
        },
        onError,
      ),
      onSnapshot(
        query(collection(db, userPath(user.uid, "activity")), orderBy("at", "desc"), limit(20)),
        (s) => setFeed(s.docs.map((d) => ({ id: d.id, ...(d.data() as Activity) }))),
        onError,
      ),
    ];
    return () => unsubs.forEach((u) => u());
  }, [user.uid]);

  const count = (statuses: LeadStatus[]) => leads.filter((l) => statuses.includes(l.status)).length;
  const counts = Object.fromEntries(STAGES.map((s) => [s.key, count(s.statuses)]));
  const contacted = counts.emailed + counts.replied + counts.interested + counts.customer;
  const responded = counts.replied + counts.interested + counts.customer;
  const attention = leads
    .filter((l) => l.status in STATUS_LABEL)
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
    .slice(0, 6);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="muted">{new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}</div>
          <h1 className="title">
            {greeting()}, {user.displayName?.split(" ")[0] ?? "there"}
          </h1>
        </div>
        <Link to="/chat" className="btn primary">
          <Icon name="chat" size={18} />
          Ask Jarvis
        </Link>
      </header>

      {error && (
        <div className="banner" role="alert">
          <Icon name="alert" />
          <div>
            <strong>{error}</strong>
            <div className="small">
              Firebase console → Firestore → <b>Rules</b> tab → paste the contents of <code>firebase/firestore.rules</code> → <b>Publish</b>.
            </div>
          </div>
        </div>
      )}

      <section className="kpis" aria-label="Pipeline totals">
        <Kpi icon="leads" label="Leads found" value={leads.length} note={leads.length ? `${counts.found} not contacted yet` : "Start a campaign"} />
        <Kpi icon="mail" label="Contacted" value={contacted} note={`${percent(contacted, leads.length)} of leads`} />
        <Kpi icon="reply" label="Replies" value={responded} note={`${percent(responded, contacted)} reply rate`} />
        <Kpi icon="star" label="Interested" value={counts.interested + counts.customer} note={`${counts.customer} customers`} accent />
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Pipeline</h2>
          <span className="muted small">{leads.length} hotels</span>
        </div>
        <div className="funnel" role="img" aria-label="Leads by stage">
          {leads.length === 0 ? (
            <div className="funnel-empty" />
          ) : (
            STAGES.filter((s) => counts[s.key] > 0).map((s) => (
              <div key={s.key} style={{ flexGrow: counts[s.key], background: s.color }} title={`${s.label}: ${counts[s.key]}`} />
            ))
          )}
        </div>
        <div className="stages">
          {STAGES.map((s) => (
            <div key={s.key} className="stage">
              <span className="dot" style={{ background: s.color }} />
              <span className="muted">{s.label}</span>
              <strong>{counts[s.key]}</strong>
            </div>
          ))}
        </div>
      </section>

      {loaded && leads.length === 0 && !error ? (
        <GettingStarted />
      ) : (
        <div className="grid2">
          <section className="card">
            <div className="card-head">
              <h2>Needs your attention</h2>
            </div>
            {attention.length === 0 ? (
              <p className="empty">No replies waiting. Jarvis will alert you on Telegram when a hotel answers.</p>
            ) : (
              <ul className="list">
                {attention.map((l) => (
                  <li key={l.id}>
                    <div>
                      <div className="list-title">{l.name}</div>
                      <div className="muted small">{l.address}</div>
                    </div>
                    <span className={`pill ${l.status}`}>{STATUS_LABEL[l.status]}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="card">
            <div className="card-head">
              <h2>What Jarvis did</h2>
            </div>
            {feed.length === 0 ? (
              <p className="empty">Nothing yet.</p>
            ) : (
              <ul className="list feed">
                {feed.map((a) => (
                  <li key={a.id}>
                    <span className={`feed-icon ${a.type}`}><Icon name={ACTIVITY_ICON[a.type]} size={16} /></span>
                    <span className="feed-text">{a.text}</span>
                    <span className="muted small nowrap">{timeAgo(a.at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function Kpi({ icon, label, value, note, accent }: { icon: IconName; label: string; value: number; note: string; accent?: boolean }) {
  return (
    <div className={`card kpi ${accent ? "kpi-accent" : ""}`}>
      <div className="kpi-top">
        <span className="muted">{label}</span>
        <span className="kpi-icon"><Icon name={icon} size={18} /></span>
      </div>
      <span className="kpi-value">{value}</span>
      <span className="muted small">{note}</span>
    </div>
  );
}

function GettingStarted() {
  const steps = [
    { done: true, title: "Sign in to the dashboard", text: "You're in." },
    { done: false, title: "Connect the backend", text: "Copy your User UID into apps/api/.env as JARVIS_UID." },
    { done: false, title: "Create your first campaign", text: "Pick an area like Madhapur and let Jarvis find hotels." },
    { done: false, title: "Send the first emails", text: "Review the leads and start outreach from Gmail." },
  ];
  return (
    <section className="card">
      <div className="card-head">
        <h2>Getting started</h2>
        <span className="muted small">1 of {steps.length} done</span>
      </div>
      <ol className="steps">
        {steps.map((s, i) => (
          <li key={s.title} className={s.done ? "done" : ""}>
            <span className="step-num">{s.done ? <Icon name="check" size={16} /> : i + 1}</span>
            <div>
              <div className="list-title">{s.title}</div>
              <div className="muted small">{s.text}</div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
