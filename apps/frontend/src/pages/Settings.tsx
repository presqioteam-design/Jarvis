import { useEffect, useMemo, useState } from "react";
import {
  errorText, getFinding, getSending, prioritiseCity, saveFinding, saveSending, skipCity,
  type FindingSettings, type FindingView, type SendingSettings, type SendingView,
} from "../lib/api";
import Icon from "../components/Icon";

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** "09:30", "10:00", … between the cron's first and last run (it fires on :00 and :30). */
function halfHours(from: string, to: string): string[] {
  const out: string[] = [];
  const [h0, m0] = from.split(":").map(Number);
  const [h1, m1] = to.split(":").map(Number);
  for (let t = h0 * 60 + m0; t <= h1 * 60 + m1; t += 30) out.push(`${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`);
  return out;
}

const ampm = (t: string) => {
  const [h, m] = t.split(":").map(Number);
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
};

function runsPerDay(from: string, until: string): number {
  const min = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3));
  const first = Math.ceil(min(from) / 30) * 30;
  return min(until) >= first ? Math.floor((min(until) - first) / 30) + 1 : 0;
}

export default function Settings() {
  return (
    <div className="page settings-page">
      <header className="page-head">
        <div>
          <h1 className="title">Settings</h1>
          <p className="muted sub">Changes apply from Jarvis's next run, within 30 minutes. No redeploy needed.</p>
        </div>
      </header>
      <SendingSection />
      <FindingSection />
    </div>
  );
}

// kept between visits so coming back to Settings shows the last values at once
let lastSending: SendingView | null = null;

