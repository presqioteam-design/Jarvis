import { useEffect, useState } from "react";
import CandleChart from "./CandleChart";
import { getDay, getLive, loaded, type DayReplay, type LabView, type LiveState, type LiveView, type MarketKey } from "./api";
import { price, signed, tone } from "./format";

type Started = Extract<LabView, { started: true }>;
const LABEL: Record<LiveState, string> = { range: "Opening range", watching: "Watching", holding: "Holding", sold: "Sold", no_trade: "No trade" };
const REFRESH_MS = 60_000;

/**
 * What Jarvis is doing right now, while a market is open. Reads the last 5-minute check from the server
 * (no price request), and today's chart from the candles that check already fetched.
 */
export default function LiveCard({ lab }: { lab: Started }) {
  const [live, setLive] = useState<LiveView | null>(null);
  const [day, setDay] = useState<DayReplay | null>(null);
  const [symbol, setSymbol] = useState<string | null>(null);
  const anyOpen = live ? (Object.values(live.markets).some((m) => m.open)) : false;

  useEffect(() => {
    let stop = false;
    const load = () => getLive().then((v) => { if (!stop) setLive(v); }).catch(() => undefined);
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => { stop = true; clearInterval(t); };
  }, []);

  // today's chart: only while a market is open and has been checked today
  const openKey = live && (Object.keys(live.markets) as MarketKey[]).find((k) => live.markets[k].open && live.markets[k].state?.stocks);
  const today = openKey ? live!.markets[openKey].day : null;
  const checkedAt = openKey ? live!.markets[openKey].state?.checkedAt : undefined;
  useEffect(() => {
    if (!today) { setDay(null); return; }
    getDay(today).then((d) => {
      setDay(d);
      setSymbol((cur) => cur ?? d.stocks.find((s) => loaded(s) && s.trade)?.symbol ?? d.stocks[0]?.symbol ?? null);
    }).catch(() => setDay(null));
  }, [today, checkedAt]);   // a new 5-minute check brings new candles

  if (!live) return null;
  const sel = day?.stocks.find((s) => s.symbol === symbol);

  return (
    <section className="card">
      <div className="card-head">
        <h2>{anyOpen && <span className="tl-live-dot" aria-hidden="true" />}Live now</h2>
        <span className="muted small">Checked every 5 minutes while a market is open · paper money</span>
      </div>
      <div className="tl-live-markets small">
        {(Object.keys(live.markets) as MarketKey[]).map((k) => {
          const m = live.markets[k], st = m.state;
          return (
            <span key={k}>
              <strong>{lab.markets[k].name}:</strong>{" "}
              {m.open
                ? st?.holiday ? "closed today (holiday)" : st?.stopped ? `paused: ${st.stopped}` : st?.checkedAt ? `open · last checked ${st.checkedAt}` : "open · first check within 5 minutes"
                : <span className="muted">closed · opens {m.nextOpen} (exchange time)</span>}
            </span>
          );
        })}
      </div>

      {!anyOpen && <p className="empty">Both markets are closed, so Jarvis isn't checking prices. Today's results are saved right after each close; pick a day below to see them.</p>}

      {(Object.keys(live.markets) as MarketKey[]).filter((k) => live.markets[k].open && live.markets[k].state?.stocks).map((k) => {
        const cur = lab.markets[k].currency, stocks = live.markets[k].state!.stocks;
        return (
          <div key={k} className="tl-live-grid">
            {lab.markets[k].stocks.map((s) => {
              const r = stocks[s];
              if (!r) return null;
              return (
                <button key={s} className={`tl-live-stock ${s === symbol ? "on" : ""}`} onClick={() => setSymbol(s)} aria-pressed={s === symbol}>
                  <span className="tl-live-top"><strong>{s}</strong><span className={`pill tl-st-${r.state}`}>{LABEL[r.state]}</span></span>
                  <span className="small">{r.price !== null ? price(r.price) : "—"} <span className="muted">at {r.time ?? "—"}</span></span>
                  {r.trade
                    ? <span className={`small ${tone(r.pnl)}`}>{signed(r.pnl, cur)} {r.state === "holding" ? "so far" : ""}</span>
                    : <span className="small muted">{r.state === "range" ? "setting the range" : r.state === "watching" ? "waiting for a breakout" : "no breakout today"}</span>}
                </button>
              );
            })}
          </div>
        );
      })}

      {sel && loaded(sel) && (
        <>
          <CandleChart candles={sel.candles} range={sel.range} trade={sel.trade} currency={sel.currency} symbol={sel.symbol} />
          <p className="muted small tl-pad">{sel.symbol}: {sel.note}.{sel.trade?.open ? ` Bought ${sel.trade.buyTime} at ${price(sel.trade.buyPrice)}; now ${price(sel.trade.last ?? 0)}.` : ""}</p>
        </>
      )}
    </section>
  );
}
