import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Candle, Currency, Trade } from "./api";
import { money, price } from "./format";

const H = 440;
const VOL_H = 64, VOL_GAP = 12;   // the volume strip under the candles
const PAD = { top: 24, right: 68, bottom: 28, left: 8 };
const INTERVALS = [1, 5, 15] as const;
type Interval = (typeof INTERVALS)[number];
type View = { a: number; b: number };   // the visible window, in candle positions (a ≤ b)
const MIN_BARS = 8;

const minutes = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5));
const hhmm = (m: number) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;

/** 1-minute candles grouped into `every`-minute ones. */
function group(candles: Candle[], every: Interval): Candle[] {
  if (every === 1) return candles;
  const out: Candle[] = [];
  for (const c of candles) {
    const slot = hhmm(minutes(c.time) - (minutes(c.time) % every));
    const last = out[out.length - 1];
    if (last && last.time === slot) {
      last.high = Math.max(last.high, c.high); last.low = Math.min(last.low, c.low); last.close = c.close; last.volume += c.volume;
    } else out.push({ ...c, time: slot });
  }
  return out;
}

/**
 * One session as candles, with the opening range shaded and where Jarvis bought and sold.
 * Zoom: the + / − buttons, pinch or Ctrl/⌘ + scroll, double-click. Move: drag, or scroll sideways.
 * Every change of view eases into place, so it's easy to keep your eye on the candles.
 */
