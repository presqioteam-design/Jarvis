import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { collection, doc, onSnapshot, orderBy, query } from "firebase/firestore";
import { CATEGORIES, categoryLabel, type AreaSummary, type Campaign, type CategoryKey, type CitySummary } from "@jarvis/shared";
import { db, userPath } from "../lib/firebase";
import { errorText, resumeScan, scanPlace } from "../lib/api";
import { useUser } from "../lib/auth";
import { slug, timeAgo } from "../lib/format";
import { LoadMore, usePaged } from "../lib/paging";
import Icon from "../components/Icon";

type Row = Campaign & { id: string };
type SortKey = "area" | "total" | "withEmail" | "emailed" | "replied";

const RADII = [1, 2, 3, 5, 8];
const PHASE: Record<string, string> = {
  map: "Searching the map square by square",
  osm: "Adding places from OpenStreetMap",
  websites: "Finishing up",
  done: "Done",
};

export default function Campaigns() {
  const user = useUser()!;
  const [mode, setMode] = useState<"city" | "spot">("city");
  const [place, setPlace] = useState("");
  const [radius, setRadius] = useState(3);
  const [category, setCategory] = useState<CategoryKey | "all">("all");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const listRef = useRef<HTMLDivElement>(null);
  const scans = usePaged<Campaign>(
    query(collection(db, userPath(user.uid, "campaigns")), orderBy("createdAt", "desc")),
    `campaigns:${user.uid}`,
    10,
  );
  const campaigns: Row[] = scans.rows;
  useEffect(() => {
    if (scans.error) setError("Couldn't load scans. Check that the Firestore rules are published.");
  }, [scans.error]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!place.trim()) return;
    setBusy(true);
    setError("");
    try {
      await scanPlace(place.trim(), mode === "city" ? null : radius, category);
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
          <h1 className="title">Find businesses</h1>
          <p className="muted sub">
            Scan a whole city or one spot for every kind of business (or just one). Jarvis reads their websites and
            saves only the ones with an email, grouped by area.
          </p>
        </div>
      </header>

      <form className="card campaign-form" onSubmit={onSubmit}>
        <div className="segmented" role="radiogroup" aria-label="Scan type">
          <button type="button" role="radio" aria-checked={mode === "city"} className={mode === "city" ? "active" : ""} onClick={() => setMode("city")}>Whole city</button>
          <button type="button" role="radio" aria-checked={mode === "spot"} className={mode === "spot" ? "active" : ""} onClick={() => setMode("spot")}>Around a spot</button>
        </div>
        <div className="field">
          <label htmlFor="category">Business</label>
          <select id="category" className="input" value={category} onChange={(e) => setCategory(e.target.value as CategoryKey | "all")}>
            <option value="all">All businesses</option>
            {CATEGORIES.map((c) => <option key={c.key} value={c.key}>Only {c.label.toLowerCase()}</option>)}
          </select>
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
          {busy ? "Starting…" : mode === "city" ? "Scan city" : "Search here"}
        </button>
        <p className="muted small hint">
          {mode === "city"
            ? "A whole-city scan of every kind of business can take an hour or more, and a big city may pause to stay within the free map searches and carry on when you press Resume the next day. You can close this page; Jarvis messages you on Telegram."
            : "Searches a square around the place, a few minutes."}
        </p>
      </form>

      {error && <p className="error" role="alert">{error}</p>}

      <section className="card scans">
        <div className="card-head">
          <h2>Your scans</h2>
          <span className="muted small">{scans.ready ? `${campaigns.length}${scans.more ? "+" : ""} scans, newest first` : ""}</span>
        </div>
        <div className="scans-scroll" ref={listRef}>
          {scans.ready && campaigns.length === 0 ? (
            <div className="empty-card">
              <Icon name="campaign" size={28} />
              <p className="muted">No scans yet. Start with your city.</p>
            </div>
          ) : (
            campaigns.map((c) => <ScanCard key={c.id} c={c} />)
          )}
          <LoadMore root={listRef} more={scans.more} loading={scans.loading} onVisible={scans.loadMore}
            done={campaigns.length > 10 ? `All ${campaigns.length} scans shown` : ""} />
        </div>
      </section>
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
            <span className="cat-tag">{categoryLabel(c.category)}</span>{" "}
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
            <Stat label="New with email" value={found} />
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
            {/* scans from before email-only saving counted phone-only places (since removed) */}
            {c.category && <Stat label="New from this scan" value={c.scan?.found ?? 0} />}
            <Stat label="To email in the area" value={c.stats.withEmail} />
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
            <div className="table-wrap areas-scroll">
              <table className="areas">
                <thead>
                  <tr>
                    {([["area", "Area"], ["total", "Businesses"], ["withEmail", "Email"], ["emailed", "Emailed"], ["replied", "Replied"]] as [SortKey, string][]).map(([k, label]) => (
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
