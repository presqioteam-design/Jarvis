import { useEffect, useRef, useState } from "react";
import CandleChart from "./CandleChart";
import {
  checkLiveNow, getDay, getLive, loaded, refreshStock,
  type LabView, type LiveState, type LiveStock, type LiveView, type MarketKey, type StockReplay,
} from "./api";
import { price, signed, tone } from "./format";
import "./tradinglab.css";

type Started = Extract<LabView, { started: true }>;
const LABEL: Record<LiveState, string> = { range: "Opening range", watching: "Watching", holding: "Holding", sold: "Sold", no_trade: "No trade" };
const EVERY_S = 60;

/** True while the browser tab is on screen; hidden tabs don't refresh, so they cost nothing. */
function useVisible() {
  const [visible, setVisible] = useState(!document.hidden);
  useEffect(() => {
    const on = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", on);
    return () => document.removeEventListener("visibilitychange", on);
  }, []);
  return visible;
}

/**
 * What Jarvis is doing right now, while a market is open.
 * - The stock you're looking at refreshes every minute: one price request for that stock only.
 * - The other tiles come from the server's 5-minute checks (reading them costs no price request).
 * - Nothing refreshes while the tab is hidden or the markets are closed.
 */
export default function LiveCard({ lab }: { lab: Started }) {
  const visible = useVisible();
  const [live, setLive] = useState<LiveView | null>(null);
  const [stock, setStock] = useState<Extract<StockReplay, { candles: unknown }> | null>(null);
  const [symbol, setSymbol] = useState<string | null>(null);
  const [left, setLeft] = useState(EVERY_S);
  const [flash, setFlash] = useState<Record<string, "up" | "down">>({});
  const lastPrice = useRef<Record<string, number>>({});

  const openKey = live ? (Object.keys(live.markets) as MarketKey[]).find((k) => live.markets[k].open) : undefined;
  const openMarket = openKey ? live!.markets[openKey] : undefined;
  // a stock that has sold, or can't buy any more today, won't change: no refreshing it (the server wouldn't fetch it anyway)
  const selDone = !!(symbol && openMarket?.state?.stocks?.[symbol]?.done);

  // tiles flash green or red when a price moves
  const notePrices = (stocks: Record<string, LiveStock> | undefined) => {
    if (!stocks) return;
    const next: Record<string, "up" | "down"> = {};
    for (const [s, r] of Object.entries(stocks)) {
      const before = lastPrice.current[s];
      if (r.price !== null && before !== undefined && r.price !== before) next[s] = r.price > before ? "up" : "down";
      if (r.price !== null) lastPrice.current[s] = r.price;
    }
    if (Object.keys(next).length) {
      setFlash(next);
      setTimeout(() => setFlash({}), 1200);
    }
  };
  const takeLive = (v: LiveView) => {
    setLive(v);
    for (const m of Object.values(v.markets)) notePrices(m.state?.stocks);
  };

  // on opening: check now if a market is open and the last check is old, then pick a stock to show
  useEffect(() => {
    checkLiveNow().then((v) => {
      takeLive(v);
      const k = (Object.keys(v.markets) as MarketKey[]).find((m) => v.markets[m].open && v.markets[m].state?.stocks);
      const stocks = k ? v.markets[k].state!.stocks : {};
      setSymbol((cur) => cur ?? Object.keys(stocks).find((s) => stocks[s].trade && !stocks[s].done) ?? Object.keys(stocks)[0] ?? null);
    }).catch(() => getLive().then(takeLive).catch(() => undefined));
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  // the stock on screen: load now, then once a minute while visible and its market is open
  useEffect(() => {
    if (!symbol || !openMarket || selDone) return;
    let stop = false;
    const tick = () => {
      refreshStock(symbol).then((r) => {
        if (stop) return;
        if (r.stock && loaded(r.stock)) setStock(r.stock);
        if (r.tile && openKey) {
          setLive((v) => v && v.markets[openKey].state ? {
            markets: { ...v.markets, [openKey]: { ...v.markets[openKey], state: { ...v.markets[openKey].state!, stocks: { ...v.markets[openKey].state!.stocks, [symbol]: r.tile! } } } },
          } : v);
          notePrices({ [symbol]: r.tile });
        }
      }).catch(() => undefined);
      getLive().then((v) => { if (!stop) takeLive(v); }).catch(() => undefined);   // the other tiles (no price request)
      setLeft(EVERY_S);
    };
    if (stock?.symbol !== symbol) setStock(null);
    tick();
    if (!visible) return () => { stop = true; };
    const t = setInterval(tick, EVERY_S * 1000);
    const c = setInterval(() => setLeft((n) => Math.max(0, n - 1)), 1000);
    return () => { stop = true; clearInterval(t); clearInterval(c); };
  }, [symbol, visible, openKey, selDone]);   // eslint-disable-line react-hooks/exhaustive-deps

  // after the markets close: a slow look every 5 minutes is enough (the server saves the day itself)
  useEffect(() => {
    if (openMarket || !visible) return;
    const t = setInterval(() => getLive().then(takeLive).catch(() => undefined), 5 * 60_000);
    return () => clearInterval(t);
  }, [openMarket, visible]);   // eslint-disable-line react-hooks/exhaustive-deps

  // a stock picked before its first refresh: show what the last check has (no request)
  useEffect(() => {
    if (!symbol || stock || !openMarket) return;
    getDay(openMarket.day).then((d) => {
      const s = d.stocks.find((x) => x.symbol === symbol);
      if (s && loaded(s)) setStock((cur) => cur ?? s);
    }).catch(() => undefined);
  }, [symbol, stock, openMarket]);

  if (!live) return null;
  const anyOpen = !!openMarket;
  const sel = stock && stock.symbol === symbol ? stock : null;

  return (
    <section className="card">
      <div className="card-head">
        <h2>{anyOpen && <span className="tl-live-dot" aria-hidden="true" />}Live now</h2>
        <span className="muted small">
          {anyOpen
            ? selDone ? `${symbol} is finished for today · not updating · other stocks every 5 min`
              : visible ? `${symbol ?? "Chart"} updates in ${left}s · other stocks every 5 min` : "Paused while this tab is hidden"
            : "Paper money"}
        </span>
      </div>
      <div className="tl-live-markets small">
        {(Object.keys(live.markets) as MarketKey[]).map((k) => {
          const m = live.markets[k], st = m.state;
          return (
            <span key={k}>
              <strong>{lab.markets[k].name}:</strong>{" "}
              {m.open
                ? st?.holiday ? "closed today (holiday)" : st?.stopped ? `paused: ${st.stopped}` : st?.checkedAt ? `open · all stocks checked ${st.checkedAt}` : "open · first check within 5 minutes"
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
                <button key={s} className={`tl-live-stock ${s === symbol ? "on" : ""} ${flash[s] ? `tl-flash-${flash[s]}` : ""}`}
                  onClick={() => setSymbol(s)} aria-pressed={s === symbol}>
                  <span className="tl-live-top"><strong>{s}</strong><span className={`pill tl-st-${r.state}`}>{LABEL[r.state]}</span></span>
                  <span className="small tl-price">{r.price !== null ? price(r.price) : "—"} <span className="muted">at {r.time ?? "—"}</span></span>
                  {r.trade
                    ? <span className={`small ${tone(r.pnl)}`}>{signed(r.pnl, cur)} {r.state === "holding" ? "so far" : ""}</span>
                    : <span className="small muted">{r.state === "range" ? "setting the range" : r.state === "watching" ? "waiting for a breakout" : "no breakout today"}</span>}
                  {s === symbol && <span className="tl-live-tag">{r.done ? "finished for today" : "on screen · every minute"}</span>}
                </button>
              );
            })}
          </div>
        );
      })}

      {sel && (
        <>
          <CandleChart live candles={sel.candles} range={sel.range} trade={sel.trade} trades={sel.trades} currency={sel.currency} symbol={sel.symbol} />
          <p className="muted small tl-pad">
            {sel.symbol}: {sel.note}.{sel.trade?.open ? ` Bought ${sel.trade.buyTime} at ${price(sel.trade.buyPrice)}; now ${price(sel.trade.last ?? 0)}.` : ""}
          </p>
        </>
      )}
      {anyOpen && symbol && !sel && <p className="empty tl-pad">Loading {symbol}…</p>}
    </section>
  );
}
