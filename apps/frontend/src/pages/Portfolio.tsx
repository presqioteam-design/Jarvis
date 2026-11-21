import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  blockProspect, errorText, getPortfolio, listProspects, setPortfolioCollect, skipProspect, startPortfolioCheck,
  type PortfolioView, type Prospect, type SiteGroup,
} from "../lib/api";
import { hostname } from "../lib/format";
import Icon from "../components/Icon";

type Reach = "" | "email" | "call";

/**
 * Businesses that need a website, for marketing Vinod's web development work. Jarvis collects them
 * during every business search (and can check the leads already saved). Nothing is emailed from here yet.
 */
export default function Portfolio() {
  const [view, setView] = useState<PortfolioView | null>(null);
  const [params, setParams] = useSearchParams();
  const [rows, setRows] = useState<Prospect[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);

  const city = params.get("city") ?? view?.cities[0]?.city ?? "";
  const site = (params.get("site") ?? "") as SiteGroup | "";
  const reach = (params.get("reach") ?? "") as Reach;
  const category = params.get("category") ?? "";
  const summary = view?.cities.find((c) => c.city === city);

  const setParam = (updates: Record<string, string>) => {
    const p = new URLSearchParams(params);
    Object.entries(updates).forEach(([k, v]) => (v ? p.set(k, v) : p.delete(k)));
    setParams(p, { replace: true });
  };

  const refresh = useCallback(() => getPortfolio().then(setView).catch((e) => setError(errorText(e, "Couldn't load the portfolio list."))), []);
  useEffect(() => void refresh(), [refresh]);

  // while the saved-leads check runs, follow its progress
  useEffect(() => {
    if (!view?.check.running) return;
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [view?.check.running, refresh]);

  const load = useCallback(async (after: string | null) => {
    if (!city) return;
    const gen = generation.current;
    setLoading(true);
    try {
      const page = await listProspects({ city, site, reach, category, after: after ?? undefined });
      if (gen !== generation.current) return;
      setRows((r) => (after ? [...r, ...page.items] : page.items));
      setNext(page.next);
    } catch (e) {
      if (gen === generation.current) setError(errorText(e, "Couldn't load businesses. Check your connection and try again."));
    } finally {
      if (gen === generation.current) setLoading(false);
    }
  }, [city, site, reach, category]);

  useEffect(() => {
    generation.current += 1;
    setRows([]);
    setNext(null);
    setError("");
    void load(null);
  }, [load]);

  // counts from the city summary (every prospect, not just the loaded ones)
  const count = (g: SiteGroup | "", r: Reach) => {
    if (!summary) return 0;
    const groups = g ? [g] : (Object.keys(summary.site) as SiteGroup[]);
    return groups.reduce((n, k) => {
      const c = summary.site[k] ?? {};
      return n + (r ? (c[r] ?? 0) : (c.email ?? 0) + (c.call ?? 0));
    }, 0);
  };
  const categories = useMemo(
    () => (view?.categories ?? []).filter((c) => (summary?.category[c.key] ?? 0) > 0),
    [view, summary],
  );

  async function toggleCollect() {
    if (!view) return;
    setBusy(true);
    try {
      setView(await setPortfolioCollect(!view.collect));
    } catch (e) {
      setError(errorText(e, "Couldn't change that. Try again."));
    } finally {
      setBusy(false);
    }
  }

  async function check(restart: boolean) {
    setBusy(true);
    setError("");
    try {
      setView(await startPortfolioCheck(restart));
    } catch (e) {
      setError(errorText(e, "Couldn't start the website check. Try again."));
    } finally {
      setBusy(false);
    }
  }

  async function remove(p: Prospect, how: "skip" | "block") {
    if (how === "block" && !confirm(`Never contact ${p.name}? Its email and phone go on the do-not-contact list (for Presqio too).`)) return;
    try {
      await (how === "skip" ? skipProspect(p.id) : blockProspect(p.id));
      setRows((r) => r.filter((x) => x.id !== p.id));
      void refresh();
    } catch (e) {
      setError(errorText(e, "Couldn't update. Check your connection and try again."));
    }
  }

  const c = view?.check;
  return (
    <div className="page wide leads-page portfolio-page">
      <header className="page-head">
        <div>
          <h1 className="title">Portfolio</h1>
          <p className="muted sub">
            Businesses that need a website: none at all, only a social or listing page, a broken site, or a weak one.
            For marketing your web development work. Nothing is emailed from here yet.
          </p>
        </div>
      </header>

      {error && <p className="error" role="alert">{error}</p>}

      {view && (
        <section className="card portfolio-controls">
          <div className="settings-head">
            <div>
              <h2>Collect during business searches</h2>
              <p className="muted small">Every scan and night-explorer run also saves the businesses that need a website, with a phone or an email.</p>
            </div>
            <button type="button" role="switch" aria-checked={view.collect} aria-label="Collect during business searches"
              className={`switch ${view.collect ? "on" : ""}`} onClick={toggleCollect} disabled={busy}>
              <span />
            </button>
          </div>
          <div className="settings-head">
            <div>
              <h2>Businesses already in Leads</h2>
              <p className="muted small" aria-live="polite">
                {c?.running
                  ? <><span className="spinner" /> Reading their websites… {c.checked.toLocaleString()} checked, {c.added.toLocaleString()} need a website.</>
                  : c?.error
                    ? `${c.error} (${c.checked.toLocaleString()} checked so far.)`
                    : c?.finished
                      ? `All ${c.checked.toLocaleString()} checked; ${c.added.toLocaleString()} needed a website.`
                      : "Read the websites of the businesses Jarvis already found, and add the ones that need a better site."}
              </p>
            </div>
            {!c?.running && (
              <button className="btn" onClick={() => check(!!c?.finished)} disabled={busy}>
                <Icon name="search" size={16} />
                {c?.error ? "Continue" : c?.finished ? "Check again" : "Check their websites"}
              </button>
            )}
          </div>
        </section>
      )}

      {view && view.cities.length === 0 ? (
        <section className="card">
          <p className="empty">
            No businesses yet. They're added as Jarvis searches for businesses (Find businesses, or the night explorer),
            or press “Check their websites” above to look through the leads you already have.
          </p>
        </section>
      ) : view && (
        <>
          <div className="filters">
            <label className="sr-only" htmlFor="pf-city">City</label>
            <select id="pf-city" className="input" value={city} onChange={(e) => setParam({ city: e.target.value, category: "" })}>
              {view.cities.map((x) => <option key={x.city} value={x.city}>{x.city} · {x.total.toLocaleString()}</option>)}
            </select>
            <label className="sr-only" htmlFor="pf-category">Kind of business</label>
            <select id="pf-category" className="input" value={category} onChange={(e) => setParam({ category: e.target.value })}>
              <option value="">All businesses</option>
              {categories.map((x) => <option key={x.key} value={x.key}>{x.label} · {summary?.category[x.key]}</option>)}
            </select>
            <div className="segmented" role="group" aria-label="How to reach them">
              {([["", "All"], ["email", "Can email"], ["call", "Call list"]] as [Reach, string][]).map(([k, label]) => (
                <button key={k} className={reach === k ? "active" : ""} aria-pressed={reach === k} onClick={() => setParam({ reach: k })}>
                  {label} <span className="count">{count(site, k).toLocaleString()}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="tabs" role="tablist" aria-label="What their website is like">
            {[{ key: "" as const, label: "All" }, ...view.groups].map((g) => (
              <button key={g.key} role="tab" aria-selected={site === g.key} className={`tab ${site === g.key ? "active" : ""}`}
                onClick={() => setParam({ site: g.key })}>
                {g.label}
                {/* per-group counts aren't kept per category, so they show only without one */}
                {!category && <span className="count">{count(g.key, reach).toLocaleString()}</span>}
              </button>
            ))}
          </div>

          <section className="card table-card">
            <div className="lead-scroll">
              {rows.length === 0 && !loading ? (
                <p className="empty">Nothing here.</p>
              ) : (
                <ul className="leads">
                  {rows.map((p) => (
                    <li key={p.id} className="lead">
                      <div className="lead-main">
                        <div className="list-title">{p.name} <span className="cat-tag">{p.categoryLabel}</span></div>
                        <div className="muted small ellipsis">{[p.area, p.address].filter(Boolean).join(" · ") || "No address"}</div>
                        <div className="site-issues small">
                          <span className={`pill site-${p.site}`}>{p.siteLabel}</span>
                          {p.issues.map((i) => <span key={i} className="issue">{i}</span>)}
                        </div>
                      </div>
                      <div className="lead-contact small">
                        {p.emails[0] ? <a href={`mailto:${p.emails[0]}`} className="contact"><Icon name="mail" size={14} />{p.emails[0]}</a> : <span className="muted">No email</span>}
                        {p.phone ? <a href={`tel:${p.phone}`} className="contact"><Icon name="phone" size={14} />{p.phone}</a> : <span className="muted">No phone</span>}
                        {p.website && <a href={p.website} target="_blank" rel="noreferrer" className="contact muted">{hostname(p.website)}</a>}
                      </div>
                      <span className={`pill ${p.reach === "email" ? "emailed" : ""}`}>{p.reach === "email" ? "Can email" : "Call"}</span>
                      <div className="lead-actions">
                        <button className="btn small-btn" onClick={() => remove(p, "skip")} title="Leave it off the lists">Not a fit</button>
                        <button className="icon-btn" onClick={() => remove(p, "block")} title="Never contact" aria-label={`Block ${p.name}`}>
                          <Icon name="ban" size={16} />
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              <div className="list-end muted small" aria-live="polite">
                {loading ? <><span className="spinner" /> Loading…</> : next ? (
                  <button className="btn small-btn" onClick={() => load(next)}>Show more</button>
                ) : rows.length > 0 ? `All ${rows.length} shown` : ""}
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
