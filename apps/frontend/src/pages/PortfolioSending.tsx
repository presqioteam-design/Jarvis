import { useEffect, useState } from "react";
import {
  errorText, portfolioSendNow, previewProspect, savePortfolioMe, savePortfolioSending,
  type PortfolioMe, type PortfolioSending, type PortfolioView, type Prospect, type ProspectEmail,
} from "../lib/api";
import { ampm, halfHours } from "../lib/format";
import Icon from "../components/Icon";

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** The portfolio mailbox: is it connected, when Jarvis sends, how many, and the signature. */
export function PortfolioSendingCard({ view, onChange }: { view: PortfolioView; onChange: (v: PortfolioView) => void }) {
  const [form, setForm] = useState<PortfolioSending>(view.sending);
  const [me, setMe] = useState<PortfolioMe>(view.me);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => setForm(view.sending), [view.sending]);
  useEffect(() => setMe(view.me), [view.me]);

  const { limits, mailbox } = view;
  const times = halfHours(limits.earliest, limits.latest);
  const changed = JSON.stringify(form) !== JSON.stringify(view.sending);
  const meChanged = JSON.stringify(me) !== JSON.stringify(view.me);
  const set = (patch: Partial<PortfolioSending>) => setForm((f) => ({ ...f, ...patch }));

  async function act(fn: () => Promise<PortfolioView | { note: string }>, fallback: string) {
    setBusy(true);
    setError("");
    setNote("");
    try {
      const r = await fn();
      if ("note" in r) setNote(r.note);
      else onChange(r);
    } catch (e) {
      setError(errorText(e, fallback));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card settings-card" aria-labelledby="pf-send-title">
      <div className="settings-head">
        <div>
          <h2 id="pf-send-title">Emailing them</h2>
          <p className="muted small">
            Sent from the outreach mailbox ({mailbox.address}) and signed by you, with your own email and phone in the text.
            Replies come back to that inbox and Jarvis tells you on Telegram. Only businesses you approve are emailed, and
            nobody gets both a Presqio and a portfolio email within 60 days.
          </p>
        </div>
        <button type="button" role="switch" aria-checked={view.sending.enabled} aria-label="Automatic portfolio emails"
          className={`switch ${view.sending.enabled ? "on" : ""}`} disabled={busy || !mailbox.connected}
          onClick={() => act(() => savePortfolioSending({ enabled: !view.sending.enabled }), "Couldn't switch automatic sending.")}>
          <span />
        </button>
      </div>

      {!mailbox.connected ? (
        <p className="error" role="status">The outreach mailbox isn't set up, so nothing can be sent. See Settings → Connections.</p>
      ) : (
        <p className="muted small">
          Today: {view.sentToday} of {view.sending.dailyCap} portfolio emails, {mailbox.sharedSentToday} of {mailbox.sharedCap} from
          the mailbox in all (Presqio included)
          {view.sending.enabled ? `. Automatic sending is on, ${ampm(view.sending.from)}–${ampm(view.sending.until)}.` : ". Automatic sending is off."}
          {view.busy && <> <span className="spinner" /> Sending now…</>}
        </p>
      )}

      <div className={`settings-grid ${form.enabled ? "" : "is-off"}`}>
        <div className="field">
          <label htmlFor="pf-per-run">Emails each run</label>
          <input id="pf-per-run" className="input" type="number" min={1} max={limits.maxPerRun} value={form.perRun}
            onChange={(e) => set({ perRun: Number(e.target.value) })} />
          <span className="muted small">Every 30 minutes, 1–{limits.maxPerRun}.</span>
        </div>
        <div className="field">
          <label htmlFor="pf-daily">Daily limit</label>
          <input id="pf-daily" className="input" type="number" min={1} max={limits.maxDaily} value={form.dailyCap}
            onChange={(e) => set({ dailyCap: Number(e.target.value) })} />
          <span className="muted small">Up to the mailbox's limit ({mailbox.sharedCap}), which Presqio's emails count toward too.</span>
        </div>
        <div className="field">
          <label htmlFor="pf-from">From</label>
          <select id="pf-from" className="input" value={form.from} onChange={(e) => set({ from: e.target.value })}>
            {times.slice(0, -1).map((t) => <option key={t} value={t}>{ampm(t)}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="pf-until">Until</label>
          <select id="pf-until" className="input" value={form.until} onChange={(e) => set({ until: e.target.value })}>
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
            Send two follow-ups ({form.followUpDays[0]} and {form.followUpDays[1]} days after the first email), as replies in the same thread
          </label>
        </div>
      </div>

      <div className="settings-actions">
        <button className="btn" type="button" disabled={busy || !mailbox.connected || view.busy}
          onClick={() => act(() => portfolioSendNow(view.sending.perRun), "Couldn't start sending.")}>
          <Icon name="send" size={16} /> Send {view.sending.perRun} now
        </button>
        <button className="btn" type="button" disabled={!changed || busy} onClick={() => { setForm(view.sending); setError(""); }}>Undo changes</button>
        <button className="btn primary" type="button" disabled={!changed || busy}
          onClick={() => act(() => savePortfolioSending(form), "Couldn't save. Check your connection and try again.")}>Save</button>
      </div>

      <div className="settings-sub">
        <h3>Signature</h3>
        <div className="settings-grid stack-on-phone">
          <div className="field">
            <label htmlFor="pf-name">Your name</label>
            <input id="pf-name" className="input" value={me.senderName} maxLength={60} onChange={(e) => setMe({ ...me, senderName: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="pf-phone">Phone (call or WhatsApp)</label>
            <input id="pf-phone" className="input" type="tel" value={me.phone} onChange={(e) => setMe({ ...me, phone: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="pf-email">Your email</label>
            <input id="pf-email" className="input" type="email" value={me.email} onChange={(e) => setMe({ ...me, email: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="pf-site">Portfolio website</label>
            <input id="pf-site" className="input" type="url" value={me.website} onChange={(e) => setMe({ ...me, website: e.target.value })} />
          </div>
        </div>
        {meChanged && (
          <div className="settings-actions">
            <button className="btn" type="button" onClick={() => setMe(view.me)} disabled={busy}>Undo changes</button>
            <button className="btn primary" type="button" disabled={busy}
              onClick={() => act(() => savePortfolioMe(me), "Couldn't save the signature.")}>Save signature</button>
          </div>
        )}
      </div>

      {error && <p className="error" role="alert">{error}</p>}
      {note && <p className="muted small" role="status">{note}</p>}
    </section>
  );
}

/** The three emails a business would get, in a dialog. */
export function ProspectPreview({ prospect, from, onClose }: { prospect: Prospect; from: string; onClose: () => void }) {
  const [emails, setEmails] = useState<ProspectEmail[] | null>(null);
  const [step, setStep] = useState(0);
  const [error, setError] = useState("");
  useEffect(() => {
    previewProspect(prospect.id).then((r) => setEmails(r.emails)).catch((e) => setError(errorText(e, "Couldn't load the preview.")));
  }, [prospect.id]);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  const mail = emails?.[step];
  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div className="dialog card" role="dialog" aria-modal="true" aria-labelledby="pv-title" onClick={(e) => e.stopPropagation()}>
        <div className="card-head">
          <h2 id="pv-title">Emails for {prospect.name}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="segmented email-tabs" role="tablist" aria-label="Which email">
          {["First email", "Follow-up 1", "Follow-up 2"].map((l, i) => (
            <button key={l} type="button" role="tab" aria-selected={step === i} className={step === i ? "active" : ""} onClick={() => setStep(i)}>{l}</button>
          ))}
        </div>
        {error ? <p className="error">{error}</p> : mail ? (
          <article className="email-preview" aria-live="polite">
            <dl>
              <dt>From</dt><dd>{from}</dd>
              <dt>To</dt><dd>{mail.to || "No email"}</dd>
              <dt>Subject</dt><dd><strong>{mail.subject}</strong></dd>
            </dl>
            <div className="email-body">{mail.body}</div>
          </article>
        ) : <p className="muted"><span className="spinner" /> Loading…</p>}
      </div>
    </div>
  );
}
