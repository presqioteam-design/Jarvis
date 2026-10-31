import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { collection, onSnapshot, orderBy, query, where, type FirestoreError } from "firebase/firestore";
import { categoryLabel, type Activity, type CitySummary, type Lead, type LeadStatus } from "@jarvis/shared";
import { db, userPath } from "../lib/firebase";
import { useUser } from "../lib/auth";
import { greeting, percent, timeAgo } from "../lib/format";
import { LoadMore, usePaged } from "../lib/paging";
import Icon, { type IconName } from "../components/Icon";

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
  const [cities, setCities] = useState<CitySummary[]>([]);
  // both panels scroll inside themselves and load the next page at the bottom
  const attentionRef = useRef<HTMLUListElement>(null);
  const feedRef = useRef<HTMLUListElement>(null);
  const hot = usePaged<Lead>(
    query(collection(db, userPath(user.uid, "leads")), where("status", "in", ["replied", "interested", "demo"])),
    `hot:${user.uid}`,
    15,
  );
  const activity = usePaged<Activity>(
    query(collection(db, userPath(user.uid, "activity")), orderBy("at", "desc")),
    `activity:${user.uid}`,
    20,
  );
  const attention = [...hot.rows].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  useEffect(() => {
    if (hot.error || activity.error) setError("Couldn't load replies or activity. Try again in a minute.");
  }, [hot.error, activity.error]);
  const feed = activity.rows;
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
      // city totals instead of every lead: thousands of leads would use up the free Firestore reads
      onSnapshot(
        collection(db, userPath(user.uid, "cities")),
        (s) => {
          setCities(s.docs.map((d) => d.data() as CitySummary));
          setLoaded(true);
        },
        onError,
      ),
    ];
    return () => unsubs.forEach((u) => u());
  }, [user.uid]);

  const total = cities.reduce((n, c) => n + c.total, 0);
  const count = (statuses: LeadStatus[]) => cities.reduce((n, c) => n + statuses.reduce((m, s) => m + (c.statuses[s] ?? 0), 0), 0);
  const counts = Object.fromEntries(STAGES.map((s) => [s.key, count(s.statuses)]));
  const contacted = counts.emailed + counts.replied + counts.interested + counts.customer;
  const responded = counts.replied + counts.interested + counts.customer;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="muted">{new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}</div>
          <h1 className="title">
            {greeting()}, {user.displayName?.split(" ")[0] ?? "there"}
          </h1>
        </div>
        <div className="head-actions">
          <Link to="/chat" className="btn">
            <Icon name="chat" size={18} />
            Ask Jarvis
          </Link>
          <Link to="/voice" className="btn talk-btn">
            <Icon name="mic" size={18} />
            Talk to Jarvis
          </Link>
        </div>
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
        <Kpi icon="leads" label="Businesses found" value={total} note={total ? `${counts.found.toLocaleString()} not contacted yet` : "Scan your city"} />
        <Kpi icon="mail" label="Contacted" value={contacted} note={`${percent(contacted, total)} of leads`} />
        <Kpi icon="reply" label="Replies" value={responded} note={`${percent(responded, contacted)} reply rate`} />
        <Kpi icon="star" label="Interested" value={counts.interested + counts.customer} note={`${counts.customer} customers`} accent />
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Pipeline</h2>
          <span className="muted small">{total.toLocaleString()} businesses</span>
        </div>
        <div className="funnel" role="img" aria-label="Leads by stage">
          {total === 0 ? (
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

      {loaded && total === 0 && !error ? (
        <GettingStarted />
      ) : (
        <div className="grid2 panels">
          <section className="card panel">
            <div className="card-head">
              <h2>Needs your attention</h2>
            </div>
            {attention.length === 0 ? (
              <p className="empty">No replies waiting. Jarvis will alert you on Telegram when someone answers.</p>
            ) : (
              <ul className="list panel-body" ref={attentionRef}>
                {attention.map((l) => (
                  <li key={l.id}>
                    <div>
                      <div className="list-title">{l.name} <span className="cat-tag">{categoryLabel(l.category)}</span></div>
                      <div className="muted small">{[l.area, l.city].filter(Boolean).join(", ") || l.address}</div>
                    </div>
                    <span className={`pill ${l.status}`}>{STATUS_LABEL[l.status]}</span>
                  </li>
                ))}
                <li className="load-row"><LoadMore root={attentionRef} more={hot.more} loading={hot.loading} onVisible={hot.loadMore} /></li>
              </ul>
            )}
          </section>

          <section className="card panel">
            <div className="card-head">
              <h2>What Jarvis did</h2>
            </div>
            {feed.length === 0 ? (
              <p className="empty">Nothing yet.</p>
            ) : (
              <ul className="list feed panel-body" ref={feedRef}>
                {feed.map((a) => (
                  <li key={a.id}>
                    <span className={`feed-icon ${a.type}`}><Icon name={ACTIVITY_ICON[a.type]} size={16} /></span>
                    <span className="feed-text">{a.text}</span>
                    <span className="muted small nowrap">{timeAgo(a.at)}</span>
                  </li>
                ))}
                <li className="load-row">
                  <LoadMore root={feedRef} more={activity.more} loading={activity.loading} onVisible={activity.loadMore}
                    done={feed.length > 20 ? "That's everything" : ""} />
                </li>
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
      <span className="kpi-value">{value.toLocaleString()}</span>
      <span className="muted small">{note}</span>
    </div>
  );
}

function GettingStarted() {
  const steps = [
    { done: true, title: "Sign in to the dashboard", text: "You're in." },
    { done: true, title: "Connect the database", text: "Firestore rules are published." },
    { done: false, title: "Create your first campaign", text: "Pick a kind of business and an area like Madhapur; Jarvis finds the ones with an email." },
    { done: false, title: "Approve leads", text: "Choose which businesses Jarvis should email." },
  ];
  return (
    <section className="card">
      <div className="card-head">
        <h2>Getting started</h2>
        <Link to="/campaigns" className="btn primary">
          <Icon name="campaign" size={18} />
          Start a campaign
        </Link>
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