export default function CandleChart({ candles, range, trade, currency, symbol }: {
  candles: Candle[]; range: { high: number; low: number; until: string } | null; trade: Trade | null; currency: Currency; symbol: string;
}) {
  const [interval, setInterval_] = useState<Interval>(5);
  const bars = useMemo(() => group(candles.map((c) => ({ ...c })), interval), [candles, interval]);
  const n = bars.length;

  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [view, setView] = useState<View>({ a: 0, b: n });
  const viewRef = useRef(view);
  viewRef.current = view;
  const anim = useRef<number | null>(null);
  const settle = useRef<number | null>(null);   // lands on the target even if no animation frames come
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const clamp = useCallback((v: View): View => {
    let span = Math.min(n, Math.max(Math.min(MIN_BARS, n), v.b - v.a));
    let a = Math.max(0, Math.min(v.a, n - span));
    if (!Number.isFinite(a)) { a = 0; span = n; }
    return { a, b: a + span };
  }, [n]);

  /** Ease from the current view to `to` (about a quarter of a second). */
  const animateTo = useCallback((to: View) => {
    const target = clamp(to), from = viewRef.current, t0 = performance.now(), ms = 260;
    stop();
    // progress comes from performance.now(), not the frame's timestamp: that can be older than t0
    const step = () => {
      const p = Math.min(1, Math.max(0, (performance.now() - t0) / ms)), e = 1 - Math.pow(1 - p, 3);
      setView({ a: from.a + (target.a - from.a) * e, b: from.b + (target.b - from.b) * e });
      anim.current = p < 1 ? requestAnimationFrame(step) : null;
      if (p >= 1 && settle.current) { clearTimeout(settle.current); settle.current = null; }
    };
    anim.current = requestAnimationFrame(step);
    // a background tab (or a headless browser) may send no frames at all: finish anyway
    settle.current = window.setTimeout(() => { stop(); setView(target); }, ms + 80);
  }, [clamp]);   // eslint-disable-line react-hooks/exhaustive-deps
  const stop = () => {
    if (anim.current) cancelAnimationFrame(anim.current);
    if (settle.current) clearTimeout(settle.current);
    anim.current = settle.current = null;
  };
  useEffect(() => stop, []);

  // a new day or stock shows the whole session; a new candle size keeps the same stretch of time
  const prevN = useRef(n);
  useEffect(() => { setView({ a: 0, b: n }); }, [candles]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (prevN.current !== n && prevN.current > 0) {
      const k = n / prevN.current, v = viewRef.current;
      setView(clamp({ a: v.a * k, b: v.b * k }));
    }
    prevN.current = n;
  }, [n, clamp]);

  const w = Math.max(0, width - PAD.left - PAD.right), h = H - PAD.top - PAD.bottom - VOL_H - VOL_GAP;
  const volTop = PAD.top + h + VOL_GAP, plotBottom = volTop + VOL_H;
  const span = view.b - view.a;
  const px = (i: number) => PAD.left + ((i + 0.5 - view.a) / span) * w;          // centre of candle i
  const posAt = (clientX: number) => {
    const r = box.current!.getBoundingClientRect();
    return view.a + ((clientX - r.left - PAD.left) / w) * span;               // candle position under the pointer
  };

  const zoomAround = useCallback((factor: number, at?: number, smooth = true) => {
    const v = viewRef.current, centre = at ?? (v.a + v.b) / 2;
    const next = { a: centre - (centre - v.a) * factor, b: centre + (v.b - centre) * factor };
    if (smooth) animateTo(next); else setView(clamp(next));
  }, [animateTo, clamp]);

  // wheel: Ctrl/⌘ + scroll or a trackpad pinch zooms, sideways scroll moves; plain scroll still scrolls the page
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        zoomAround(Math.exp(e.deltaY * 0.01), posAt(e.clientX), false);
      } else if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
        e.preventDefault();
        const v = viewRef.current, d = (e.deltaX / w) * (v.b - v.a);
        setView(clamp({ a: v.a + d, b: v.b + d }));
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  });

  // drag to move, two fingers to pinch
  const pointers = useRef(new Map<number, number>());
  const drag = useRef<{ x: number; view: View; pinch?: number } | null>(null);
  const onDown = (e: React.PointerEvent) => {
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    pointers.current.set(e.pointerId, e.clientX);
    const xs = [...pointers.current.values()];
    drag.current = { x: xs[0], view: viewRef.current, pinch: xs.length === 2 ? Math.abs(xs[0] - xs[1]) : undefined };
    stop();
  };
  const onMove = (e: React.PointerEvent) => {
    const i = Math.floor(posAt(e.clientX));
    setHover(i >= 0 && i < n ? i : null);
    if (!drag.current || !pointers.current.has(e.pointerId)) return;
    pointers.current.set(e.pointerId, e.clientX);
    const xs = [...pointers.current.values()], d = drag.current;
    if (xs.length === 2 && d.pinch) {
      const factor = d.pinch / Math.max(20, Math.abs(xs[0] - xs[1]));
      const mid = d.view.a + (((xs[0] + xs[1]) / 2 - box.current!.getBoundingClientRect().left - PAD.left) / w) * (d.view.b - d.view.a);
      setView(clamp({ a: mid - (mid - d.view.a) * factor, b: mid + (d.view.b - mid) * factor }));
    } else {
      const shift = ((d.x - e.clientX) / w) * (d.view.b - d.view.a);
      setView(clamp({ a: d.view.a + shift, b: d.view.b + shift }));
    }
  };
  const onUp = (e: React.PointerEvent) => {
    pointers.current.delete(e.pointerId);
    drag.current = pointers.current.size ? { x: [...pointers.current.values()][0], view: viewRef.current } : null;
  };

  const onKey = (e: React.KeyboardEvent) => {
    const v = viewRef.current, s = (v.b - v.a) * 0.2;
    if (e.key === "+" || e.key === "=") zoomAround(0.6);
    else if (e.key === "-") zoomAround(1 / 0.6);
    else if (e.key === "0") animateTo({ a: 0, b: n });
    else if (e.key === "ArrowLeft") animateTo({ a: v.a - s, b: v.b - s });
    else if (e.key === "ArrowRight") animateTo({ a: v.a + s, b: v.b + s });
    else return;
    e.preventDefault();
  };

  const slotIndex = (t: string) => {
    let k = -1;
    for (let i = 0; i < n; i++) if (minutes(bars[i].time) <= minutes(t)) k = i; else break;
    return k;
  };
  const buyI = trade ? slotIndex(trade.buyTime) : -1;
  // a trade still held (today, live) runs to the latest candle at the latest price
  const sellI = trade ? slotIndex(trade.sellTime ?? trade.lastTime ?? bars[n - 1]?.time ?? "00:00") : -1;
  const sellPrice = trade ? (trade.sellPrice ?? trade.last ?? trade.buyPrice) : 0;
  const fitTrade = () => {
    if (buyI < 0 || sellI < 0) return;
    const margin = Math.max(6, (sellI - buyI) * 0.35);
    animateTo({ a: buyI - margin, b: sellI + 1 + margin });
  };

  if (n === 0) return <p className="empty">No prices for this day.</p>;

  // prices of the candles on screen set the vertical scale, so zooming in shows the detail
  const i0 = Math.max(0, Math.floor(view.a)), i1 = Math.min(n - 1, Math.ceil(view.b) - 1);
  const shown = bars.slice(i0, i1 + 1);
  let lo = Math.min(...shown.map((c) => c.low)), hi = Math.max(...shown.map((c) => c.high));
  if (trade && buyI <= i1 && sellI >= i0) {
    lo = Math.min(lo, trade.buyPrice, sellPrice, trade.stop ?? Infinity); hi = Math.max(hi, trade.buyPrice, sellPrice);
  }
  const pad = (hi - lo) * 0.1 || hi * 0.002;
  lo -= pad; hi += pad;
  const y = (v: number) => PAD.top + (1 - (v - lo) / (hi - lo)) * h;
  const barW = w / span;
  const body = Math.max(1, Math.min(14, barW * 0.68));
  const ticks = [0, 1, 2, 3, 4].map((k) => lo + ((hi - lo) * k) / 4);
  // volume: scaled to the busiest candle on screen, so it zooms with the price
  const vmax = Math.max(1, ...shown.map((c) => c.volume));
  const vy = (v: number) => plotBottom - (v / vmax) * VOL_H;
  const labelEvery = Math.max(1, Math.ceil(70 / Math.max(barW, 0.01)));
  const steps = [1, 2, 3, 5, 10, 15, 30, 60, 120];
  const stepMin = steps.find((s) => s >= labelEvery * interval) ?? 120;
  const rangeEndI = range ? bars.findIndex((c) => c.time >= range.until) : -1;
  const won = trade ? trade.pnl > 0 : false;
  const c = hover === null ? null : bars[hover];
  const zoomed = span < n - 0.5;

  return (
    <div className="tl-chart-wrap">
      <div className="tl-chart-tools" role="toolbar" aria-label="Chart">
        <div className="tl-seg" role="group" aria-label="Candle size">
          {INTERVALS.map((m) => (
            <button key={m} className={interval === m ? "on" : ""} aria-pressed={interval === m} onClick={() => setInterval_(m)}>{m}m</button>
          ))}
        </div>
        <div className="tl-seg" role="group" aria-label="Zoom">
          <button onClick={() => zoomAround(1 / 0.6)} disabled={!zoomed} aria-label="Zoom out" title="Zoom out (−)">−</button>
          <button onClick={() => zoomAround(0.6)} disabled={span <= MIN_BARS + 0.5} aria-label="Zoom in" title="Zoom in (+)">+</button>
          <button onClick={() => animateTo({ a: 0, b: n })} disabled={!zoomed} title="Whole day (0)">Whole day</button>
          {trade && <button onClick={fitTrade} title="Zoom to the trade">Trade</button>}
        </div>
        <span className="muted small tl-hint">Drag to move · pinch or Ctrl/⌘ + scroll to zoom · double-click to zoom in</span>
      </div>

      <div className="tl-chart" ref={box} tabIndex={0} onKeyDown={onKey}
        aria-label={`${symbol} chart. Plus and minus zoom, arrow keys move, 0 shows the whole day.`}>
        {width > 0 && (
          <svg width={width} height={H} role="img"
            aria-label={trade ? `${symbol}: bought at ${trade.buyTime} for ${price(trade.buyPrice)}, ${trade.sellTime ? `sold at ${trade.sellTime} for ${price(sellPrice)}` : `holding, now ${price(sellPrice)}`}` : `${symbol}: no trade`}>
            <defs>
              <clipPath id={`tl-clip-${symbol}`}><rect x={PAD.left} y={0} width={w} height={H} /></clipPath>
            </defs>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={PAD.left} x2={PAD.left + w} y1={y(t)} y2={y(t)} className="tl-grid" />
                <text x={PAD.left + w + 8} y={y(t)} className="tl-axis" dominantBaseline="middle">{price(t)}</text>
              </g>
            ))}
            <g clipPath={`url(#tl-clip-${symbol})`}>
              {bars.map((k, i) => (i >= i0 - 1 && i <= i1 + 1 && minutes(k.time) % stepMin === 0) ? (
                <text key={`t${k.time}`} x={px(i)} y={H - 8} className="tl-axis" textAnchor="middle">{k.time}</text>
              ) : null)}

              {range && rangeEndI > 0 && (
                <g>
                  <rect x={PAD.left} y={y(range.high)} width={w} height={Math.max(1, y(range.low) - y(range.high))} className="tl-range" />
                  <line x1={PAD.left} x2={PAD.left + w} y1={y(range.high)} y2={y(range.high)} className="tl-range-line" />
                  <line x1={PAD.left} x2={PAD.left + w} y1={y(range.low)} y2={y(range.low)} className="tl-range-line" />
                  <line x1={px(rangeEndI) - barW / 2} x2={px(rangeEndI) - barW / 2} y1={PAD.top} y2={plotBottom} className="tl-range-line" />
                  <text x={Math.max(PAD.left + 4, px(0) - barW / 2 + 4)} y={y(range.high) - 6} className="tl-axis">Opening range</text>
                </g>
              )}

              {bars.map((k, i) => {
                if (i < i0 - 1 || i > i1 + 1) return null;
                const up = k.close >= k.open, cx = px(i);
                const top = y(Math.max(k.open, k.close)), bottom = y(Math.min(k.open, k.close));
                return (
                  <g key={k.time} className={up ? "tl-candle-up" : "tl-candle-down"}>
                    <line x1={cx} x2={cx} y1={y(k.high)} y2={y(k.low)} />
                    <rect x={cx - body / 2} y={top} width={body} height={Math.max(1, bottom - top)} rx={Math.min(1.5, body / 4)} />
                  </g>
                );
              })}

              {bars.map((k, i) => (i < i0 - 1 || i > i1 + 1) ? null : (
                <rect key={`v${k.time}`} x={px(i) - body / 2} y={vy(k.volume)} width={body} height={Math.max(0.5, plotBottom - vy(k.volume))}
                  className={k.close >= k.open ? "tl-vol-up" : "tl-vol-down"} />
              ))}

              {trade && buyI >= 0 && sellI >= 0 && (
                <g>
                  <line x1={px(buyI)} x2={px(sellI)} y1={y(trade.buyPrice)} y2={y(trade.buyPrice)} className="tl-entry-line" />
                  <line x1={px(buyI)} x2={px(sellI)} y1={y(trade.buyPrice)} y2={y(sellPrice)} className={won ? "tl-path-win" : "tl-path-loss"} />
                  {trade.open && trade.stop && (
                    <g>
                      <line x1={px(buyI)} x2={PAD.left + w} y1={y(trade.stop)} y2={y(trade.stop)} className="tl-stop-line" />
                      <text x={PAD.left + w - 4} y={y(trade.stop) + 14} className="tl-axis" textAnchor="end">
                        {trade.trailing ? "Trailing stop" : "Stop"} {price(trade.stop)}
                      </text>
                    </g>
                  )}
                  <Marker x={px(buyI)} y={y(trade.buyPrice)} kind="buy" label={`Buy ${trade.buyTime} · ${price(trade.buyPrice)}`} left={PAD.left} right={PAD.left + w} />
                  {trade.sellTime ? (
                    <Marker x={px(sellI)} y={y(sellPrice)} kind="sell" label={`Sell ${trade.sellTime} · ${price(sellPrice)}`} left={PAD.left} right={PAD.left + w} />
                  ) : (
                    <circle cx={px(sellI)} cy={y(sellPrice)} r={4} className="tl-now-dot" />
                  )}
                </g>
              )}
              {c && hover !== null && <line x1={px(hover)} x2={px(hover)} y1={PAD.top} y2={plotBottom} className="tl-cross" />}
            </g>
            <line x1={PAD.left} x2={PAD.left + w} y1={volTop - VOL_GAP / 2} y2={volTop - VOL_GAP / 2} className="tl-grid" />
            <text x={PAD.left + w + 8} y={volTop + 6} className="tl-axis">{compact(vmax)}</text>
            <text x={PAD.left + w + 8} y={plotBottom} className="tl-axis">Vol</text>
            <rect x={PAD.left} y={PAD.top} width={w} height={plotBottom - PAD.top} fill="transparent" className={drag.current ? "tl-grabbing" : "tl-grab"}
              onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
              onPointerLeave={() => { setHover(null); }} onDoubleClick={(e) => zoomAround(0.5, posAt(e.clientX))} />
          </svg>
        )}
        {c && hover !== null && !drag.current && (
          <div className="tl-tip" style={{ left: Math.min(Math.max(px(hover), 120), width - 120), top: 2 }}>
            <div className="muted small">{symbol} · {c.time}–{hhmm(minutes(c.time) + interval)}</div>
            <div className="tl-ohlc small">
              <span>O {price(c.open)}</span><span>H {price(c.high)}</span><span>L {price(c.low)}</span><span>C {price(c.close)}</span>
            </div>
            <div className="small muted">{c.close >= c.open ? "Rose" : "Fell"} {money(Math.abs(c.close - c.open), currency)} · vol {Math.round(c.volume).toLocaleString()}</div>
          </div>
        )}
      </div>
    </div>
  );
}

/** 724082 -> "724K", 1530000 -> "1.5M". */
const compact = (v: number) => new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(v);

/** Buy: an upward arrow under the price, label below. Sell: a downward arrow above it, label above. */
function Marker({ x, y, kind, label, left, right }: { x: number; y: number; kind: "buy" | "sell"; label: string; left: number; right: number }) {
  const up = kind === "buy";
  const tip = up ? y + 4 : y - 4;
  const d = up ? `M${x},${tip} l-6,10 h12 z` : `M${x},${tip} l-6,-10 h12 z`;
  const anchor = x < left + 90 ? "start" : x > right - 110 ? "end" : "middle";
  return (
    <g className={`tl-marker tl-marker-${kind}`}>
      <circle cx={x} cy={y} r={3.5} />
      <path d={d} />
      <text x={x} y={up ? tip + 24 : tip - 16} textAnchor={anchor}>{label}</text>
    </g>
  );
}
