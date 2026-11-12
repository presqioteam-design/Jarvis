import type { BarsChart, Display, LineChart, Tone } from "../lib/display";

/** The board Jarvis's character holds up during a call: stat tiles, charts and a short list. */
export default function Presentation({ display }: { display: Display }) {
  const { stats = [], charts = [], rows } = display;
  return (
    <div className="pres">
      <div className="pres-head">
        <h3>{display.title}</h3>
        {display.subtitle && <span>{display.subtitle}</span>}
      </div>
      {stats.length > 0 && (
        <div className="pres-stats">
          {stats.map((s, i) => (
            <div key={i} className={`pres-stat ${tone(s.tone)}`} style={{ animationDelay: `${i * 70}ms` }}>
              <span className="pres-stat-label">{s.label}</span>
              <strong>{s.value}</strong>
              {s.note && <span className="pres-stat-note">{s.note}</span>}
            </div>
          ))}
        </div>
      )}
      {charts.map((c, i) => (c.type === "bars" ? <Bars key={i} chart={c} /> : <Line key={i} chart={c} />))}
      {rows && rows.items.length > 0 && (
        <div className="pres-rows">
          {rows.title && <h4>{rows.title}</h4>}
          {rows.items.map((r, i) => (
            <div key={i} className="pres-row">
              <span className="pres-row-label">{r.label}</span>
              {r.detail && <span className="pres-row-detail">{r.detail}</span>}
              {r.value && <span className={`pres-row-value ${tone(r.tone)}`}>{r.value}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const tone = (t: Tone) => (t === "up" ? "up" : t === "down" ? "down" : "");

const W = 520;

function Bars({ chart }: { chart: BarsChart }) {
  const items = chart.items;
  const signed = items.some((d) => d.value < 0);
  const max = Math.max(1e-9, ...items.map((d) => Math.abs(d.value)));
  const H = 120, top = 16, bottom = 22;
  const zero = signed ? top + (H - top - bottom) / 2 : H - bottom;
  const span = signed ? (H - top - bottom) / 2 : H - top - bottom;
  const step = W / items.length;
  const bw = Math.min(34, step * 0.62);
  return (
    <figure className="pres-chart">
      <figcaption>{chart.title}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={chart.title}>
        <line x1={0} x2={W} y1={zero} y2={zero} className="pres-axis" />
        {items.map((d, i) => {
          const h = Math.max(1.5, (Math.abs(d.value) / max) * span);
          const x = i * step + (step - bw) / 2;
          const y = d.value >= 0 ? zero - h : zero;
          return (
            <g key={i} className={signed ? (d.value >= 0 ? "up" : "down") : "neutral"}>
              <rect x={x} y={y} width={bw} height={h} rx={3} style={{ animationDelay: `${i * 40}ms` }}>
                <title>{`${d.label}: ${d.text}`}</title>
              </rect>
              {items.length <= 8 && <text x={x + bw / 2} y={d.value >= 0 ? y - 4 : y + h + 11} className="pres-val">{d.text}</text>}
              <text x={x + bw / 2} y={H - 6} className="pres-tick">{d.label}</text>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}

function Line({ chart }: { chart: LineChart }) {
  const pts = chart.points;
  if (pts.length < 2) return null;
  const H = 170, pad = { l: 6, r: 52, t: 14, b: 20 };
  const prices = pts.map((p) => p[1]).concat(chart.band ?? []);
  const lo = Math.min(...prices), hi = Math.max(...prices);
  const x = (i: number) => pad.l + (i / (pts.length - 1)) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - (v - lo) / (hi - lo || 1)) * (H - pad.t - pad.b);
  const path = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[1]).toFixed(1)}`).join("");
  const ticks = [0, Math.floor(pts.length / 2), pts.length - 1];
  return (
    <figure className="pres-chart">
      <figcaption>{chart.title}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={chart.title}>
        {chart.band && (
          <rect x={pad.l} width={W - pad.l - pad.r} y={y(chart.band[1])} height={Math.max(1, y(chart.band[0]) - y(chart.band[1]))} className="pres-band">
            <title>Opening range</title>
          </rect>
        )}
        <path d={`${path}L${x(pts.length - 1)},${H - pad.b}L${x(0)},${H - pad.b}Z`} className="pres-area" />
        <path d={path} className="pres-line" pathLength={1} />
        {chart.marks.map((m, i) => {
          const p = pts[Math.min(m.at, pts.length - 1)];
          return (
            <g key={i} className={`pres-mark ${m.kind}`}>
              <circle cx={x(m.at)} cy={y(p[1])} r={4.5} />
              <text x={x(m.at)} y={m.kind === "buy" ? y(p[1]) - 10 : y(p[1]) + 18} textAnchor={m.at > pts.length * 0.75 ? "end" : "middle"}>{m.label}</text>
            </g>
          );
        })}
        <text x={W - pad.r + 6} y={pad.t + 4} className="pres-tick start">{hi.toFixed(2)}</text>
        <text x={W - pad.r + 6} y={H - pad.b} className="pres-tick start">{lo.toFixed(2)}</text>
        {ticks.map((i) => <text key={i} x={x(i)} y={H - 5} className="pres-tick">{pts[i][0]}</text>)}
      </svg>
    </figure>
  );
}
