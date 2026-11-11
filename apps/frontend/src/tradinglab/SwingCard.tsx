import type { Extras } from "./api";
import { money, shortDate, signed, tone } from "./format";

/** The lab's US swing strategy: positions held for days, checked once a day after the US close. */
export default function SwingCard({ extras }: { extras: Extras | null }) {
  if (!extras) return null;
  if ("error" in extras && extras.error) {
    return <section className="card"><div className="card-head"><h2>US swing</h2></div><p className="empty">{extras.error}</p></section>;
  }
  const sw = extras.swing!;
  const hold = extras.hold?.US;
  return (
    <section className="card">
      <div className="card-head">
        <h2>US swing <span className="muted small">held for days · paper money</span></h2>
        <span className="muted small">Updated after each US close · prices up to {shortDate(sw.asOf)}</span>
      </div>
      <p className="muted small tl-note">{sw.about}</p>

      <div className="stat-row tl-swing-stats">
        <div className="stat"><span className="muted small">Total</span><span className={`stat-value ${tone(sw.total)}`}>{signed(sw.total, "USD")}</span></div>
        <div className="stat"><span className="muted small">Closed trades</span><span className="stat-value">{sw.trades}</span><span className="muted small">{sw.wins} won</span></div>
        <div className="stat">
          <span className="muted small">Buy and hold, same 5</span>
          <span className={`stat-value ${hold ? tone(hold.pnl) : ""}`}>{hold ? signed(hold.pnl, "USD") : "—"}</span>
          <span className="muted small">since {shortDate(sw.start)}</span>
        </div>
      </div>

      {sw.buyNext.length > 0 && (
        <p className="tl-pad"><span className="pill tl-st-watching">Next open</span> Buying {sw.buyNext.join(", ")}: closed above the 20-day high while SPY is up.</p>
      )}

      <h3 className="tl-sub">Holding</h3>
      {sw.held.length === 0 ? <p className="empty">Nothing held right now.</p> : (
        <ul className="list">
          {sw.held.map((h) => (
            <li key={h.symbol}>
              <div>
                <div className="list-title">{h.symbol}</div>
                <div className="muted small">Bought {shortDate(h.buy)} at {money(h.buyPrice, "USD")} · day {h.daysHeld} of 10 · target {money(h.target, "USD")} · stop {money(h.stop, "USD")}</div>
              </div>
              <div className="tl-num"><div>{money(h.last, "USD")}</div><div className={`small ${tone(h.pnl)}`}>{signed(h.pnl, "USD")}</div></div>
            </li>
          ))}
        </ul>
      )}

      <h3 className="tl-sub">Closed trades</h3>
      {sw.closed.length === 0 ? <p className="empty">None yet.</p> : (
        <div className="tl-table-wrap tl-scroll">
          <table className="tl-table">
            <thead><tr><th>Stock</th><th>Bought</th><th>Sold</th><th>Why</th><th>Result</th></tr></thead>
            <tbody>
              {sw.closed.map((t) => (
                <tr key={`${t.symbol}-${t.buy}`}>
                  <td>{t.symbol}</td>
                  <td>{shortDate(t.buy)} · {money(t.buyPrice, "USD")}</td>
                  <td>{shortDate(t.sell)} · {money(t.sellPrice, "USD")}</td>
                  <td className="muted">{t.why} · {t.days} day{t.days === 1 ? "" : "s"}</td>
                  <td className={tone(t.pnl)}>{signed(t.pnl, "USD")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
