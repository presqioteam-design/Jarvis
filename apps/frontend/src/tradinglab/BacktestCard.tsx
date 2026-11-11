import { useEffect, useState } from "react";
import { call } from "../lib/api";
import type { LabView, MarketKey } from "./api";
import { signed, tone } from "./format";

type Score = { trades: number; wins: number; winRate: number; pnl: number; pnlPct: number; avgWin: number; avgLoss: number;
  profitFactor: number | null; worstDay: number; maxDrawdown: number; days: number };
type Variant = { key: string; name: string; about: string;
  markets: Record<MarketKey, { first: Score; last: Score; all: Score; beatsCurrentInBoth: boolean }> };
type Result = { from: string; to: string; ranAt: string; split: Record<MarketKey, { first: string; last: string }>;
  sessions: Record<MarketKey, number>; variants: Variant[]; best: Record<MarketKey, string> };

type Started = Extract<LabView, { started: true }>;

/** The strategy tester's comparison (run on the laptop, published to the lab): which smarter rules did best. */
export default function BacktestCard({ lab }: { lab: Started }) {
  const [res, setRes] = useState<Result | null | undefined>(undefined);
  const [market, setMarket] = useState<MarketKey>("IN");
  useEffect(() => { call<{ result: Result | null }>("/tradinglab/backtest").then((r) => setRes(r.result)).catch(() => setRes(null)); }, []);
  if (res === undefined) return null;

  return (
    <section className="card">
      <div className="card-head">
        <h2>Strategy test</h2>
        {res && <span className="muted small">{res.from} to {res.to} · fixed 1,000 a trade · after charges</span>}
      </div>
      {!res ? (
        <p className="empty">
          Not run yet. On the laptop: <code>cd apps/api && PYTHONPATH=../.. .venv/bin/python -m tradinglab.backtest --download --publish</code>
        </p>
      ) : (
        <>
          <div className="tl-test-head">
            <div className="tl-seg" role="group" aria-label="Market">
              {(Object.keys(lab.markets) as MarketKey[]).map((k) => (
                <button key={k} className={market === k ? "on" : ""} aria-pressed={market === k} onClick={() => setMarket(k)}>{lab.markets[k].name}</button>
              ))}
            </div>
            <p className="muted small">
              {res.sessions[market]} sessions. Each idea is scored on two parts of the period: an idea that beats the current rules in <b>both</b> (✓) is
              more likely to be real than one that only wins overall.
            </p>
          </div>
          <div className="tl-table-wrap">
            <table className="tl-table">
              <thead>
                <tr><th>Rules</th><th>{res.split[market]?.first}</th><th>{res.split[market]?.last}</th><th>Total</th><th>Trades</th><th>Won</th><th>Worst day</th><th>Better in both</th></tr>
              </thead>
              <tbody>
                {res.variants.map((v) => {
                  const m = v.markets[market], cur = lab.markets[market].currency;
                  return (
                    <tr key={v.key} className={v.key === res.best[market] ? "tl-row-on" : ""} title={v.about}>
                      <td><div>{v.name}{v.key === res.best[market] && <span className="pill tl-st-sold tl-best">best</span>}</div><div className="muted small tl-wrap">{v.about}</div></td>
                      <td className={tone(m.first.pnl)}>{signed(m.first.pnl, cur)}</td>
                      <td className={tone(m.last.pnl)}>{signed(m.last.pnl, cur)}</td>
                      <td className={tone(m.all.pnl)}><strong>{signed(m.all.pnl, cur)}</strong> <span className="muted small">({signed(m.all.pnlPct, "%")})</span></td>
                      <td>{m.all.trades}</td>
                      <td>{m.all.winRate.toFixed(0)}%</td>
                      <td className={tone(m.all.worstDay)}>{signed(m.all.worstDay, cur)}</td>
                      <td>{m.beatsCurrentInBoth ? "✓" : ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="muted small tl-pad">The live lab still uses the current rules. Results on the past don't promise future profit; a rule that keeps winning on new days is the real test.</p>
        </>
      )}
    </section>
  );
}
