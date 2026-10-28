import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { collection, limit, onSnapshot, orderBy, query } from "firebase/firestore";
import type { Campaign } from "@jarvis/shared";
import { db, userPath } from "../lib/firebase";
import { createCampaign } from "../lib/api";
import { useUser } from "../lib/auth";
import { timeAgo } from "../lib/format";
import Icon from "../components/Icon";

const RADII = [1, 2, 3, 5, 8];
const EXAMPLES = ["Madhapur, Hyderabad", "Gachibowli, Hyderabad", "Banjara Hills, Hyderabad"];

export default function Campaigns() {
  const user = useUser()!;
  const [campaigns, setCampaigns] = useState<(Campaign & { id: string })[]>([]);
  const [area, setArea] = useState("");
  const [radius, setRadius] = useState(3);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const q = query(collection(db, userPath(user.uid, "campaigns")), orderBy("createdAt", "desc"), limit(50));
    return onSnapshot(
      q,
      (s) => setCampaigns(s.docs.map((d) => ({ id: d.id, ...(d.data() as Campaign) }))),
      () => setError("Couldn't load campaigns. Check that the Firestore rules are published."),
    );
  }, [user.uid]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!area.trim()) return;
    setBusy(true);
    setError("");
    try {
      await createCampaign(area.trim(), radius);
      setArea("");
    } catch {
      setError("Couldn't start the search. Make sure the API is running (yarn api:dev).");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1 className="title">Campaigns</h1>
          <p className="muted sub">Pick an area. Jarvis finds the hotels there and looks up their contact details.</p>
        </div>
      </header>

      <form className="card campaign-form" onSubmit={onSubmit}>
        <div className="field grow">
          <label htmlFor="area">Area</label>
          <input id="area" className="input" placeholder="e.g. Madhapur, Hyderabad" value={area} onChange={(e) => setArea(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="radius">Radius</label>
          <select id="radius" className="input" value={radius} onChange={(e) => setRadius(Number(e.target.value))}>
            {RADII.map((r) => (
              <option key={r} value={r}>{r} km</option>
            ))}
          </select>
        </div>
        <button className="btn primary" type="submit" disabled={busy || !area.trim()}>
          <Icon name="search" size={18} />
          {busy ? "Starting…" : "Find hotels"}
        </button>
        <div className="examples">
          <span className="muted small">Try:</span>
          {EXAMPLES.map((x) => (
            <button key={x} type="button" className="chip small" onClick={() => setArea(x)}>{x}</button>
          ))}
        </div>
      </form>

      {error && <p className="error" role="alert">{error}</p>}

      {campaigns.length === 0 ? (
        <div className="card empty-card">
          <Icon name="campaign" size={28} />
          <p className="muted">No campaigns yet. Start with the area around your office.</p>
        </div>
      ) : (
        <div className="campaigns">
          {campaigns.map((c) => (
            <article key={c.id} className="card campaign">
              <div className="card-head">
                <div>
                  <h2>{c.area.label}</h2>
                  <div className="muted small">{c.area.radiusM / 1000} km radius · {timeAgo(c.createdAt)}</div>
                </div>
                <CampaignStatus c={c} />
              </div>
              {c.status === "failed" ? (
                <p className="error">{c.error ?? "Search failed."}</p>
              ) : c.status === "searching" ? (
                <p className="muted">Searching maps and reading hotel websites. This takes about a minute.</p>
              ) : (
                <>
                  <div className="stat-row">
                    <Stat label="Hotels" value={c.stats.found} />
                    <Stat label="With email" value={c.stats.withEmail} />
                    <Stat label="With phone" value={c.stats.withPhone} />
                  </div>
                  <Link to={`/leads?campaign=${c.id}`} className="btn">
                    Review leads <Icon name="arrow" size={16} />
                  </Link>
                </>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function CampaignStatus({ c }: { c: Campaign }) {
  if (c.status === "searching") return <span className="pill searching"><span className="spinner" /> Searching</span>;
  if (c.status === "failed") return <span className="pill failed">Failed</span>;
  return <span className="pill done">Ready</span>;
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="stat">
      <span className="stat-value">{value}</span>
      <span className="muted small">{label}</span>
    </div>
  );
}
