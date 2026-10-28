import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { collection, doc, onSnapshot, updateDoc, writeBatch } from "firebase/firestore";
import type { Campaign, Lead, LeadStatus } from "@jarvis/shared";
import { db, userPath } from "../lib/firebase";
import { blockLead } from "../lib/api";
import { useUser } from "../lib/auth";
import { hostname } from "../lib/format";
import Icon from "../components/Icon";

type Row = Lead & { id: string };

const TABS: { key: string; label: string; statuses?: LeadStatus[] }[] = [
  { key: "review", label: "To review", statuses: ["new"] },
  { key: "ready", label: "Approved", statuses: ["ready"] },
  { key: "contacted", label: "Contacted", statuses: ["emailed", "replied", "interested", "demo", "customer"] },
  { key: "none", label: "No contact", statuses: ["no_contact"] },
  { key: "blocked", label: "Blocked", statuses: ["unsubscribed", "not_interested", "bounced"] },
  { key: "all", label: "All" },
];

const STATUS_TEXT: Record<LeadStatus, string> = {
  new: "To review", ready: "Approved", no_contact: "No contact", emailed: "Emailed", replied: "Replied",
  interested: "Interested", demo: "Demo booked", customer: "Customer", not_interested: "Not interested",
  unsubscribed: "Blocked", bounced: "Bounced",
};

export default function Leads() {
  const user = useUser()!;
  const [params, setParams] = useSearchParams();
  const [leads, setLeads] = useState<Row[]>([]);
  const [campaigns, setCampaigns] = useState<(Campaign & { id: string })[]>([]);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const tab = params.get("tab") ?? "review";
  const campaign = params.get("campaign") ?? "";

  useEffect(() => {
    const onError = () => setError("Couldn't load leads. Check that the Firestore rules are published.");
    const unsubs = [
      onSnapshot(collection(db, userPath(user.uid, "leads")), (s) => setLeads(s.docs.map((d) => ({ id: d.id, ...(d.data() as Lead) }))), onError),
      onSnapshot(collection(db, userPath(user.uid, "campaigns")), (s) => setCampaigns(s.docs.map((d) => ({ id: d.id, ...(d.data() as Campaign) }))), onError),
    ];
    return () => unsubs.forEach((u) => u());
  }, [user.uid]);

  const inCampaign = useMemo(() => leads.filter((l) => !campaign || l.campaignId === campaign), [leads, campaign]);
  const tabCount = (statuses?: LeadStatus[]) => (statuses ? inCampaign.filter((l) => statuses.includes(l.status)).length : inCampaign.length);

  const rows = useMemo(() => {
    const statuses = TABS.find((t) => t.key === tab)?.statuses;
    const q = search.trim().toLowerCase();
    return inCampaign
      .filter((l) => !statuses || statuses.includes(l.status))
      .filter((l) => !q || `${l.name} ${l.address} ${l.emails.join(" ")} ${l.phone ?? ""}`.toLowerCase().includes(q))
      // best leads first: email, then phone, then name
      .sort((a, b) => Number(!!b.emails.length) - Number(!!a.emails.length) || Number(!!b.phone) - Number(!!a.phone) || a.name.localeCompare(b.name));
  }, [inCampaign, tab, search]);

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  const setStatus = (l: Row, status: LeadStatus) =>
    updateDoc(doc(db, userPath(user.uid, "leads", l.id)), { status, updatedAt: new Date().toISOString() });

  async function approveAllWithEmail() {
    const targets = rows.filter((l) => l.status === "new" && l.emails.length);
    const now = new Date().toISOString();
    for (let i = 0; i < targets.length; i += 400) {
      const batch = writeBatch(db);
      targets.slice(i, i + 400).forEach((l) => batch.update(doc(db, userPath(user.uid, "leads", l.id)), { status: "ready", updatedAt: now }));
      await batch.commit();
    }
  }

  async function block(l: Row) {
    if (!confirm(`Never contact ${l.name}? Its email and phone go on the do-not-contact list.`)) return;
    try {
      await blockLead(l.id);
    } catch {
      setError("Couldn't block this lead. Make sure the API is running (yarn api:dev).");
    }
  }

  const reviewWithEmail = rows.filter((l) => l.status === "new" && l.emails.length).length;

  return (
    <div className="page wide">
      <header className="page-head">
        <div>
          <h1 className="title">Leads</h1>
          <p className="muted sub">Approve the hotels Jarvis should email. Blocked hotels are never contacted.</p>
        </div>
        {tab === "review" && reviewWithEmail > 0 && (
          <button className="btn primary" onClick={approveAllWithEmail}>
            <Icon name="check" size={18} />
            Approve {reviewWithEmail} with email
          </button>
        )}
      </header>

      {error && <p className="error" role="alert">{error}</p>}

      <div className="toolbar">
        <div className="tabs" role="tablist">
          {TABS.map((t) => (
            <button key={t.key} role="tab" aria-selected={tab === t.key} className={`tab ${tab === t.key ? "active" : ""}`} onClick={() => setParam("tab", t.key === "review" ? "" : t.key)}>
              {t.label} <span className="count">{tabCount(t.statuses)}</span>
            </button>
          ))}
        </div>
        <div className="filters">
          <label className="sr-only" htmlFor="lead-search">Search leads</label>
          <input id="lead-search" className="input" placeholder="Search name, email, phone…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <label className="sr-only" htmlFor="lead-campaign">Campaign</label>
          <select id="lead-campaign" className="input" value={campaign} onChange={(e) => setParam("campaign", e.target.value)}>
            <option value="">All areas</option>
            {campaigns.map((c) => (
              <option key={c.id} value={c.id}>{c.area.label}</option>
            ))}
          </select>
        </div>
      </div>

      <section className="card table-card">
        {rows.length === 0 ? (
          <p className="empty">{leads.length === 0 ? "No leads yet. Start a campaign to find hotels." : "Nothing here."}</p>
        ) : (
          <ul className="leads">
            {rows.map((l) => (
              <li key={l.id} className="lead">
                <div className="lead-main">
                  <div className="list-title">{l.name}</div>
                  <div className="muted small ellipsis">{l.address || "No address"}</div>
                </div>
                <div className="lead-contact small">
                  {l.emails[0] ? <a href={`mailto:${l.emails[0]}`} className="contact"><Icon name="mail" size={14} />{l.emails[0]}</a> : <span className="muted">No email</span>}
                  {l.phone ? <a href={`tel:${l.phone}`} className="contact"><Icon name="phone" size={14} />{l.phone}</a> : <span className="muted">No phone</span>}
                  {l.website && <a href={l.website} target="_blank" rel="noreferrer" className="contact muted">{hostname(l.website)}</a>}
                </div>
                <span className={`pill ${l.status}`}>{STATUS_TEXT[l.status]}</span>
                <div className="lead-actions">
                  {l.status === "new" && (
                    <button className="btn small-btn" onClick={() => setStatus(l, "ready")}>Approve</button>
                  )}
                  {l.status === "ready" && (
                    <button className="btn small-btn" onClick={() => setStatus(l, "new")}>Undo</button>
                  )}
                  {l.status !== "unsubscribed" && (
                    <button className="icon-btn" onClick={() => block(l)} title="Never contact" aria-label={`Block ${l.name}`}>
                      <Icon name="ban" size={16} />
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
