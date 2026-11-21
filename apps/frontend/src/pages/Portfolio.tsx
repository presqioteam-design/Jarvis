import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  approveAllProspects, blockProspect, errorText, getPortfolio, listProspects, reviewProspects, setPortfolioCollect, skipProspect,
  startPortfolioCheck, type PortfolioTab, type PortfolioView, type Prospect, type ProspectStatus, type SiteGroup,
} from "../lib/api";
import { hostname, timeAgo } from "../lib/format";
import Icon from "../components/Icon";
import { PortfolioSendingCard, ProspectPreview } from "./PortfolioSending";

type Reach = "" | "email" | "call";

const TABS: { key: PortfolioTab; label: string; statuses: ProspectStatus[] }[] = [
  { key: "review", label: "To review", statuses: ["new"] },
  { key: "approved", label: "Approved", statuses: ["ready"] },
  { key: "contacted", label: "Contacted", statuses: ["emailed", "replied", "interested"] },
  { key: "closed", label: "Closed", statuses: ["not_interested", "unsubscribed", "bounced"] },
];
const STATUS_TEXT: Record<ProspectStatus, string> = {
  new: "To review", ready: "Approved", emailed: "Emailed", replied: "Replied", interested: "Interested",
  not_interested: "Not interested", unsubscribed: "Asked to stop", bounced: "Bounced",
};

/**
 * Businesses that need a website, for marketing Vinod's web development work. Jarvis collects them
 * during every business search; approved ones are emailed from his own Gmail.
 */
