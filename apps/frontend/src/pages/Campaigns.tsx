import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { collection, doc, limit, onSnapshot, orderBy, query } from "firebase/firestore";
import type { AreaSummary, Campaign, CitySummary } from "@jarvis/shared";
import { db, userPath } from "../lib/firebase";
import { errorText, resumeScan, scanPlace } from "../lib/api";
import { useUser } from "../lib/auth";
import { slug, timeAgo } from "../lib/format";
import Icon from "../components/Icon";

type Row = Campaign & { id: string };
type SortKey = "area" | "total" | "withEmail" | "withPhone" | "emailed" | "replied";

const RADII = [1, 2, 3, 5, 8];
const PHASE: Record<string, string> = {
  map: "Searching the map square by square",
  osm: "Adding hotels from OpenStreetMap",
  websites: "Reading hotel websites for emails and phones",
  done: "Done",
};

export default function Campaigns() {
  const user = useUser()!;
  const [campaigns, setCampaigns] = useState<Row[]>([]);
  const [mode, setMode] = useState<"city" | "spot">("city");
  const [place, setPlace] = useState("");
  const [radius, setRadius] = useState(3);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const q = query(collection(db, userPath(user.uid, "campaigns")), orderBy("createdAt", "desc"), limit(20));
    return onSnapshot(
      q,
      (s) => setCampaigns(s.docs.map((d) => ({ id: d.id, ...(d.data() as Campaign) }))),
      () => setError("Couldn't load scans. Check that the Firestore rules are published."),
    );
  }, [user.uid]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!place.trim()) return;
    setBusy(true);
    setError("");
    try {
      await scanPlace(place.trim(), mode === "city" ? null : radius);
      setPlace("");
    } catch (e) {
      setError(errorText(e, "Couldn't start the scan. The server may be waking up; try again in a minute."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page wide">
      <header className="page-head">
        <div>
          <h1 className="title">Find hotels</h1>
          <p className="muted sub">Scan a whole city, or search around one spot. Hotels are grouped by area automatically.</p>
        </div>
      </header>

      <form className="card campaign-form" onSubmit={onSubmit}>
        <div className="segmented" role="radiogroup" aria-label="Scan type">
          <button type="button" role="radio" aria-checked={mode === "city"} className={mode === "city" ? "active" : ""} onClick={() => setMode("city")}>Whole city</button>
          <button type="button" role="radio" aria-checked={mode === "spot"} className={mode === "spot" ? "active" : ""} onClick={() => setMode("spot")}>Around a spot</button>
        </div>
        <div className="field grow">
          <label htmlFor="place">{mode === "city" ? "City" : "Area"}</label>
          <input id="place" className="input" placeholder={mode === "city" ? "e.g. Hyderabad" : "e.g. Kukatpally, Hyderabad"} value={place} onChange={(e) => setPlace(e.target.value)} />
        </div>
        {mode === "spot" && (
          <div className="field">
            <label htmlFor="radius">Radius</label>
            <select id="radius" className="input" value={radius} onChange={(e) => setRadius(Number(e.target.value))}>
              {RADII.map((r) => <option key={r} value={r}>{r} km</option>)}
            </select>
          </div>
        )}
        <button className="btn primary" type="submit" disabled={busy || !place.trim()}>
          <Icon name="search" size={18} />
          {busy ? "Starting…" : mode === "city" ? "Scan city" : "Find hotels"}
        </button>
        <p className="muted small hint">
          {mode === "city"
            ? "A whole-city scan can take 20–40 minutes. You can close this page; Jarvis messages you on Telegram when it's done."
            : "Searches a square around the place, about a minute."}
        </p>
      </form>

      {error && <p className="error" role="alert">{error}</p>}

      {campaigns.length === 0 ? (
        <div className="card empty-card">
          <Icon name="campaign" size={28} />
          <p className="muted">No scans yet. Start with your city.</p>
        </div>
      ) : (
        campaigns.map((c) => <ScanCard key={c.id} c={c} />)
      )}
    </div>
  );
}

function ScanCard({ c }: { c: Row }) {
  const user = useUser()!;
  const [areas, setAreas] = useState<AreaSummary[]>([]);
  const [open, setOpen] = useState(false);
  const [sort, setSort] = useState<SortKey>("total");
  const ready = c.status === "ready" && !!c.city;

  useEffect(() => {
    if (!ready || !open) return;
    return onSnapshot(doc(db, userPath(user.uid, "cities", slug(c.city!))), (s) =>
      setAreas(Object.values((s.data() as CitySummary | undefined)?.areas ?? {})));
  }, [ready, open, c.city, user.uid]);

  const rows = useMemo(() => {
    const val = (a: AreaSummary) =>
      sort === "area" ? a.area : sort === "emailed" ? a.statuses.emailed ?? 0 : sort === "replied" ? (a.statuses.replied ?? 0) + (a.statuses.interested ?? 0) : a[sort];
    return [...areas].sort((a, b) => (sort === "area" ? String(val(a)).localeCompare(String(val(b))) : Number(val(b)) - Number(val(a))));
  }, [areas, sort]);

  const scan = c.scan;
  const found = scan?.found ?? c.stats.found;

  return (
    <article className="card campaign">
      <div className="card-head">
        <div>
          <h2>{c.name}</h2>
          <div className="muted small">
            {c.area.radiusM ? `${c.area.radiusM / 1000} km around the spot` : "Whole city"} · started {timeAgo(c.createdAt)}
          </div>
        </div>
        {c.status === "searching" ? (
          <span className="pill searching"><span className="spinner" /> Scanning</span>
        ) : c.status === "failed" ? (
          <span className="pill failed">Stopped</span>
        ) : (
          <span className="pill done">Ready</span>
        )}
      </div>

      {c.status === "searching" && (
        <div className="progress-block">
          <div className="muted">{PHASE[scan?.phase ?? "map"]}…</div>
          <div className="stat-row">
            <Stat label="Hotels found" value={found} />
            <Stat label="Squares searched" value={scan?.squaresDone ?? 0} />
            <Stat label="Squares left" value={scan?.queue?.length ?? 0} />
          </div>
        </div>
      )}

      {c.status === "failed" && (
        <div className="row-between">
          <p className="error">{c.error ?? "The scan stopped."} Progress is saved.</p>
          <button className="btn" onClick={() => resumeScan(c.id)}>Resume</button>
        </div>
      )}

      {ready && (
        <>
          <div className="stat-row">
            <Stat label="Hotels" value={c.stats.found} />
            <Stat label="With email" value={c.stats.withEmail} />
            <Stat label="With phone" value={c.stats.withPhone} />
          </div>
          <div className="row-between">
            <button className="btn" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
              {open ? "Hide areas" : "Show areas"}
            </button>
            <Link to={`/leads?city=${encodeURIComponent(c.city!)}`} className="btn">
              All leads <Icon name="arrow" size={16} />
            </Link>
          </div>
          {open && (
            <div className="table-wrap">
              <table className="areas">
                <thead>
                  <tr>
                    {([["area", "Area"], ["total", "Hotels"], ["withEmail", "Email"], ["withPhone", "Phone"], ["emailed", "Emailed"], ["replied", "Replied"]] as [SortKey, string][]).map(([k, label]) => (
                      <th key={k} aria-sort={sort === k ? (k === "area" ? "ascending" : "descending") : undefined}>
                        <button className={`th-btn ${sort === k ? "active" : ""}`} onClick={() => setSort(k)}>{label}</button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((a) => (
                    <tr key={a.area}>
                      <td>
                        <Link to={`/leads?city=${encodeURIComponent(a.city)}&area=${encodeURIComponent(a.area)}&tab=all`} className="area-link">{a.area}</Link>
                      </td>
                      <td>{a.total}</td>
                      <td className={a.withEmail ? "strong" : "muted"}>{a.withEmail}</td>
                      <td className={a.withPhone ? "" : "muted"}>{a.withPhone}</td>
                      <td>{a.statuses.emailed ?? 0}</td>
                      <td>{(a.statuses.replied ?? 0) + (a.statuses.interested ?? 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </article>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="stat">
      <span className="stat-value">{value.toLocaleString()}</span>
      <span className="muted small">{label}</span>
    </div>
  );
}
