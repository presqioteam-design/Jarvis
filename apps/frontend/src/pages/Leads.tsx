import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { collection, doc, limit, onSnapshot, query, where, type QueryConstraint } from "firebase/firestore";
import type { AreaSummary, Campaign, CitySummary, Lead, LeadStatus } from "@jarvis/shared";
import { db, userPath } from "../lib/firebase";
import { blockLead, setLeadStatus } from "../lib/api";
import { useUser } from "../lib/auth";
import { areaKey, hostname, slug } from "../lib/format";
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

const PAGE = 300;   // without an area picked, show at most this many leads per tab

export default function Leads() {
  const user = useUser()!;
  const [params, setParams] = useSearchParams();
  const [cities, setCities] = useState<string[]>([]);
  const [areas, setAreas] = useState<AreaSummary[]>([]);
  const [leads, setLeads] = useState<Row[]>([]);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  const tab = params.get("tab") ?? "review";
  const city = params.get("city") ?? cities[0] ?? "";
  const area = params.get("area") ?? "";
  const statuses = TABS.find((t) => t.key === tab)?.statuses;

  const onError = () => setError("Couldn't load leads. Check that the Firestore rules are published.");

  // cities come from finished scans
  useEffect(
    () =>
      onSnapshot(collection(db, userPath(user.uid, "campaigns")), (s) => {
        const names = s.docs.map((d) => (d.data() as Campaign).city).filter((c): c is string => !!c);
        setCities([...new Set(names)].sort());
      }, onError),
    [user.uid],
  );

  useEffect(() => {
    if (!city) return;
    return onSnapshot(doc(db, userPath(user.uid, "cities", slug(city))), (s) =>
      setAreas(Object.values((s.data() as CitySummary | undefined)?.areas ?? {}).sort((a, b) => a.area.localeCompare(b.area))), onError);
  }, [user.uid, city]);

  // one area: every lead in it. No area: one status tab, capped.
  useEffect(() => {
    if (!area && !statuses) {
      setLeads([]);
      return;
    }
    const constraints: QueryConstraint[] = area
      ? [where("areaKey", "==", areaKey(city, area))]
      : [where("status", "in", statuses!), limit(PAGE)];
    return onSnapshot(query(collection(db, userPath(user.uid, "leads")), ...constraints),
      (s) => setLeads(s.docs.map((d) => ({ id: d.id, ...(d.data() as Lead) }))), onError);
    // statuses is derived from tab
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user.uid, city, area, area ? "" : tab]);

  // tab counts come from the area totals, so they cover every lead, not just the loaded ones
  const counted = area ? areas.filter((a) => a.area === area) : areas;
  const tabCount = (st?: LeadStatus[]) =>
    counted.reduce((n, a) => n + (st ? st.reduce((m, s) => m + (a.statuses[s] ?? 0), 0) : a.total), 0);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return leads
      .filter((l) => !statuses || statuses.includes(l.status))
      .filter((l) => area || !city || !l.city || l.city === city)
      .filter((l) => !q || `${l.name} ${l.address} ${l.area ?? ""} ${l.emails.join(" ")} ${l.phone ?? ""}`.toLowerCase().includes(q))
      .sort((a, b) => Number(!!b.emails.length) - Number(!!a.emails.length) || Number(!!b.phone) - Number(!!a.phone) || a.name.localeCompare(b.name));
  }, [leads, statuses, search, area, city]);

  const setParam = (updates: Record<string, string>) => {
    const next = new URLSearchParams(params);
    Object.entries(updates).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    setParams(next, { replace: true });
  };

  async function changeStatus(ids: string[], status: "new" | "ready") {
    setWorking(true);
    setError("");
    try {
      for (let i = 0; i < ids.length; i += 500) await setLeadStatus(ids.slice(i, i + 500), status);
    } catch {
      setError("Couldn't update. Make sure the API is running (yarn api:dev).");
    } finally {
      setWorking(false);
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

  const approvable = rows.filter((l) => l.status === "new" && l.emails.length).map((l) => l.id);

  return (
    <div className="page wide">
      <header className="page-head">
        <div>
          <h1 className="title">Leads</h1>
          <p className="muted sub">Approved hotels are emailed first when you tell Jarvis to send. Blocked hotels are never contacted.</p>
        </div>
        {tab === "review" && approvable.length > 0 && (
          <button className="btn primary" onClick={() => changeStatus(approvable, "ready")} disabled={working}>
            <Icon name="check" size={18} />
            Approve {approvable.length} with email{area ? ` in ${area}` : ""}
          </button>
        )}
      </header>

      {error && <p className="error" role="alert">{error}</p>}

      <div className="filters">
        <label className="sr-only" htmlFor="lead-city">City</label>
        <select id="lead-city" className="input" value={city} onChange={(e) => setParam({ city: e.target.value, area: "" })}>
          {cities.length === 0 && <option value="">No scans yet</option>}
          {cities.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <label className="sr-only" htmlFor="lead-area">Area</label>
        <select id="lead-area" className="input" value={area} onChange={(e) => setParam({ area: e.target.value })}>
          <option value="">All areas</option>
          {areas.map((a) => (
            <option key={a.area} value={a.area}>{a.area} ({a.total})</option>
          ))}
        </select>
        <label className="sr-only" htmlFor="lead-search">Search leads</label>
        <input id="lead-search" className="input" placeholder="Search name, email, phone…" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} className={`tab ${tab === t.key ? "active" : ""}`} onClick={() => setParam({ tab: t.key === "review" ? "" : t.key })}>
            {t.label} <span className="count">{tabCount(t.statuses).toLocaleString()}</span>
          </button>
        ))}
      </div>

      <section className="card table-card">
        {!area && !statuses ? (
          <p className="empty">Pick an area to see all of its hotels.</p>
        ) : rows.length === 0 ? (
          <p className="empty">Nothing here.</p>
        ) : (
          <>
            {!area && leads.length >= PAGE && (
              <p className="muted small list-note">Showing the first {PAGE}. Pick an area to see everything in it.</p>
            )}
            <ul className="leads">
              {rows.map((l) => (
                <li key={l.id} className="lead">
                  <div className="lead-main">
                    <div className="list-title">{l.name}</div>
                    <div className="muted small ellipsis">{[l.area, l.address].filter(Boolean).join(" · ") || "No address"}</div>
                  </div>
                  <div className="lead-contact small">
                    {l.emails[0] ? <a href={`mailto:${l.emails[0]}`} className="contact"><Icon name="mail" size={14} />{l.emails[0]}</a> : <span className="muted">No email</span>}
                    {l.phone ? <a href={`tel:${l.phone}`} className="contact"><Icon name="phone" size={14} />{l.phone}</a> : <span className="muted">No phone</span>}
                    {l.website && <a href={l.website} target="_blank" rel="noreferrer" className="contact muted">{hostname(l.website)}</a>}
                  </div>
                  <span className={`pill ${l.status}`}>{STATUS_TEXT[l.status]}</span>
                  <div className="lead-actions">
                    {l.status === "new" && <button className="btn small-btn" onClick={() => changeStatus([l.id], "ready")} disabled={working}>Approve</button>}
                    {l.status === "ready" && <button className="btn small-btn" onClick={() => changeStatus([l.id], "new")} disabled={working}>Undo</button>}
                    {!["unsubscribed", "bounced"].includes(l.status) && (
                      <button className="icon-btn" onClick={() => block(l)} title="Never contact" aria-label={`Block ${l.name}`}>
                        <Icon name="ban" size={16} />
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </div>
  );
}
