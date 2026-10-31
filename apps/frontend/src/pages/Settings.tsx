import { useEffect, useMemo, useState } from "react";
import { errorText, getSending, saveSending, type SendingSettings, type SendingView } from "../lib/api";
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
    </div>
  );
}

function SendingSection() {
  const [view, setView] = useState<SendingView | null>(null);
  const [form, setForm] = useState<SendingSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getSending()
      .then((v) => {
        setView(v);
        setForm(v.settings);
      })
      .catch((e) => setError(errorText(e, "Couldn't load the settings. The server may be waking up; try again in a minute.")));
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