export default function Portfolio() {
  const [view, setView] = useState<PortfolioView | null>(null);
  const [params, setParams] = useSearchParams();
  const [rows, setRows] = useState<Prospect[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [previewing, setPreviewing] = useState<Prospect | null>(null);
  const generation = useRef(0);

  const city = params.get("city") ?? view?.cities[0]?.city ?? "";
  const tab = TABS.find((t) => t.key === params.get("tab")) ?? TABS[0];
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

  // follow the saved-leads check and a running send batch
  useEffect(() => {
    if (!view?.check.running && !view?.busy) return;
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [view?.check.running, view?.busy, refresh]);

  const load = useCallback(async (after: string | null) => {
    if (!city) return;
    const gen = generation.current;
    setLoading(true);
    try {
      const page = await listProspects({ city, tab: tab.key, site, reach, category, after: after ?? undefined });
      if (gen !== generation.current) return;
      setRows((r) => (after ? [...r, ...page.items] : page.items));
      setNext(page.next);
    } catch (e) {
      if (gen === generation.current) setError(errorText(e, "Couldn't load businesses. Check your connection and try again."));
    } finally {
      if (gen === generation.current) setLoading(false);
    }
  }, [city, tab.key, site, reach, category]);

  useEffect(() => {
    generation.current += 1;
    setRows([]);
    setNext(null);
    setError("");
    void load(null);
  }, [load]);

  // counts from the city summary, for every prospect, not just the loaded ones
  const count = (statuses: ProspectStatus[], g: SiteGroup | "", r: Reach) => {
    if (!summary) return 0;
    let n = 0;
    for (const st of statuses) {
      const bySite = summary.n[st] ?? {};
      for (const [k, c] of Object.entries(bySite)) {
        if ((!g || k === g) && c) n += r ? (c[r] ?? 0) : (c.email ?? 0) + (c.call ?? 0);
      }
    }
    return n;
  };
  const perCategory = useMemo(() => {
    const out: Record<string, number> = {};
    for (const st of tab.statuses) Object.entries(summary?.c[st] ?? {}).forEach(([k, n]) => (out[k] = (out[k] ?? 0) + n));
    return out;
  }, [summary, tab]);

  async function act(fn: () => Promise<unknown>, fallback: string) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(errorText(e, fallback));
    } finally {
      setBusy(false);
    }
  }

  const dropRow = (id: string) => setRows((r) => r.filter((x) => x.id !== id));

  const review = (p: Prospect, approved: boolean) => act(async () => {
    await reviewProspects([p.id], approved);
    dropRow(p.id);
    void refresh();
  }, "Couldn't update. Check your connection and try again.");

  const remove = (p: Prospect, how: "skip" | "block") => {
    if (how === "block" && !confirm(`Never contact ${p.name}? Its email and phone go on the do-not-contact list (for Presqio too).`)) return;
    void act(async () => {
      await (how === "skip" ? skipProspect(p.id) : blockProspect(p.id));
      dropRow(p.id);
      void refresh();
    }, "Couldn't update. Check your connection and try again.");
  };

  const approveAll = () => {
    const n = count(["new"], site, "email");
    const what = site ? view?.groups.find((g) => g.key === site)?.label.toLowerCase() : "all groups";
    if (!confirm(`Approve ${category ? "these" : "all"} ${n} businesses with an email in ${city} (${what})? Only approved ones are emailed.`)) return;
    void act(async () => {
      const { approved } = await approveAllProspects(city, site || null, category || null);
      await refresh();
      await load(null);
      alert(`Approved ${approved}.`);
    }, "Couldn't approve. Check your connection and try again.");
  };

  const c = view?.check;
  const waitingWithEmail = tab.key === "review" ? count(["new"], site, "email") : 0;
  return (
    <div className="page wide leads-page portfolio-page">
      <header className="page-head">
        <div>
          <h1 className="title">Portfolio</h1>
          <p className="muted sub">
            Businesses that need a website: none at all, only a social or listing page, a broken site, or a weak one.
            Approve the ones to email; Jarvis emails them from your own Gmail and tells you on Telegram when they reply.
          </p>
        </div>
        {waitingWithEmail > 0 && (
          <button className="btn primary" onClick={approveAll} disabled={busy}>
            <Icon name="check" size={18} /> Approve all with email
          </button>
        )}
      </header>

      {error && <p className="error" role="alert">{error}</p>}

      {view && view.cities.length === 0 ? (
        <section className="card">
          <p className="empty">
            No businesses yet. They're added as Jarvis searches for businesses (Find businesses, or the night explorer),
            or press “Check their websites” below to look through the leads you already have.
          </p>
        </section>
      ) : view && (
        <>
          <div className="tabs" role="tablist" aria-label="Status">
            {TABS.map((t) => (
              <button key={t.key} role="tab" aria-selected={tab.key === t.key} className={`tab ${tab.key === t.key ? "active" : ""}`}
                onClick={() => setParam({ tab: t.key === "review" ? "" : t.key })}>
                {t.label}
                <span className="count">{count(t.statuses, "", "").toLocaleString()}</span>
              </button>
            ))}
          </div>

          <div className="filters">
            <label className="sr-only" htmlFor="pf-city">City</label>
            <select id="pf-city" className="input" value={city} onChange={(e) => setParam({ city: e.target.value, category: "" })}>
              {view.cities.map((x) => <option key={x.city} value={x.city}>{x.city} · {x.total.toLocaleString()}</option>)}
            </select>
            <label className="sr-only" htmlFor="pf-group">What their website is like</label>
            <select id="pf-group" className="input" value={site} onChange={(e) => setParam({ site: e.target.value })}>
              <option value="">Every kind of website · {count(tab.statuses, "", reach).toLocaleString()}</option>
              {view.groups.map((g) => <option key={g.key} value={g.key}>{g.label} · {count(tab.statuses, g.key, reach).toLocaleString()}</option>)}
            </select>
            <label className="sr-only" htmlFor="pf-category">Kind of business</label>
            <select id="pf-category" className="input" value={category} onChange={(e) => setParam({ category: e.target.value })}>
              <option value="">All businesses</option>
              {view.categories.filter((x) => perCategory[x.key] || x.key === category).map((x) => (
                <option key={x.key} value={x.key}>{x.label} · {perCategory[x.key] ?? 0}</option>
              ))}
            </select>
            {tab.key === "review" && (
              <div className="segmented" role="group" aria-label="How to reach them">
                {([["", "All"], ["email", "Can email"], ["call", "Call list"]] as [Reach, string][]).map(([k, label]) => (
                  <button key={k} className={reach === k ? "active" : ""} aria-pressed={reach === k} onClick={() => setParam({ reach: k })}>
                    {label} <span className="count">{count(tab.statuses, site, k).toLocaleString()}</span>
                  </button>
                ))}
              </div>
            )}
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
                        {p.replySummary && <div className="small reply-note">“{p.replySummary}”</div>}
                      </div>
                      <div className="lead-contact small">
                        {(p.emailedTo || p.emails[0])
                          ? <a href={`mailto:${p.emailedTo || p.emails[0]}`} className="contact"><Icon name="mail" size={14} />{p.emailedTo || p.emails[0]}</a>
                          : <span className="muted">No email</span>}
                        {p.phone ? <a href={`tel:${p.phone}`} className="contact"><Icon name="phone" size={14} />{p.phone}</a> : <span className="muted">No phone</span>}
                        {p.website && <a href={p.website} target="_blank" rel="noreferrer" className="contact muted">{hostname(p.website)}</a>}
                      </div>
                      <span className={`pill ${p.status === "new" ? (p.reach === "email" ? "emailed" : "") : p.status}`}
                        title={p.lastContactAt ? `Last email ${timeAgo(p.lastContactAt)}` : undefined}>
                        {p.status === "new" ? (p.reach === "email" ? "Can email" : "Call") : STATUS_TEXT[p.status]}
                        {p.status === "emailed" && p.followUps > 0 ? ` · ${p.followUps} follow-up${p.followUps > 1 ? "s" : ""}` : ""}
                      </span>
                      <div className="lead-actions">
                        {p.reach === "email" && (
                          <button className="icon-btn" onClick={() => setPreviewing(p)} title="See the emails" aria-label={`See the emails for ${p.name}`}>
                            <Icon name="mail" size={16} />
                          </button>
                        )}
                        {p.status === "new" && p.reach === "email" && (
                          <button className="btn small-btn" onClick={() => review(p, true)} disabled={busy}>Approve</button>
                        )}
                        {p.status === "ready" && <button className="btn small-btn" onClick={() => review(p, false)} disabled={busy}>Undo</button>}
                        {(p.status === "new" || p.status === "ready") && (
                          <button className="btn small-btn" onClick={() => remove(p, "skip")} disabled={busy} title="Leave it off the lists">Not a fit</button>
                        )}
                        {!["unsubscribed", "bounced"].includes(p.status) && (
                          <button className="icon-btn" onClick={() => remove(p, "block")} title="Never contact" aria-label={`Block ${p.name}`}>
                            <Icon name="ban" size={16} />
                          </button>
                        )}
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

      {view && <PortfolioSendingCard view={view} onChange={setView} />}

      {view && (
        <section className="card portfolio-controls">
          <div className="settings-head">
            <div>
              <h2>Collect during business searches</h2>
              <p className="muted small">Every scan and night-explorer run also saves the businesses that need a website, with a phone or an email.</p>
            </div>
            <button type="button" role="switch" aria-checked={view.collect} aria-label="Collect during business searches"
              className={`switch ${view.collect ? "on" : ""}`} disabled={busy}
              onClick={() => act(async () => setView(await setPortfolioCollect(!view.collect)), "Couldn't change that. Try again.")}>
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
              <button className="btn" disabled={busy}
                onClick={() => act(async () => setView(await startPortfolioCheck(!!c?.finished)), "Couldn't start the website check. Try again.")}>
                <Icon name="search" size={16} />
                {c?.error ? "Continue" : c?.finished ? "Check again" : "Check their websites"}
              </button>
            )}
          </div>
        </section>
      )}


      {previewing && view && (
        <ProspectPreview prospect={previewing} from={`${view.me.senderName} <${view.mailbox.address}>`} onClose={() => setPreviewing(null)} />
      )}
    </div>
  );
}
