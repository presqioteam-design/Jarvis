import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  collection, doc, documentId, getDocs, limit, onSnapshot, query, startAfter, where, type QueryDocumentSnapshot,
} from "firebase/firestore";
import type { AreaSummary, Campaign, CitySummary, Lead, LeadStatus } from "@jarvis/shared";
import { db, userPath } from "../lib/firebase";
import { approveAllWithEmail, blockLead, setLeadStatus } from "../lib/api";
import { useUser } from "../lib/auth";
import { areaKey, hostname, slug } from "../lib/format";
import Icon from "../components/Icon";

type Row = Lead & { id: string };

const ALL: LeadStatus[] = ["new", "ready", "emailed", "replied", "interested", "demo", "customer", "no_contact", "not_interested", "unsubscribed", "bounced"];
const TABS: { key: string; label: string; statuses: LeadStatus[] }[] = [
  { key: "review", label: "To review", statuses: ["new"] },
  { key: "ready", label: "Approved", statuses: ["ready"] },
  { key: "contacted", label: "Contacted", statuses: ["emailed", "replied", "interested", "demo", "customer"] },
  { key: "none", label: "No contact", statuses: ["no_contact"] },
  { key: "blocked", label: "Blocked", statuses: ["unsubscribed", "not_interested", "bounced"] },
  { key: "all", label: "All", statuses: ALL },
];

const STATUS_TEXT: Record<LeadStatus, string> = {
  new: "To review", ready: "Approved", no_contact: "No contact", emailed: "Emailed", replied: "Replied",
  interested: "Interested", demo: "Demo booked", customer: "Customer", not_interested: "Not interested",
  unsubscribed: "Blocked", bounced: "Bounced",
};

const PAGE_SIZE = 20;

/**
 * Pages are fetched with equality filters only (status, hasEmail, area), one
 * "phase" at a time: every status of the tab, hotels with email before those
 * without. Equality-only queries need no composite index in Firestore.
 */
type Phase = { status: LeadStatus; hasEmail: boolean };

/** One hotel in the city's search list (built by the API): id, name, email, phone, area. */
type Entry = { i: string; n: string; e: string; p: string; a: string };

/** Matches any part of the name, email or area; for numbers, any part of the phone (with or without +91). */
function matches(e: Entry, words: string[], digits: string): boolean {
  if (digits.length >= 3 && words.every((w) => /^[+\d\s-]+$/.test(w))) {
    return e.p.replace(/\D/g, "").includes(digits.replace(/^(91|0)(?=\d{10}$)/, ""));
  }
  const hay = `${e.n} ${e.e} ${e.a}`.toLowerCase();
  return words.every((w) => hay.includes(w));
}
type Cursor = { phase: number; last: QueryDocumentSnapshot | null; done: boolean };

