import { useCallback, useEffect, useMemo, useState } from "react";
import { errorText } from "../lib/api";
import Icon, { type IconName } from "../components/Icon";
import CandleChart from "./CandleChart";
import LiveCard from "./LiveCard";
import { getDay, getLab, loaded, refreshLab, startLab, type DayReplay, type LabView, type MarketKey, type Rules } from "./api";
import { money, price, shortDate, signed, tone } from "./format";
import "./tradinglab.css";

type Started = Extract<LabView, { started: true }>;
const MARKET_ORDER: MarketKey[] = ["IN", "US"];

/** Trading Lab: Jarvis day-trades 10 stocks with 1,000 each of pretend money, for learning. No real orders. */
export default function TradingLab() {
  const [lab, setLab] = useState<LabView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => getLab().then(setLab).catch((e) => setError(errorText(e, "Couldn't load the Trading Lab. Try again in a minute."))), []);
  useEffect(() => { load(); }, [load]);
  // while the server replays sessions, check back every few seconds
  useEffect(() => {
    if (!lab?.busy) return;
    const t = setTimeout(load, 3000);
    return () => clearTimeout(t);
  }, [lab, load]);

  const act = async (fn: () => Promise<LabView>, fallback: string) => {
    setBusy(true);
    setError("");
    try { setLab(await fn()); } catch (e) { setError(errorText(e, fallback)); } finally { setBusy(false); }
  };

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1 className="title">Trading Lab</h1>
          <p className="muted sub">
            Jarvis day-trades 10 stocks with 1,000 each of pretend money (₹ for India, $ for the US) and shows every buy and sell on the candles. For learning; no real orders.
          </p>
        </div>
        {lab?.started && (
          <div className="tl-head-actions">
            <span className="pill tl-paper">Paper money</span>
            <button className="btn" disabled={busy || lab.busy} onClick={() => act(refreshLab, "Couldn't check for new days.")}>
              {lab.busy ? "Replaying…" : "Check for new days"}
            </button>
          </div>
        )}
      </header>

      {error && <div className="banner" role="alert"><Icon name="alert" /><strong>{error}</strong></div>}
      {lab?.error && <div className="banner" role="alert"><Icon name="alert" /><div><strong>The last replay stopped early.</strong><div className="small">{lab.error}</div></div></div>}
      {lab && !lab.configured && (
        <div className="banner" role="alert">
          <Icon name="alert" />
          <div>
            <strong>No price data source is set up.</strong>
            <div className="small">Add <code>INTRADAY_1MIN_URL</code> and <code>INTRADAY_1MIN_API</code> in Render → Environment.</div>
          </div>
        </div>
      )}
      {!lab && !error && <div className="card"><p className="empty">Loading the Trading Lab…</p></div>}

      {lab && !lab.started && (
        <section className="card">
          <div className="card-head"><h2>Start the lab</h2></div>
          <Stocks lab={lab} />
          <RulesList rules={lab.rules} />
          <StartForm label="Start" defaultDate={lab.defaultStart} minDate={lab.minStart} busy={busy} onStart={(d) => act(() => startLab(d), "Couldn't start the lab.")}
            note="Jarvis replays every finished session since this date, minute by minute as if live, then adds each new session every morning." />
        </section>
      )}

      {lab?.started && <Running lab={lab} busy={busy} onRestart={(d) => act(() => startLab(d), "Couldn't start over.")} />}
    </div>
  );
}

