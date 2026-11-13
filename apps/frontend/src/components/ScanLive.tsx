import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { scansLive, type ScanRun } from "../lib/api";

const FAST_MS = 1500;    // while a search runs
const SLOW_MS = 15000;   // otherwise: just notice when one starts
const STEPS = [
  { key: "map", label: "Map search" },
  { key: "osm", label: "OpenStreetMap" },
  { key: "websites", label: "Reading websites for emails" },
  { key: "saving", label: "Saving" },
] as const;

/** Poll the live search state; `kick()` asks again at once (after starting a scan). */
export function useScanLive() {
  const [runs, setRuns] = useState<ScanRun[] | null>(null);
  const timer = useRef<number>();
  const load = useRef<() => void>(() => undefined);
  useEffect(() => {
    let stop = false;
    load.current = () => {
      window.clearTimeout(timer.current);
      scansLive().then((r) => {
        if (stop) return;
        setRuns(r.runs);
        timer.current = window.setTimeout(load.current, r.runs.some((x) => x.status === "running") && !document.hidden ? FAST_MS : SLOW_MS);
      }).catch(() => { if (!stop) timer.current = window.setTimeout(load.current, SLOW_MS); });
    };
    load.current();
    const wake = () => !document.hidden && load.current();
    document.addEventListener("visibilitychange", wake);
    return () => { stop = true; window.clearTimeout(timer.current); document.removeEventListener("visibilitychange", wake); };
  }, []);
  return { runs, kick: () => load.current() };
}

/** Seconds since an ISO time, ticking every second while `running`. */
function useElapsed(since: string | null | undefined, until: string | null | undefined, running: boolean) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [running]);
  if (!since) return 0;
  const end = until ? Date.parse(until) : now;
  return Math.max(0, Math.round((end - Date.parse(since)) / 1000));
}

const clock = (s: number) => (s >= 60 ? `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s` : `${s} s`);
const n = (v: number) => v.toLocaleString();

/** The search that is running now (or the last one), step by step, as the server reports it. */
export default function ScanLive({ runs, compact = false }: { runs: ScanRun[] | null; compact?: boolean }) {
  const run = runs?.[0];
  const running = run?.status === "running";
  const elapsed = useElapsed(run?.startedAt, running ? null : run?.finishedAt, running);
  const stepElapsed = useElapsed(run?.updatedAt, null, running && run?.step === "osm");
  if (!run) return null;
  // the last finished search only shows here for an hour; it's in Recent scans / Leads after that
  if (!running && run.finishedAt && Date.now() - Date.parse(run.finishedAt) > 3600_000) return null;

  const who = run.kind === "explorer" ? "Night explorer" : "Scan";
  const m = run.map, w = run.websites;
  const at = STEPS.findIndex((s) => s.key === run.step);
  const done = (i: number) => run.status === "done" || (at >= 0 && i < at);
  const leadsLink = run.city ? `/leads?city=${encodeURIComponent(run.city)}` : "/leads";

  if (compact) {
    if (!running) return null;
    const step = STEPS[at]?.label ?? "Working";
    return (
      <Link to="/campaigns" className="sl-bar" aria-live="polite">
        <span className="spinner" />
        <span><strong>{who}: {run.place}</strong> · {step}{run.step === "websites" && w.total ? ` ${w.done}/${w.total}` : ""} · {run.saved} saved · {clock(elapsed)}</span>
        <span className="sl-bar-go">Watch →</span>
      </Link>
    );
  }

  // a rough time left for the website step, from how fast it has gone so far
  const webSecs = w.startedAt ? (Date.now() - Date.parse(w.startedAt)) / 1000 : 0;
  const webLeft = w.done > 3 && w.total > w.done ? Math.round((webSecs / w.done) * (w.total - w.done)) : null;

  return (
    <section className={`card sl ${running ? "sl-running" : ""}`} aria-live="polite">
      <div className="card-head">
        <div>
          <h2>{running ? <><span className="sl-dot" aria-hidden="true" />Scanning now</> : run.status === "failed" ? "Last search stopped" : "Last search"}</h2>
          <div className="muted small">{who} · <strong className="sl-place">{run.place}</strong>{run.what ? ` · ${run.what}` : ""}</div>
        </div>
        <span className="sl-time">{clock(elapsed)}</span>
      </div>

      <ol className="sl-steps">
        {STEPS.map((s, i) => {
          const state = run.status === "failed" && i === at ? "failed" : done(i) ? "done" : i === at && running ? "active" : "todo";
          return (
            <li key={s.key} className={`sl-step sl-${state}`}>
              <span className="sl-mark">{state === "done" ? "✓" : state === "active" ? <span className="spinner" /> : state === "failed" ? "!" : i + 1}</span>
              <div className="sl-body">
                <div className="sl-label">{s.label}</div>
                {s.key === "map" && (m.searches > 0 || state === "active") && (
                  <>
                    <div className="small">
                      {state === "active" && m.kind ? <><strong>{m.kind}</strong> · square {m.square} · </> : ""}
                      {m.kindsDone} of {m.kindsTotal || "…"} kinds · {n(m.searches)} searches · <strong>{n(m.places)}</strong> places
                    </div>
                    {m.kindsTotal > 0 && <Bar value={m.kindsDone} max={m.kindsTotal} />}
                  </>
                )}
                {s.key === "osm" && state === "active" && (
                  <div className="small muted">Asking OpenStreetMap for more places… {clock(stepElapsed)} (it can take up to 2½ min; Jarvis moves on without it if it's busy)</div>
                )}
                {s.key === "osm" && run.osm.places !== null && <div className="small">+{n(run.osm.places)} places</div>}
                {s.key === "websites" && w.total > 0 && (
                  <>
                    <div className="small">
                      <strong>{w.done}</strong> of {w.total} read · <strong>{w.withEmail}</strong> with an email
                      {state === "active" && webLeft !== null ? ` · about ${clock(webLeft)} left` : ""}
                    </div>
                    <Bar value={w.done} max={w.total} />
                  </>
                )}
                {s.key === "saving" && (run.saved > 0 || state !== "todo") && (
                  <div className="small"><strong>{run.saved}</strong> new business{run.saved === 1 ? "" : "es"} with an email saved</div>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {run.status === "done" && (
        <div className="sl-result">
          <span>✅ {run.result}</span>
          <Link to={leadsLink} className="btn small">See them on Leads</Link>
        </div>
      )}
      {run.status === "failed" && <p className="error">{run.error}</p>}

      {run.events.length > 0 && (
        <>
          <h3 className="sl-feed-head">{running ? "Live" : "What it found"}</h3>
          <ul className="sl-feed">
            {run.events.map((e) => (
              <li key={`${e.at}-${e.text}`} className={`sl-ev sl-ev-${e.icon === "✉" ? "email" : e.icon === "✗" ? "none" : "info"}`}>
                <span className="sl-ev-icon" aria-hidden="true">{e.icon}</span>
                <span className="sl-ev-text">{e.text}</span>
                <span className="muted small nowrap">{new Date(e.at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function Bar({ value, max }: { value: number; max: number }) {
  const pct = max ? Math.min(100, (value / max) * 100) : 0;
  return <div className="sl-track" role="progressbar" aria-valuenow={value} aria-valuemax={max}><div className="sl-fill" style={{ width: `${pct}%` }} /></div>;
}