export default function Leads() {
  const user = useUser()!;
  const [params, setParams] = useSearchParams();
  const [cities, setCities] = useState<string[]>([]);
  const [summary, setSummary] = useState<CitySummary | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [typed, setTyped] = useState("");                 // the search text after a short pause
  const [index, setIndex] = useState<Entry[] | null>(null);
  const [indexLoading, setIndexLoading] = useState(false);
  const [found, setFound] = useState<Record<string, Row>>({});   // full leads fetched for search results
  const [visible, setVisible] = useState(PAGE_SIZE);
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  const cursor = useRef<Cursor>({ phase: 0, last: null, done: false });
  const generation = useRef(0);   // ignores pages that arrive after the filters changed
  const listRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);

  const tab = TABS.find((t) => t.key === (params.get("tab") ?? "review")) ?? TABS[0];
  const city = params.get("city") ?? cities[0] ?? "";
  const area = params.get("area") ?? "";
  const areas: AreaSummary[] = useMemo(
    () => Object.values(summary?.areas ?? {}).sort((a, b) => a.area.localeCompare(b.area)),
    [summary],
  );
  const phases: Phase[] = useMemo(() => [true, false].flatMap((hasEmail) => tab.statuses.map((status) => ({ status, hasEmail }))), [tab]);

  const onError = useCallback((e: { code?: string }) => {
    setError(e.code === "resource-exhausted"
      ? "Firestore's free daily reads are used up. They reset at 12:30 PM IST."
      : e.code === "failed-precondition"
        ? "This filter needs a Firestore index. Tell Jarvis's developer which tab and area you picked."
        : "Couldn't load leads. Check that the Firestore rules are published.");
  }, []);

  useEffect(
    () => onSnapshot(collection(db, userPath(user.uid, "campaigns")), (s) => {
      const names = s.docs.map((d) => (d.data() as Campaign).city).filter((c): c is string => !!c);
      setCities([...new Set(names)].sort());
    }, onError),
    [user.uid, onError],
  );

  useEffect(() => {
    if (!city) return;
    return onSnapshot(doc(db, userPath(user.uid, "cities", slug(city))), (s) => setSummary(s.exists() ? (s.data() as CitySummary) : null), onError);
  }, [user.uid, city, onError]);

  // ── search: load the city's list once, then filter in the browser ─────────
  useEffect(() => {
    const t = setTimeout(() => setTyped(search.trim().toLowerCase()), 150);
    return () => clearTimeout(t);
  }, [search]);

  const loadIndex = useCallback(async () => {
    if (index || indexLoading || !city) return;
    setIndexLoading(true);
    try {
      const snap = await getDocs(query(collection(db, userPath(user.uid, "search")), where("city", "==", city)));
      setIndex(snap.docs.flatMap((d) => (d.data().entries as Entry[]) ?? []));
    } catch (e) {
      onError(e as { code?: string });
    } finally {
      setIndexLoading(false);
    }
  }, [index, indexLoading, city, user.uid, onError]);

  useEffect(() => setIndex(null), [city]);
  useEffect(() => {
    if (search) loadIndex();
  }, [search, loadIndex]);

  const hits = useMemo(() => {
    if (!typed || !index) return [];
    const words = typed.split(/\s+/).filter(Boolean);
    const digits = typed.replace(/\D/g, "");
    return index.filter((e) => (!area || e.a === area) && matches(e, words, digits));
  }, [typed, index, area]);

  useEffect(() => {
    setVisible(PAGE_SIZE);
    listRef.current?.scrollTo({ top: 0 });
  }, [typed, area]);

  // fetch full details only for the results on screen (30 ids per query is Firestore's limit for "in")
  useEffect(() => {
    const want = hits.slice(0, visible).map((h) => h.i).filter((id) => !found[id]);
    if (!want.length) return;
    let cancelled = false;
    (async () => {
      const got: Record<string, Row> = {};
      for (let i = 0; i < want.length; i += 30) {
        const snap = await getDocs(query(collection(db, userPath(user.uid, "leads")), where(documentId(), "in", want.slice(i, i + 30))));
        snap.docs.forEach((d) => (got[d.id] = { id: d.id, ...(d.data() as Lead) }));
      }
      if (!cancelled) setFound((f) => ({ ...f, ...got }));
    })().catch((e) => onError(e));
    return () => {
      cancelled = true;
    };
    // found is read, not watched: watching it would refetch after every page
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hits, visible, user.uid, onError]);

  const searching = !!search.trim();

  const loadMore = useCallback(async () => {
    const c = cursor.current;
    if (loading || c.done || !city) return;
    const gen = generation.current;
    setLoading(true);
    try {
      const page: Row[] = [];
      while (page.length < PAGE_SIZE && c.phase < phases.length) {
        const p = phases[c.phase];
        const wanted = PAGE_SIZE - page.length;
        const snap = await getDocs(query(
          collection(db, userPath(user.uid, "leads")),
          where("city", "==", city),
          where("status", "==", p.status),
          where("hasEmail", "==", p.hasEmail),
          ...(area ? [where("areaKey", "==", areaKey(city, area))] : []),
          ...(c.last ? [startAfter(c.last)] : []),
          limit(wanted),
        ));
        if (gen !== generation.current) return;
        page.push(...snap.docs.map((d) => ({ id: d.id, ...(d.data() as Lead) })));
        if (snap.docs.length < wanted) {
          c.phase += 1;   // this phase is used up; continue with the next
          c.last = null;
        } else {
          c.last = snap.docs[snap.docs.length - 1];
        }
      }
      c.done = c.phase >= phases.length;
      setRows((r) => [...r, ...page]);
    } catch (e) {
      onError(e as { code?: string });
      c.done = true;
    } finally {
      if (gen === generation.current) setLoading(false);
    }
  }, [loading, city, area, phases, user.uid, onError]);

  // new filters: start again from the first page
  useEffect(() => {
    generation.current += 1;
    cursor.current = { phase: 0, last: null, done: false };
    setRows([]);
    setLoading(false);
    setError("");
    listRef.current?.scrollTo({ top: 0 });
  }, [city, area, tab.key]);

  // fetch the next page whenever the bottom of the list scrolls into view
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const next = () => (searching ? setVisible((v) => (v < hits.length ? v + PAGE_SIZE : v)) : loadMore());
    const io = new IntersectionObserver((entries) => entries[0].isIntersecting && next(), { root: listRef.current, rootMargin: "200px" });
    io.observe(el);
    return () => io.disconnect();
  }, [loadMore, rows.length, searching, hits.length, visible]);

  const shown = useMemo(
    () => (searching ? hits.slice(0, visible).map((h) => found[h.i]).filter((l): l is Row => !!l) : rows),
    [searching, hits, visible, found, rows],
  );
  const searchPending = searching && (indexLoading || !index || typed !== search.trim().toLowerCase() || shown.length < Math.min(visible, hits.length));

  // counts come from the city summary, so they cover every lead, not just loaded ones
  const counted = area ? areas.filter((a) => a.area === area) : areas;
  const tabCount = (st: LeadStatus[]) => counted.reduce((n, a) => n + st.reduce((m, s) => m + (a.statuses[s] ?? 0), 0), 0);
  const reviewWithEmail = rows.filter((l) => l.status === "new" && l.emails.length).length;

  const setParam = (updates: Record<string, string>) => {
    const next = new URLSearchParams(params);
    Object.entries(updates).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    setParams(next, { replace: true });
  };

  /** Update loaded rows in place; drop the ones that no longer belong in this tab. */
  const applyLocal = (ids: string[], status: LeadStatus) => {
    setRows((r) => r.map((l) => (ids.includes(l.id) ? { ...l, status } : l)).filter((l) => tab.statuses.includes(l.status)));
    setFound((f) => Object.fromEntries(Object.entries(f).map(([id, l]) => [id, ids.includes(id) ? { ...l, status } : l])));
  };

  async function changeStatus(ids: string[], status: "new" | "ready") {
    setWorking(true);
    setError("");
    try {
      await setLeadStatus(ids, status);
      applyLocal(ids, status);
    } catch {
      setError("Couldn't update. Make sure the API is running (yarn api:dev).");
    } finally {
      setWorking(false);
    }
  }

  async function approveAll() {
    const where = area ? ` in ${area}` : ` in ${city}`;
    if (!confirm(`Approve every hotel with an email${where} that's waiting for review?`)) return;
    setWorking(true);
    setError("");
    try {
      const { approved } = await approveAllWithEmail(city, area || null);
      setRows((r) => r.filter((l) => !(l.status === "new" && l.emails.length)));
      alert(`Approved ${approved} hotels${where}.`);
    } catch {
      setError("Couldn't approve. Make sure the API is running (yarn api:dev).");
    } finally {
      setWorking(false);
    }
  }

  async function block(l: Row) {
    if (!confirm(`Never contact ${l.name}? Its email and phone go on the do-not-contact list.`)) return;
    try {
      await blockLead(l.id);
      applyLocal([l.id], "unsubscribed");
    } catch {
      setError("Couldn't block this lead. Make sure the API is running (yarn api:dev).");
    }
  }

  return (
    <div className="page wide leads-page">
      <header className="page-head">
        <div>
          <h1 className="title">Leads</h1>
          <p className="muted sub">Approved hotels are emailed first when you tell Jarvis to send. Blocked hotels are never contacted.</p>
        </div>
        {tab.key === "review" && reviewWithEmail > 0 && (
          <button className="btn primary" onClick={approveAll} disabled={working}>
            <Icon name="check" size={18} />
            Approve all with email{area ? ` in ${area}` : ""}
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
        <select id="lead-area" className="input" value={area} onChange={(e) => setParam({ area: e.target.value })} disabled={areas.length === 0}>
          <option value="">{areas.length ? `All areas (${areas.length})` : "Areas not ready yet"}</option>
          {areas.map((a) => (
            <option key={a.area} value={a.area}>{a.area} · {a.total} hotels{a.withEmail ? ` · ${a.withEmail} email` : ""}</option>
          ))}
        </select>
        <div className="search-box">
          <Icon name="search" size={16} />
          <label className="sr-only" htmlFor="lead-search">Search hotels by name, email or phone</label>
          <input id="lead-search" className="input" placeholder={`Search ${city || "hotels"} by name, email or phone…`} autoComplete="off"
            value={search} onChange={(e) => setSearch(e.target.value)} onFocus={loadIndex}
            onKeyDown={(e) => e.key === "Escape" && setSearch("")} />
          {search && (
            <button type="button" className="icon-btn clear" onClick={() => setSearch("")} aria-label="Clear search">×</button>
          )}
        </div>
      </div>

      {searching ? (
        <p className="muted small search-note" aria-live="polite">
          {indexLoading || !index
            ? "Getting the hotel list ready…"
            : `${hits.length.toLocaleString()} ${hits.length === 1 ? "match" : "matches"}${area ? ` in ${area}` : ` in ${city}`}, any status. Press Esc to clear.`}
        </p>
      ) : (
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab.key === t.key} className={`tab ${tab.key === t.key ? "active" : ""}`} onClick={() => setParam({ tab: t.key === "review" ? "" : t.key })}>
            {t.label} <span className="count">{tabCount(t.statuses).toLocaleString()}</span>
          </button>
        ))}
      </div>
      )}

      <section className="card table-card">
        <div className="lead-scroll" ref={listRef}>
          {searching && !searchPending && hits.length === 0 ? (
            <p className="empty">No hotel matches “{search.trim()}”. Try part of the name, the email, or the last digits of the phone.</p>
          ) : !searching && shown.length === 0 && !loading && cursor.current.done ? (
            <p className="empty">Nothing here.</p>
          ) : (
            <ul className="leads">
              {shown.map((l) => (
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
          )}
          <div ref={sentinelRef} className="list-end muted small" aria-live="polite">
            {searching
              ? searchPending ? <><span className="spinner" /> Searching…</> : hits.length > visible ? "" : hits.length ? `All ${hits.length} shown` : ""
              : loading ? <><span className="spinner" /> Loading more…</> : cursor.current.done && rows.length > 0 ? `All ${rows.length} loaded` : ""}
          </div>
        </div>
      </section>
    </div>
  );
}