function Running({ lab, busy, onRestart }: { lab: Started; busy: boolean; onRestart: (d: string) => void }) {
  const { config, days, markets } = lab;
  const pot = config.potPerStock;
  const newest = days.length ? days[days.length - 1].date : null;
  const [picked, setPicked] = useState<string | null>(null);
  const [symbol, setSymbol] = useState<string | null>(null);   // kept when the day changes
  const [pickNote, setPickNote] = useState("");
  const pick = (d: string, note = "") => { setPicked(d); setPickNote(note); };
  const date = picked ?? newest;

  const perStock = useMemo(() => {
    const out: Record<string, { pnl: number; withdrawn: number; trades: number; wins: number }> = {};
    for (const d of days) for (const [s, r] of Object.entries(d.stocks)) {
      const t = (out[s] ??= { pnl: 0, withdrawn: 0, trades: 0, wins: 0 });
      t.pnl += r.pnl; t.withdrawn += r.withdrawn; t.trades += r.traded ? 1 : 0; t.wins += r.pnl > 0 ? 1 : 0;
    }
    return out;
  }, [days]);

  const totalTrades = MARKET_ORDER.reduce((n, k) => n + config.totals[k].trades, 0);
  const totalWins = MARKET_ORDER.reduce((n, k) => n + config.totals[k].wins, 0);

  return (
    <>
      <p className="muted small tl-asof">
        Started {shortDate(config.startDate)} ·{" "}
        {MARKET_ORDER.map((k) => `${markets[k].name}: ${config.progress[k] ? `replayed to ${shortDate(config.progress[k]!)}` : "nothing finished yet"}`).join(" · ")}
        {lab.busy && " · replaying now…"}
        {` · ${lab.priceCallsToday} price request${lab.priceCallsToday === 1 ? "" : "s"} today`}
      </p>

      <section className="kpis" aria-label="Lab totals">
        {MARKET_ORDER.map((k) => {
          const m = markets[k], t = config.totals[k];
          const pots = Object.values(config.pots[k]).reduce((a, b) => a + b, 0);
          const start = pot * m.stocks.length;
          return (
            <Kpi key={k} icon="chart" label={m.name} value={money(pots + t.withdrawn, m.currency)} accent={k === "IN"}
              note={<><span className={tone(t.pnl)}>{signed(t.pnl, m.currency)} ({signed((t.pnl / start) * 100, "%")})</span> on {money(start, m.currency, 0)}</>} />
          );
        })}
        <Kpi icon="check" label="Profit withdrawn" value={MARKET_ORDER.map((k) => money(config.totals[k].withdrawn, markets[k].currency)).join(" · ")}
          note="Taken out after each winning trade" />
        <Kpi icon="bolt" label="Trades" value={String(totalTrades)}
          note={totalTrades ? `${totalWins} won (${Math.round((totalWins / totalTrades) * 100)}%) over ${days.length} day${days.length === 1 ? "" : "s"}` : "None yet"} />
      </section>

      <LiveCard lab={lab} />

      {days.length === 0 ? (
        <section className="card">
          <p className="empty">{lab.busy ? "Replaying the first sessions… this takes a few seconds per day." : `No finished sessions since ${shortDate(config.startDate)} yet. Check back after the next market day.`}</p>
        </section>
      ) : (
        <DayCard key={date!} days={days} date={date!} onPick={pick} note={pickNote} lab={lab} symbol={symbol} setSymbol={setSymbol} />
      )}

      <section className="card">
        <div className="card-head"><h2>Stocks</h2><span className="muted small">{money(pot, "INR", 0)} or {money(pot, "USD", 0)} each</span></div>
        <div className="tl-table-wrap">
          <table className="tl-table">
            <thead><tr><th>Stock</th><th>Market</th><th>Pot now</th><th>P&amp;L</th><th>Withdrawn</th><th>Trades</th><th>Won</th></tr></thead>
            <tbody>
              {MARKET_ORDER.flatMap((k) => markets[k].stocks.map((s) => {
                const t = perStock[s] ?? { pnl: 0, withdrawn: 0, trades: 0, wins: 0 }, cur = markets[k].currency;
                return (
                  <tr key={s}>
                    <td>{s}</td><td className="muted">{k === "IN" ? "NSE" : "US"}</td>
                    <td>{money(config.pots[k][s] ?? pot, cur)}</td>
                    <td className={tone(t.pnl)}>{signed(t.pnl, cur)}</td>
                    <td>{money(t.withdrawn, cur)}</td><td>{t.trades}</td><td>{t.wins}</td>
                  </tr>
                );
              }))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <div className="card-head"><h2>Daily profit and loss</h2><span className="muted small">Saved for each date</span></div>
        <div className="tl-table-wrap tl-scroll">
          <table className="tl-table">
            <thead><tr><th>Date</th>{MARKET_ORDER.map((k) => <th key={k} colSpan={2}>{markets[k].name}</th>)}</tr>
              <tr className="tl-subhead"><th />{MARKET_ORDER.map((k) => [<th key={`${k}d`}>Day</th>, <th key={`${k}t`}>Since start</th>])}</tr></thead>
            <tbody>
              {[...days].reverse().map((d) => (
                <tr key={d.date}>
                  <td>{shortDate(d.date)}</td>
                  {MARKET_ORDER.map((k) => {
                    const m = d.markets[k];
                    if (!m) return [<td key={`${k}d`} className="muted">closed</td>, <td key={`${k}t`} />];
                    return [
                      <td key={`${k}d`} className={tone(m.pnl)}>{signed(m.pnl, m.currency)} <span className="muted small">{m.trades}T/{m.wins}W</span></td>,
                      <td key={`${k}t`} className={tone(m.cumPnl)}>{signed(m.cumPnl, m.currency)}</td>,
                    ];
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <div className="card-head"><h2>The rules</h2></div>
        <RulesList rules={lab.rules} />
        <details className="tl-restart">
          <summary>Start over from another date</summary>
          <StartForm label="Start over" defaultDate={config.startDate} minDate={lab.minStart} busy={busy || lab.busy} onStart={onRestart}
            note="Clears the saved days and starts again with 1,000 per stock." />
        </details>
      </section>
    </>
  );
}

/** Days already opened this visit, so going back to one doesn't ask the server (or FMP) again. */
const opened = new Map<string, Promise<DayReplay>>();
function dayCache(date: string) {
  if (!opened.has(date)) opened.set(date, getDay(date).catch((e) => { opened.delete(date); throw e; }));
  return opened.get(date)!;
}

/** One day: pick a date and a stock, see its candles with the buy and sell, plus all 10 stocks' trades. */
function DayCard({ days, date, onPick, note, lab, symbol, setSymbol }: {
  days: Started["days"]; date: string; onPick: (d: string, note?: string) => void; note: string; lab: Started;
  symbol: string | null; setSymbol: (s: string | null | ((cur: string | null) => string | null)) => void;
}) {
  const [replay, setReplay] = useState<DayReplay | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    dayCache(date).then((r) => {
      setReplay(r);
      // open the first stock that traded, else the first one
      setSymbol((cur) => cur ?? (r.stocks.find((s) => loaded(s) && s.trade) ?? r.stocks[0])?.symbol ?? null);
    }).catch((e) => setError(errorText(e, "Couldn't load that day.")));
  }, [date]);

  const dates = days.map((d) => d.date);   // oldest first
  const at = dates.indexOf(date);
  // a weekend or holiday picked on the calendar shows the trading day before it (or the first one)
  const pickDate = (d: string) => {
    if (dates.includes(d)) return onPick(d);
    const before = dates.filter((x) => x < d).pop() ?? dates[0];
    onPick(before, `No session on ${shortDate(d)} (weekend, holiday or not replayed), so this shows ${shortDate(before)}.`);
  };
  const sel = replay?.stocks.find((s) => s.symbol === symbol);
  const rec = days.find((d) => d.date === date);

  return (
    <section className="card">
      <div className="card-head tl-day-head">
        <h2>Day replay</h2>
        <div className="tl-pickers">
          <div className="tl-pick">
            <div className="tl-date">
              <button className="icon-btn tl-step" disabled={at <= 0} onClick={() => onPick(dates[at - 1])} aria-label="Previous trading day">‹</button>
              <input className="input" type="date" aria-label="Day" value={date} min={dates[0]} max={dates[dates.length - 1]} required
                onChange={(e) => e.target.value && pickDate(e.target.value)} />
              <button className="icon-btn tl-step" disabled={at >= dates.length - 1} onClick={() => onPick(dates[at + 1])} aria-label="Next trading day">›</button>
            </div>
          </div>
          <div className="tl-pick">
            <select className="input" aria-label="Stock" value={symbol ?? ""} onChange={(e) => setSymbol(e.target.value)} disabled={!replay}>
              {(Object.keys(lab.markets) as MarketKey[]).map((k) => (
                <optgroup key={k} label={lab.markets[k].name}>
                  {lab.markets[k].stocks.map((s) => {
                    const r = rec?.stocks[s];
                    const result = !r ? "no session" : r.traded ? signed(r.pnl, lab.markets[k].currency) : "no trade";
                    return <option key={s} value={s} disabled={!r}>{s} · {result}</option>;
                  })}
                </optgroup>
              ))}
            </select>
          </div>
        </div>
      </div>
      <p className="muted small tl-note">Times are the exchange's own (IST for NSE, New York time for US)</p>
      {note && <p className="muted small tl-note">{note}</p>}

      {error && <p className="error">{error}</p>}
      {!replay && !error && <p className="empty tl-pad">Replaying {shortDate(date)}…</p>}
      {replay && (
        <>

          {sel && (!loaded(sel) ? <p className="error">{sel.symbol}: {sel.error}</p> : (
            <div className="tl-day">
              <CandleChart candles={sel.candles} range={sel.range} trade={sel.trade} currency={sel.currency} symbol={sel.symbol} />
              {sel.trade ? (
                <dl className="tl-facts">
                  <div><dt>Bought</dt><dd>{sel.trade.buyTime} at {price(sel.trade.buyPrice)}<span className="muted small">{sel.trade.qty} shares for {money(sel.potStart, sel.currency)}</span></dd></div>
                  <div><dt>Why</dt><dd className="muted">{sel.trade.reason}</dd></div>
                  <div><dt>Sold</dt><dd>{sel.trade.sellTime} at {price(sel.trade.sellPrice ?? 0)}<span className="muted small">{sel.trade.exit}</span></dd></div>
                  <div><dt>Result</dt><dd className={tone(sel.trade.pnl)}>{signed(sel.trade.pnl, sel.currency)} ({signed(sel.trade.pnlPct, "%")})<span className="muted small">after {money(sel.trade.charges, sel.currency)} charges · best price {price(sel.trade.best)}</span></dd></div>
                </dl>
              ) : <p className="muted tl-pad">{sel.note}.</p>}
            </div>
          ))}

          <div className="tl-table-wrap">
            <table className="tl-table">
              <thead><tr><th>Stock</th><th>Bought</th><th>Sold</th><th>Why it sold</th><th>Result</th></tr></thead>
              <tbody>
                {replay.stocks.map((s) => !loaded(s) ? (
                  <tr key={s.symbol}><td>{s.symbol}</td><td colSpan={4} className="muted">{s.error}</td></tr>
                ) : (
                  <tr key={s.symbol} className={s.symbol === symbol ? "tl-row-on" : ""} onClick={() => setSymbol(s.symbol)}>
                    <td>{s.symbol}</td>
                    {s.trade ? (
                      <>
                        <td>{s.trade.buyTime} · {price(s.trade.buyPrice)}</td>
                        <td>{s.trade.sellTime ?? "holding"}{s.trade.sellPrice !== null && ` · ${price(s.trade.sellPrice)}`}</td>
                        <td className="muted tl-wrap">{s.trade.exit}</td>
                        <td className={tone(s.pnl)}>{signed(s.pnl, s.currency)}</td>
                      </>
                    ) : <td colSpan={4} className="muted tl-wrap">{s.note}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

function Stocks({ lab }: { lab: LabView }) {
  return (
    <div className="tl-stocklist">
      {MARKET_ORDER.map((k) => (
        <div key={k}>
          <span className="muted small">{lab.markets[k].name} · {money(lab.rules.pot, lab.markets[k].currency, 0)} each · {lab.markets[k].open}–{lab.markets[k].close}</span>
          <div>{lab.markets[k].stocks.join(", ")}</div>
        </div>
      ))}
    </div>
  );
}

function RulesList({ rules }: { rules: Rules }) {
  const items = [
    ["Watch", `the first ${rules.range_minutes} minutes of the session. Their high and low are the opening range.`],
    ["Buy", `at the next minute's open once a minute closes above the range high. One trade per stock per day; no new buys in the last ${rules.no_entry_last_minutes} minutes.`],
    ["Stop", `the range low, but never more than ${rules.max_stop_pct}% under the buy price.`],
    ["Lock profit", `once up ${rules.trail_after_pct}%, a trailing stop follows the best price ${rules.trail_pct}% behind it and sells on a pullback.`],
    ["Close", `anything still held is sold ${rules.exit_before_close_minutes} minutes before the close. Nothing is held overnight.`],
    ["Money", `each stock has its own pot of ${rules.pot.toLocaleString()} in its currency. Profit is withdrawn after a win; a loss shrinks the pot.${rules.charges ? " Broker charges and taxes are taken." : ""}`],
  ];
  return <dl className="tl-rules">{items.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}</dl>;
}

function StartForm({ label, defaultDate, minDate, busy, onStart, note }: { label: string; defaultDate: string; minDate: string; busy: boolean; onStart: (d: string) => void; note: string }) {
  const [date, setDate] = useState(defaultDate < minDate ? minDate : defaultDate);
  const today = new Date().toISOString().slice(0, 10);
  return (
    <form className="tl-form" onSubmit={(e) => { e.preventDefault(); onStart(date); }}>
      <label className="field">
        <span className="muted small">Start date (last 30 days)</span>
        <input className="input" type="date" value={date} min={minDate} max={today} required onChange={(e) => setDate(e.target.value)} />
      </label>
      <button className="btn primary" disabled={busy || !date}>{busy ? "Working…" : label}</button>
      <p className="muted small hint">{note}</p>
    </form>
  );
}

function Kpi({ icon, label, value, note, accent }: { icon: IconName; label: string; value: string; note: React.ReactNode; accent?: boolean }) {
  return (
    <div className={`card kpi ${accent ? "kpi-accent" : ""}`}>
      <div className="kpi-top">
        <span className="muted">{label}</span>
        <span className="kpi-icon"><Icon name={icon} size={18} /></span>
      </div>
      <span className="kpi-value tl-kpi">{value}</span>
      <span className="muted small">{note}</span>
    </div>
  );
}
