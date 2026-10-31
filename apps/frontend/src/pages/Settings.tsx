import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  blockAddress, errorText, getDnc, getUsage, getEmails, getFinding, getSending, previewEmails, prioritiseCity, saveEmails, saveFinding,
  saveSending, skipCity, unblockAddress,
  type DncView, type UsageView, type EmailPreview, type EmailSettings, type EmailsView, type FindingSettings, type FindingView,
  type SendingSettings, type SendingView,
} from "../lib/api";
import { categoryLabel } from "@jarvis/shared";
import { timeAgo } from "../lib/format";
import Icon, { type IconName } from "../components/Icon";

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

// one section at a time: only the open one loads, and the tab is kept in the address (?tab=)
const SECTIONS: { key: string; label: string; icon: IconName; Body: () => React.ReactElement }[] = [
  { key: "usage", label: "Usage", icon: "dashboard", Body: UsageSection },
  { key: "sending", label: "Sending", icon: "mail", Body: SendingSection },
  { key: "finding", label: "What to find", icon: "search", Body: FindingSection },
  { key: "emails", label: "Emails", icon: "chat", Body: EmailsSection },
  { key: "dnc", label: "Do not contact", icon: "ban", Body: DncSection },
];

export default function Settings() {
  const [params, setParams] = useSearchParams();
  const active = SECTIONS.find((t) => t.key === params.get("tab")) ?? SECTIONS[0];
  const Body = active.Body;
  const tabsRef = useRef<HTMLElement>(null);
  // on a phone the chosen tab may be off to the side: bring it into view
  useEffect(() => {
    tabsRef.current?.querySelector(".active")?.scrollIntoView({ block: "nearest", inline: "center" });
  }, [active.key]);
  return (
    <div className="page settings-page">
      <header className="settings-top">
        <div>
          <h1 className="title">Settings</h1>
          <p className="muted sub">Changes apply from Jarvis's next run, within 30 minutes. No redeploy needed.</p>
        </div>
        <nav className="settings-tabs" role="tablist" aria-label="Settings sections" ref={tabsRef}>
          {SECTIONS.map((t) => (
            <button key={t.key} type="button" role="tab" aria-selected={t.key === active.key}
              className={t.key === active.key ? "active" : ""} onClick={() => setParams(t.key === "usage" ? {} : { tab: t.key }, { replace: true })}>
              <Icon name={t.icon} size={16} />
              {t.label}
            </button>
          ))}
        </nav>
      </header>
      <div role="tabpanel" aria-label={active.label}>
        <Body key={active.key} />
      </div>
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

// ── section 3: emails ──────────────────────────────────────────────────────

let lastEmails: EmailsView | null = null;

function EmailsSection() {
  const [view, setViewState] = useState<EmailsView | null>(lastEmails);
  const [form, setForm] = useState<EmailSettings | null>(lastEmails?.settings ?? null);
  const [kind, setKind] = useState("hotels");
  const [sample, setSample] = useState({ name: "Sunrise Residency", area: "Madhapur" });
  const [step, setStep] = useState(0);
  const [preview, setPreview] = useState<EmailPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const setView = (v: EmailsView) => {
    lastEmails = v;
    setViewState(v);
  };

  useEffect(() => {
    const before = lastEmails;
    getEmails()
      .then((v) => {
        setView(v);
        setForm((f) => (!f || !before || JSON.stringify(f) === JSON.stringify(before.settings) ? v.settings : f));
      })
      .catch((e) => {
        if (!before) setError(errorText(e, "Couldn't load these settings. The server may be waking up; try again in a minute."));
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // the preview follows every edit, including unsaved sender details (after a short pause in typing)
  useEffect(() => {
    if (!form) return;
    let cancelled = false;
    const t = setTimeout(() => {
      previewEmails({ ...form, category: kind, name: sample.name, area: sample.area })
        .then((p) => !cancelled && setPreview(p))
        .catch(() => undefined);
    }, 350);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [form, kind, sample]);

  const changed = useMemo(() => !!form && !!view && JSON.stringify(form) !== JSON.stringify(view.settings), [form, view]);

  if (!form || !view) {
    return (
      <section className="card settings-card">
        <h2>Emails</h2>
        {error ? <p className="error" role="alert">{error}</p> : <p className="muted"><span className="spinner" /> Loading…</p>}
      </section>
    );
  }

  const set = (patch: Partial<EmailSettings>) => {
    setSaved(false);
    setForm({ ...form, ...patch });
  };

  async function save() {
    setBusy(true);
    setError("");
    try {
      const v = await saveEmails(form!);
      setView(v);
      setForm(v.settings);
      setSaved(true);
    } catch (e) {
      setError(errorText(e, "Couldn't save. Check your connection and try again."));
    } finally {
      setBusy(false);
    }
  }

  const mail = preview?.emails[step];

  return (
    <section className="card settings-card" aria-labelledby="emails-title">
      <div>
        <h2 id="emails-title">Emails</h2>
        <p className="muted small">
          Who the emails are from, and exactly what each kind of business receives. The wording is fixed (not written
          by AI) so every email is accurate; only the name, area and these details change.
        </p>
      </div>

      <div className="settings-grid stack-on-phone">
        <div className="field">
          <label htmlFor="sender">Sender name</label>
          <input id="sender" className="input" value={form.senderName} maxLength={60} onChange={(e) => set({ senderName: e.target.value })} />
          <span className="muted small">Shown as who the email is from, and in the signature.</span>
        </div>
        <div className="field">
          <label htmlFor="phone">Phone (call or WhatsApp)</label>
          <input id="phone" className="input" type="tel" value={form.phone} onChange={(e) => set({ phone: e.target.value })} />
          <span className="muted small">Also what Jarvis gives when asked about pricing.</span>
        </div>
        <div className="field">
          <label htmlFor="website">Website</label>
          <input id="website" className="input" type="url" value={form.website} onChange={(e) => set({ website: e.target.value })} />
          <span className="muted small">In the signature.</span>
        </div>
      </div>

      {error && <p className="error" role="alert">{error}</p>}
      <div className="settings-actions">
        {saved && !changed && <span className="saved"><Icon name="check" size={16} /> Saved</span>}
        <button className="btn" type="button" disabled={!changed || busy} onClick={() => { setForm(view.settings); setError(""); }}>Undo changes</button>
        <button className="btn primary" type="button" disabled={!changed || busy} onClick={save}>{busy ? "Saving…" : "Save"}</button>
      </div>

      <div className="settings-sub">
        <h3>Preview</h3>
        <div className="preview-controls">
          <div className="field">
            <label htmlFor="pv-kind">Kind of business</label>
            <select id="pv-kind" className="input" value={kind} onChange={(e) => setKind(e.target.value)}>
              {view.categories.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="pv-name">Business name</label>
            <input id="pv-name" className="input" value={sample.name} maxLength={80} onChange={(e) => setSample({ ...sample, name: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="pv-area">Area</label>
            <input id="pv-area" className="input" value={sample.area} maxLength={60} onChange={(e) => setSample({ ...sample, area: e.target.value })} />
          </div>
        </div>
        <div className="segmented email-tabs" role="tablist" aria-label="Which email">
          {["First email", "Follow-up 1", "Follow-up 2"].map((l, i) => (
            <button key={l} type="button" role="tab" aria-selected={step === i} className={step === i ? "active" : ""} onClick={() => setStep(i)}>{l}</button>
          ))}
        </div>
        {mail ? (
          <article className="email-preview" aria-live="polite">
            <dl>
              <dt>From</dt><dd>{preview!.from}</dd>
              <dt>Subject</dt><dd><strong>{mail.subject}</strong></dd>
            </dl>
            <div className="email-body">{mail.body}</div>
          </article>
        ) : (
          <p className="muted"><span className="spinner" /> Loading the preview…</p>
        )}
        <p className="muted small">Follow-ups go as replies in the same email thread, so the business sees them together.</p>
      </div>
    </section>
  );
}

// ── section 4: do-not-contact list ─────────────────────────────────────────

let lastDnc: DncView | null = null;

const REASON: Record<string, string> = {
  "asked to stop": "Asked us to stop",
  "blocked by admin": "Blocked by you",
  "added by admin": "Added by you",
};

/** "919876543210" -> "+91 98765 43210" (the list keeps phone numbers as digits) */
const showKey = (key: string, kind: string) =>
  kind === "phone" && /^91\d{10}$/.test(key) ? `+91 ${key.slice(2, 7)} ${key.slice(7)}` : key;

function DncSection() {
  const [view, setViewState] = useState<DncView | null>(lastDnc);
  const [tab, setTab] = useState<"blocked" | "bounced">("blocked");
  const [search, setSearch] = useState("");
  const [address, setAddress] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const setView = (v: DncView) => {
    lastDnc = v;
    setViewState(v);
  };

  useEffect(() => {
    getDnc()
      .then(setView)
      .catch((e) => !lastDnc && setError(errorText(e, "Couldn't load the list. The server may be waking up; try again in a minute.")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const q = search.trim().toLowerCase();
  const entries = useMemo(
    () => (view?.entries ?? []).filter((e) => !q || `${e.key} ${e.business} ${e.area}`.toLowerCase().includes(q)),
    [view, q],
  );
  const bounced = useMemo(
    () => (view?.bounced ?? []).filter((b) => !q || `${b.name} ${b.email} ${b.area}`.toLowerCase().includes(q)),
    [view, q],
  );

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setBusy("add");
    setError("");
    setNote("");
    try {
      setView(await blockAddress(address.trim()));
      setNote(`${address.trim().toLowerCase()} won't be emailed.`);
      setAddress("");
    } catch (err) {
      setError(errorText(err, "Couldn't add it. Check your connection and try again."));
    } finally {
      setBusy("");
    }
  }

  async function unblock(key: string, reason: string) {
    const ask = reason === "asked to stop"
      ? `${key} asked us to stop emailing. Emailing them again could get the Gmail account reported as spam. Unblock anyway?`
      : `Take ${key} off the list? Jarvis may email this business again.`;
    if (!confirm(ask)) return;
    setBusy(key);
    setError("");
    setNote("");
    try {
      const v = await unblockAddress(key);
      setView(v);
      setNote(v.restored ? `${key} is off the list; its business can be emailed again.` : `${key} is off the list.`);
    } catch (err) {
      setError(errorText(err, "Couldn't unblock it. Try again."));
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="card settings-card" aria-labelledby="dnc-title">
      <div>
        <h2 id="dnc-title">Do-not-contact list</h2>
        <p className="muted small">
          Jarvis never emails these addresses. Businesses get here when they reply “stop”, when you block them in Leads
          or on Telegram, or when you add an address below.
        </p>
      </div>

      <form className="add-city" onSubmit={add}>
        <input className="input" type="email" placeholder="Add an email, e.g. someone who asked on the phone" value={address}
          onChange={(e) => setAddress(e.target.value)} aria-label="Email to block" />
        <button className="btn" type="submit" disabled={!address.trim() || !!busy}>{busy === "add" ? "Adding…" : "Don't email"}</button>
      </form>
      {note && <p className="saved-note">{note}</p>}
      {error && <p className="error" role="alert">{error}</p>}

      {!view ? (
        <p className="muted"><span className="spinner" /> Loading…</p>
      ) : (
        <>
          <div className="dnc-bar">
            <div className="segmented" role="tablist" aria-label="Which list">
              <button type="button" role="tab" aria-selected={tab === "blocked"} className={tab === "blocked" ? "active" : ""} onClick={() => setTab("blocked")}>
                Blocked ({view.entries.length})
              </button>
              <button type="button" role="tab" aria-selected={tab === "bounced"} className={tab === "bounced" ? "active" : ""} onClick={() => setTab("bounced")}>
                Bounced ({view.bounced.length})
              </button>
            </div>
            <input className="input dnc-search" type="search" placeholder="Search address or business…" value={search}
              onChange={(e) => setSearch(e.target.value)} aria-label="Search the list" />
          </div>

          {tab === "blocked" ? (
            entries.length === 0 ? (
              <p className="empty">{q ? "Nothing matches." : "Nobody is blocked. Replies asking to stop are added here automatically."}</p>
            ) : (
              <ul className="dnc-list">
                {entries.map((e) => (
                  <li key={e.key}>
                    <div className="q-main">
                      <div className="q-name">{showKey(e.key, e.kind)}<span className="cat-tag muted-tag">{e.kind === "email" ? "Email" : "Phone"}</span></div>
                      <div className="muted small">
                        {[e.business, e.area].filter(Boolean).join(" · ") || "No business on file"} · {REASON[e.reason] ?? e.reason}
                        {e.createdAt && ` · ${timeAgo(e.createdAt)}`}
                      </div>
                    </div>
                    <button className="btn small-btn" disabled={!!busy} onClick={() => unblock(e.key, e.reason)}>
                      {busy === e.key ? "Removing…" : "Unblock"}
                    </button>
                  </li>
                ))}
              </ul>
            )
          ) : bounced.length === 0 ? (
            <p className="empty">{q ? "Nothing matches." : "No bounced emails."}</p>
          ) : (
            <>
              <p className="muted small">These addresses don't exist (the email came back). Jarvis doesn't email them again.</p>
              <ul className="dnc-list">
                {bounced.map((b) => (
                  <li key={b.id}>
                    <div className="q-main">
                      <div className="q-name">{b.name}<span className="cat-tag">{categoryLabel(b.category)}</span></div>
                      <div className="muted small">{b.email}{b.area && ` · ${b.area}`}{b.city && `, ${b.city}`}</div>
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </section>
  );
}

// ── usage today ────────────────────────────────────────────────────────────

let lastUsage: UsageView | null = null;

/** "in 5 h (12:00 AM)" */
function resetsIn(iso: string): string {
  const ms = new Date(iso).getTime() - Date.now();
  const at = new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", hour12: true });
  if (ms <= 0) return "now";
  const total = Math.round(ms / 60_000);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return `in ${h ? `${h} h ` : ""}${h < 3 ? `${m} min ` : ""}(${at})`.replace("  ", " ");
}

function Meter({ label, used, limit, resetsAt, note }: { label: string; used: number; limit: number; resetsAt: string; note?: string }) {
  const pct = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  const tone = pct >= 90 ? "bad" : pct >= 70 ? "warn" : "ok";
  return (
    <div className={`meter ${tone}`}>
      <div className="meter-top">
        <span>{label}</span>
        <span className="meter-num"><strong>{used.toLocaleString()}</strong> / {limit.toLocaleString()}</span>
      </div>
      <div className="meter-bar" role="progressbar" aria-label={label} aria-valuenow={used} aria-valuemin={0} aria-valuemax={limit}>
        <span style={{ width: `${pct}%` }} />
      </div>
      <div className="muted small">{pct >= 100 ? "Used up" : `${(limit - used).toLocaleString()} left`} · resets {resetsIn(resetsAt)}</div>
      {note && <div className="muted small meter-note">{note}</div>}
    </div>
  );
}

function UsageSection() {
  const [view, setViewState] = useState<UsageView | null>(lastUsage);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    getUsage()
      .then((v) => {
        lastUsage = v;
        setViewState(v);
        setError("");
      })
      .catch((e) => !lastUsage && setError(errorText(e, "Couldn't load usage. The server may be waking up; try again in a minute.")))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const db = view?.database;
  return (
    <section className="card settings-card" aria-labelledby="usage-title">
      <div className="settings-head">
        <div>
          <h2 id="usage-title">Usage today</h2>
          <p className="muted small">What's used of each daily allowance. When one runs out, that part of Jarvis waits until it resets.</p>
        </div>
        <button type="button" className="btn small-btn" onClick={load} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {!view ? (
        !error && <p className="muted"><span className="spinner" /> Loading…</p>
      ) : (
        <>
          <div className="meters">
            {view.meters.map(({ key, ...m }) => <Meter key={key} {...m} />)}
          </div>
          <div className="settings-sub">
            <h3>Database (Firestore's free allowance)</h3>
            {db && !db.error ? (
              <div className="meters">
                <Meter label="Reads" used={db.reads} limit={db.limits.reads} resetsAt={db.resetsAt} />
                <Meter label="Writes" used={db.writes} limit={db.limits.writes} resetsAt={db.resetsAt} />
                <Meter label="Deletes" used={db.deletes} limit={db.limits.deletes} resetsAt={db.resetsAt} />
              </div>
            ) : db?.error === "permission" ? (
              <div className="setup-steps">
                <p>Jarvis needs permission to read these numbers from Google Cloud (a one-time step):</p>
                <ol>
                  <li>
                    Open{" "}
                    <a href={`https://console.cloud.google.com/iam-admin/iam?project=${db.project}`} target="_blank" rel="noreferrer">
                      Google Cloud → IAM for {db.project}
                    </a>{" "}
                    (sign in with the Google account that owns the Firebase project).
                  </li>
                  <li>Click <strong>Grant access</strong>. In “New principals” paste: <code className="copy">{db.serviceAccount}</code></li>
                  <li>In “Role” pick <strong>Monitoring Viewer</strong>, then <strong>Save</strong>.</li>
                  <li>Wait a minute and press Refresh above.</li>
                </ol>
                <p className="muted small">It only lets Jarvis read usage numbers. Until then, Firebase console → Firestore → Usage shows them.</p>
              </div>
            ) : (
              <p className="muted small">The numbers aren't available right now. Firebase console → Firestore → Usage shows them. Resets {db ? resetsIn(db.resetsAt) : ""}.</p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