function SendingSection() {
  const [view, setViewState] = useState<SendingView | null>(lastSending);
  const [form, setForm] = useState<SendingSettings | null>(lastSending?.settings ?? null);
  const setView = (v: SendingView) => {
    lastSending = v;
    setViewState(v);
  };
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  // refresh quietly; don't overwrite anything already being edited
  useEffect(() => {
    const before = lastSending;
    getSending()
      .then((v) => {
        setView(v);
        setForm((f) => (!f || !before || JSON.stringify(f) === JSON.stringify(before.settings) ? v.settings : f));
      })
      .catch((e) => {
        if (!before) setError(errorText(e, "Couldn't load the settings. The server may be waking up; try again in a minute."));
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const changed = useMemo(() => !!form && !!view && JSON.stringify(form) !== JSON.stringify(view.settings), [form, view]);

  if (!form || !view) {
    return (
      <section className="card settings-card">
        <h2>Automatic sending</h2>
        {error ? <p className="error" role="alert">{error}</p> : <p className="muted"><span className="spinner" /> Loading…</p>}
      </section>
    );
  }

  const { limits } = view;
  const set = (patch: Partial<SendingSettings>) => {
    setSaved(false);
    setForm({ ...form, ...patch });
  };
  const times = halfHours(limits.earliest, limits.latest);
  const runs = runsPerDay(form.from, form.until);
  const possible = runs * form.perRun;
  const perDay = Math.min(possible, form.dailyAuto, form.dailyCap);
  const days = form.days.length;

  async function save() {
    setBusy(true);
    setError("");
    try {
      const v = await saveSending(form!);
      setView(v);
      setForm(v.settings);
      setSaved(true);
    } catch (e) {
      setError(errorText(e, "Couldn't save. Check your connection and try again."));
    } finally {
      setBusy(false);
    }
  }

  // the on/off switch saves at once, like "pause auto" on Telegram
  async function toggle() {
    const enabled = !form!.enabled;
    set({ enabled });
    try {
      const v = await saveSending({ enabled });
      setView(v);
      setForm((f) => (f ? { ...f, enabled: v.settings.enabled } : f));
    } catch (e) {
      set({ enabled: !enabled });
      setError(errorText(e, "Couldn't switch automatic sending. Try again."));
    }
  }

  return (
    <section className="card settings-card" aria-labelledby="sending-title">
      <div className="settings-head">
        <div>
          <h2 id="sending-title">Automatic sending</h2>
          <p className="muted small">Jarvis emails businesses on its own every 30 minutes in these hours. Same as “pause auto” / “resume auto” on Telegram.</p>
        </div>
        <button type="button" role="switch" aria-checked={form.enabled} aria-label="Automatic sending" className={`switch ${form.enabled ? "on" : ""}`} onClick={toggle}>
          <span />
        </button>
      </div>

      <div className={`settings-grid ${form.enabled ? "" : "is-off"}`}>
        <div className="field">
          <label htmlFor="per-run">Emails each run</label>
          <input id="per-run" className="input" type="number" min={1} max={limits.maxPerRun} value={form.perRun}
            onChange={(e) => set({ perRun: Number(e.target.value) })} />
          <span className="muted small">1–{limits.maxPerRun}. Jarvis waits 20–45 s between emails.</span>
        </div>
        <div className="field">
          <label htmlFor="daily-auto">Automatic emails a day</label>
          <input id="daily-auto" className="input" type="number" min={1} max={form.dailyCap} value={form.dailyAuto}
            onChange={(e) => set({ dailyAuto: Number(e.target.value) })} />
          <span className="muted small">Auto stops here; “send 10” on Telegram can use the rest.</span>
        </div>
        <div className="field">
          <label htmlFor="daily-cap">Daily limit (all emails)</label>
          <input id="daily-cap" className="input" type="number" min={1} max={limits.maxDaily} value={form.dailyCap}
            onChange={(e) => set({ dailyCap: Number(e.target.value) })} />
          <span className="muted small">Hard limit, protects the Gmail account. Up to {limits.maxDaily}.</span>
        </div>

        <div className="field">
          <label htmlFor="from">From</label>
          <select id="from" className="input" value={form.from} onChange={(e) => set({ from: e.target.value })}>
            {times.slice(0, -1).map((t) => <option key={t} value={t}>{ampm(t)}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="until">Until</label>
          <select id="until" className="input" value={form.until} onChange={(e) => set({ until: e.target.value })}>
            {times.filter((t) => t > form.from).map((t) => <option key={t} value={t}>{ampm(t)}</option>)}
          </select>
        </div>
        <div className="field">
          <span className="label">Days</span>
          <div className="day-chips" role="group" aria-label="Sending days">
            {DAY_NAMES.map((d, i) => {
              const on = form.days.includes(i);
              return (
                <button key={d} type="button" aria-pressed={on} className={`chip ${on ? "on" : ""}`}
                  onClick={() => set({ days: on ? form.days.filter((x) => x !== i) : [...form.days, i].sort() })}>
                  {d}
                </button>
              );
            })}
          </div>
        </div>

        <div className="field wide">
          <label className="check">
            <input type="checkbox" checked={form.followUps} onChange={(e) => set({ followUps: e.target.checked })} />
            Send follow-ups automatically (they go first in each run)
          </label>
          {form.followUps && (
            <div className="follow-days">
              <span>First follow-up after</span>
              <select className="input" aria-label="Days until the first follow-up" value={form.followUpDays[0]}
                onChange={(e) => set({ followUpDays: [Number(e.target.value), Math.max(form.followUpDays[1], Number(e.target.value) + 1)] })}>
                {Array.from({ length: 14 }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n} day{n > 1 ? "s" : ""}</option>)}
              </select>
              <span>second after</span>
              <select className="input" aria-label="Days until the second follow-up" value={form.followUpDays[1]}
                onChange={(e) => set({ followUpDays: [form.followUpDays[0], Number(e.target.value)] })}>
                {Array.from({ length: 30 - form.followUpDays[0] }, (_, i) => i + form.followUpDays[0] + 1).map((n) => <option key={n} value={n}>{n} days</option>)}
              </select>
              <span className="muted small">(counted from the first email)</span>
            </div>
          )}
        </div>
      </div>

      <div className="settings-summary" aria-live="polite">
        <Icon name="mail" size={18} />
        <div>
          {!form.enabled ? (
            <strong>Automatic sending is paused.</strong>
          ) : days === 0 ? (
            <strong>Pick at least one day.</strong>
          ) : (
            <>
              <strong>Up to {perDay} automatic emails a day</strong>, {days === 6 ? "Monday to Saturday" : `${days} day${days > 1 ? "s" : ""} a week`}:
              {" "}{form.perRun} every 30 min, {runs} runs from {ampm(form.from)} to {ampm(form.until)}.
              {possible < form.dailyAuto && <span className="warn"> These hours allow only {possible}; widen them or send more per run to reach {form.dailyAuto}.</span>}
              {form.dailyAuto > form.dailyCap && <span className="warn"> Automatic emails can't be more than the daily limit.</span>}
            </>
          )}
          <div className="muted small">Sent today: {view.sentToday} of {view.settings.dailyCap}.</div>
        </div>
      </div>

      {error && <p className="error" role="alert">{error}</p>}
      <div className="settings-actions">
        {saved && !changed && <span className="saved"><Icon name="check" size={16} /> Saved</span>}
        <button className="btn" type="button" disabled={!changed || busy} onClick={() => { setForm(view.settings); setError(""); }}>Undo changes</button>
        <button className="btn primary" type="button" disabled={!changed || busy || days === 0} onClick={save}>
          {busy ? "Saving…" : "Save"}
        </button>
      </div>
    </section>
  );
}

// ── section 2: what to find ────────────────────────────────────────────────

let lastFinding: FindingView | null = null;

function FindingSection() {
  const [view, setViewState] = useState<FindingView | null>(lastFinding);
  const [form, setForm] = useState<FindingSettings | null>(lastFinding?.settings ?? null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [newCity, setNewCity] = useState("");
  const setView = (v: FindingView) => {
    lastFinding = v;
    setViewState(v);
  };

  useEffect(() => {
    const before = lastFinding;
    getFinding()
      .then((v) => {
        setView(v);
        setForm((f) => (!f || !before || JSON.stringify(f) === JSON.stringify(before.settings) ? v.settings : f));
      })
      .catch((e) => {
        if (!before) setError(errorText(e, "Couldn't load these settings. The server may be waking up; try again in a minute."));
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const changed = useMemo(() => !!form && !!view && JSON.stringify(form) !== JSON.stringify(view.settings), [form, view]);

  if (!form || !view) {
    return (
      <section className="card settings-card">
        <h2>What to find</h2>
        {error ? <p className="error" role="alert">{error}</p> : <p className="muted"><span className="spinner" /> Loading…</p>}
      </section>
    );
  }

  const on = new Set(form.categories);
  const toggleKind = (key: string) => {
    setNote("");
    setForm({ ...form, categories: on.has(key) ? form.categories.filter((k) => k !== key) : [...form.categories, key] });
  };

  async function act(label: string, fn: () => Promise<FindingView & { note?: string }>, keepForm = false) {
    setBusy(label);
    setError("");
    setNote("");
    try {
      const v = await fn();
      setView(v);
      if (!keepForm) setForm(v.settings);
      else setForm((f) => (f ? { ...f, exploreEnabled: v.settings.exploreEnabled } : f));
      if (v.note) setNote(v.note);
      return true;
    } catch (e) {
      setError(errorText(e, "That didn't work. Check your connection and try again."));
      return false;
    } finally {
      setBusy("");
    }
  }

  // the explorer switch saves at once, like "pause explore" / "resume explore" on Telegram
  const toggleExplorer = () => act("explore", () => saveFinding({ exploreEnabled: !form.exploreEnabled }), true);
  const addCity = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newCity.trim() && (await act("add", () => prioritiseCity(newCity.trim()), true))) setNewCity("");
  };

  const searchesPerNight = form.areasPerNight * Math.round((form.categories.length / view.categories.length) * 110);

  return (
    <section className="card settings-card" aria-labelledby="finding-title">
      <div>
        <h2 id="finding-title">What to find</h2>
        <p className="muted small">
          The kinds switched on are what “All businesses” scans and the night explorer search for. You can still scan
          any one kind by naming it, e.g. “scan factories in Patancheru 3km”.
        </p>
      </div>

      <div className="kind-grid" role="group" aria-label="Kinds of business">
        {view.categories.map((c) => (
          <label key={c.key} className={`kind ${on.has(c.key) ? "on" : ""}`}>
            <input type="checkbox" checked={on.has(c.key)} onChange={() => toggleKind(c.key)} />
            <span>{c.label}</span>
          </label>
        ))}
      </div>
      <div className="row-links small">
        <button type="button" className="link-btn" onClick={() => setForm({ ...form, categories: view.categories.map((c) => c.key) })}>Switch all on</button>
        <span className="muted">{form.categories.length} of {view.categories.length} on</span>
      </div>

      <div className="settings-sub">
        <div className="settings-head">
          <div>
            <h3>Night explorer</h3>
            <p className="muted small">Searches new areas of India's biggest cities every night, 12:30–5 AM, and tells you in the morning.</p>
          </div>
          <button type="button" role="switch" aria-checked={form.exploreEnabled} aria-label="Night explorer"
            className={`switch ${form.exploreEnabled ? "on" : ""}`} onClick={toggleExplorer} disabled={busy === "explore"}>
            <span />
          </button>
        </div>
        <div className={`explore-row ${form.exploreEnabled ? "" : "is-off"}`}>
          <div className="field">
            <label htmlFor="areas-night">Areas a night</label>
            <select id="areas-night" className="input" value={form.areasPerNight}
              onChange={(e) => setForm({ ...form, areasPerNight: Number(e.target.value) })}>
              {Array.from({ length: view.maxAreasPerNight }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
          <p className="muted small">
            About {searchesPerNight.toLocaleString()} map searches a night at most, of the 2,500 free each day.
            {view.tonight.areas > 0 && <> Last night: {view.tonight.areas} areas, {view.tonight.added} new businesses with an email.</>}
          </p>
        </div>
      </div>

      {error && <p className="error" role="alert">{error}</p>}
      <div className="settings-actions">
        <button className="btn" type="button" disabled={!changed || !!busy} onClick={() => { setForm(view.settings); setError(""); }}>Undo changes</button>
        <button className="btn primary" type="button" disabled={!changed || !!busy || form.categories.length === 0}
          onClick={() => act("save", () => saveFinding({ categories: form.categories, areasPerNight: form.areasPerNight }))}>
          {busy === "save" ? "Saving…" : "Save"}
        </button>
      </div>

      <div className="settings-sub">
        <h3>City queue</h3>
        <p className="muted small">The explorer works down this list. Move a city to the front, skip one, or add a new one.</p>
        <form className="add-city" onSubmit={addCity}>
          <input className="input" placeholder="Add a city, e.g. Warangal" value={newCity} onChange={(e) => setNewCity(e.target.value)} aria-label="City to add" />
          <button className="btn" type="submit" disabled={!newCity.trim() || !!busy}>{busy === "add" ? "Adding…" : "Add and put first"}</button>
        </form>
        {note && <p className="saved-note">{note}</p>}
        <ol className="city-queue">
          {view.queue.map((c, i) => {
            const pct = c.areas ? Math.round((c.areasDone / c.areas) * 100) : 0;
            return (
              <li key={c.id} className={c.skipped ? "skipped" : ""}>
                <span className="q-num">{i + 1}</span>
                <div className="q-main">
                  <div className="q-name">{c.city}{c.skipped && <span className="cat-tag muted-tag">Skipped</span>}</div>
                  <div className="muted small">
                    {!c.areasListed ? "Areas get listed when the explorer reaches it"
                      : c.areasDone === c.areas ? `All ${c.areas} areas searched`
                      : `${c.areasDone} of ${c.areas} areas fully searched${c.next ? ` · next: ${c.next}` : ""}`}
                  </div>
                  {c.areasListed && <div className="q-bar"><span style={{ width: `${pct}%` }} /></div>}
                </div>
                <div className="q-actions">
                  {!c.skipped && i > 0 && (
                    <button className="btn small-btn" disabled={!!busy} onClick={() => act(`front-${c.id}`, () => prioritiseCity(c.city), true)}>Move to front</button>
                  )}
                  <button className="btn small-btn" disabled={!!busy} onClick={() => act(`skip-${c.id}`, () => skipCity(c.id, !c.skipped), true)}>
                    {c.skipped ? "Include" : "Skip"}
                  </button>
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}
