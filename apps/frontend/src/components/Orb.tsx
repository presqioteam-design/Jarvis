import { useEffect, useRef } from "react";
import type { CallState } from "../lib/voice";

/**
 * The Jarvis arc-reactor HUD: a slowly turning sphere of glowing cyan fragments inside
 * layered rotating rings (segmented ring, partial arcs, a degree scale) and an equalizer
 * ring that moves with whoever is talking. The core turns warm gold while Jarvis speaks.
 * Canvas 2D with additive blending for the glow.
 */
type Particle = { th: number; ph: number; r: number; len: number; spin: number; kind: 0 | 1 | 2; seed: number };

function makeParticles(n: number): Particle[] {
  const out: Particle[] = [];
  for (let i = 0; i < n; i++) {
    const kind: 0 | 1 | 2 = i % 10 < 7 ? 0 : i % 10 < 9 ? 1 : 2; // 70% shell, 20% inner ring, 10% core sparks
    out.push({
      th: Math.random() * Math.PI * 2,
      ph: kind === 1 ? Math.PI / 2 + (Math.random() - 0.5) * 0.25 : Math.acos(2 * Math.random() - 1),
      r: kind === 0 ? 1 + (Math.random() - 0.5) * 0.12 : kind === 1 ? 0.58 + Math.random() * 0.06 : Math.random() * 0.32,
      len: kind === 0 ? 2 + Math.random() * 7 : 1 + Math.random() * 3,
      spin: (Math.random() - 0.5) * 0.4,
      kind,
      seed: Math.random() * 1000,
    });
  }
  return out;
}

const CYAN = "79,216,255";
const GOLD = "255,184,77";

export default function Orb({ state, levels }: { state: CallState | "idle"; levels: () => { you: number; jarvis: number } }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef(state);
  stateRef.current = state;
  const levelsRef = useRef(levels);
  levelsRef.current = levels;

  useEffect(() => {
    const canvas = ref.current!;
    const ctx = canvas.getContext("2d")!;
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const particles = makeParticles(innerWidth < 700 ? 900 : 1400);
    const bars = new Float32Array(96);
    let raf = 0;
    let rot = 0;
    let smooth = 0;
    let swirl = 0;
    let warm = 0; // 0 cyan → 1 gold while Jarvis speaks
    let last = performance.now();

    const resize = () => {
      const dpr = Math.min(devicePixelRatio || 1, 2);
      canvas.width = canvas.clientWidth * dpr;
      canvas.height = canvas.clientHeight * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    addEventListener("resize", resize);

    const arc = (cx: number, cy: number, r: number, a0: number, a1: number, color: string, width: number) => {
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.beginPath();
      ctx.arc(cx, cy, r, a0, a1);
      ctx.stroke();
    };

    const frame = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      const s = stateRef.current;
      const lv = levelsRef.current();
      const target = s === "speaking" ? lv.jarvis : s === "listening" ? lv.you * 0.8 : 0;
      smooth += (target - smooth) * Math.min(1, dt * (target > smooth ? 18 : 6));
      swirl += ((s === "thinking" || s === "connecting" ? 1 : 0) - swirl) * Math.min(1, dt * 3);
      warm += ((s === "speaking" ? 1 : 0) - warm) * Math.min(1, dt * 4);
      const t = now / 1000;
      const breathe = s === "idle" || s === "ended" || s === "error" ? 0.025 * Math.sin(t * 1.4) : 0.012 * Math.sin(t * 2);
      rot += dt * (0.12 + swirl * 1.1 + smooth * 0.5) * (reduced ? 0.2 : 1);
      const dim = s === "ended" || s === "error" ? 0.4 : s === "idle" ? 0.75 : 1;
      const hud = (a: number) => `rgba(${CYAN},${a * dim})`;

      const cx = w / 2;
      const cy = h / 2;
      const base = Math.min(w, h) * 0.24;
      const R = base * (1 + breathe + smooth * 0.12);
      const tilt = 0.35 + Math.sin(t * 0.2) * 0.08;
      const ct = Math.cos(tilt);
      const st = Math.sin(tilt);

      ctx.clearRect(0, 0, w, h);
      ctx.globalCompositeOperation = "lighter";

      // halo
      const halo = ctx.createRadialGradient(cx, cy, R * 0.2, cx, cy, R * 1.9);
      halo.addColorStop(0, `rgba(${CYAN},${0.14 * dim + smooth * 0.14})`);
      halo.addColorStop(0.45, `rgba(${warm > 0.5 ? GOLD : CYAN},${0.05 * dim + warm * 0.05})`);
      halo.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = halo;
      ctx.fillRect(0, 0, w, h);

      // sphere of fragments
      for (const p of particles) {
        const th = p.th + rot * (p.kind === 1 ? -1.6 : 1) + p.spin * t * 0.1;
        const wobble = p.kind === 0 ? 1 + smooth * 0.35 * Math.sin(p.seed + t * 9) * Math.sin(p.ph * 3 + t * 4) : 1 + smooth * 0.2;
        const r = p.r * wobble;
        let y = r * Math.cos(p.ph);
        let z = r * Math.sin(p.ph) * Math.sin(th);
        const x = r * Math.sin(p.ph) * Math.cos(th);
        const y2 = y * ct - z * st; // tilt towards the viewer
        z = y * st + z * ct;
        y = y2;
        const persp = 1 / (1.9 - z * 0.55);
        const sx = cx + x * R * persp * 1.6;
        const sy = cy + y * R * persp * 1.6;
        const depth = (z + 1.2) / 2.4;
        const flicker = 0.75 + 0.25 * Math.sin(p.seed + t * (3 + p.spin * 10));
        const a = Math.max(0, Math.min(1, (0.08 + depth * 0.9) * flicker * dim * (p.kind === 2 ? 0.9 + smooth : 1)));
        // core sparks switch to gold while Jarvis speaks (a straight switch: fading the hue would pass
        // through green); the shell and inner ring stay reactor-blue
        const hue = p.kind === 2 && warm > 0.5 ? 40 : 192 + depth * 6;
        ctx.globalAlpha = p.kind === 2 ? a * (warm > 0.5 ? warm : 1 - warm) : a;
        ctx.strokeStyle = ctx.fillStyle = `hsl(${hue},100%,${55 + depth * 20 + smooth * 8}%)`;
        if (p.kind === 0) {
          const len = p.len * (1 + smooth * 1.5) * persp;
          const dx = -Math.sin(th) * len;
          const dy = Math.cos(th) * len * 0.35;
          ctx.lineWidth = 0.6 + depth * 0.9;
          ctx.beginPath();
          ctx.moveTo(sx - dx, sy - dy);
          ctx.lineTo(sx + dx, sy + dy);
          ctx.stroke();
        } else if (p.kind === 2) {
          ctx.beginPath();
          ctx.arc(sx, sy, p.len * persp * (0.45 + smooth * 0.5), 0, Math.PI * 2);
          ctx.fill();
        } else {
          const size = p.len * persp;
          ctx.fillRect(sx - size / 2, sy - size / 2, size, size);
        }
      }
      ctx.globalAlpha = 1;

      // core
      const coreR = R * (0.22 + smooth * 0.22 + swirl * 0.04);
      const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR);
      core.addColorStop(0, `rgba(240,252,255,${0.9 * dim})`);
      core.addColorStop(0.35, `rgba(${warm > 0.5 ? GOLD : CYAN},${0.55 * dim})`);
      core.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = core;
      ctx.beginPath();
      ctx.arc(cx, cy, coreR, 0, Math.PI * 2);
      ctx.fill();

      // equalizer ring: bars follow the voice, with a slow idle shimmer
      const eqR = base * 1.22;
      for (let i = 0; i < bars.length; i++) {
        const noise = 0.5 + 0.5 * Math.sin(i * 1.7 + t * 6) * Math.sin(i * 0.6 - t * 3.3);
        const want = 0.04 + smooth * (0.4 + 0.6 * noise) + swirl * 0.12 * (0.5 + 0.5 * Math.sin(i * 0.4 + t * 8));
        bars[i] += (want - bars[i]) * Math.min(1, dt * 14);
        const ang = (i / bars.length) * Math.PI * 2 - Math.PI / 2;
        const len = base * 0.18 * bars[i];
        ctx.strokeStyle = `rgba(${warm > 0.5 ? GOLD : CYAN},${(0.25 + bars[i]) * dim})`;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(ang) * eqR, cy + Math.sin(ang) * eqR);
        ctx.lineTo(cx + Math.cos(ang) * (eqR + len), cy + Math.sin(ang) * (eqR + len));
        ctx.stroke();
      }

      ctx.globalCompositeOperation = "source-over";

      // segmented ring
      const segR = base * 1.48;
      for (let i = 0; i < 60; i++) {
        const a0 = (i / 60) * Math.PI * 2 + rot * 0.35;
        arc(cx, cy, segR, a0, a0 + (Math.PI * 2) / 60 * 0.62, hud(i % 15 < 11 ? 0.5 : 0.15), 5);
      }

      // counter-rotating partial arcs with bright caps
      const arcR = base * 1.62;
      for (let i = 0; i < 3; i++) {
        const a0 = -rot * 0.5 + (i * Math.PI * 2) / 3;
        const a1 = a0 + Math.PI * 0.42;
        arc(cx, cy, arcR, a0, a1, hud(0.55), 2);
        arc(cx, cy, arcR, a1 - 0.05, a1, hud(1), 5);
      }
      arc(cx, cy, base * 1.69, rot * 0.8, rot * 0.8 + Math.PI * 0.25, hud(0.35), 1);
      arc(cx, cy, base * 1.69, rot * 0.8 + Math.PI, rot * 0.8 + Math.PI * 1.25, hud(0.35), 1);

      // degree scale with labels
      const scaleR = base * 1.78;
      ctx.strokeStyle = hud(0.3);
      ctx.lineWidth = 1;
      const turn = -rot * 0.12;
      for (let i = 0; i < 120; i++) {
        const ang = (i / 120) * Math.PI * 2 + turn;
        const long = i % 10 === 0;
        const r2 = scaleR + (long ? 9 : 4);
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(ang) * scaleR, cy + Math.sin(ang) * scaleR);
        ctx.lineTo(cx + Math.cos(ang) * r2, cy + Math.sin(ang) * r2);
        ctx.stroke();
      }
      if (w > 360) {
        ctx.fillStyle = hud(0.45);
        ctx.font = `${Math.max(8, base * 0.045)}px "JetBrains Mono", monospace`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        for (let i = 0; i < 12; i++) {
          const ang = (i / 12) * Math.PI * 2 + turn;
          const lr = scaleR + 20;
          ctx.fillText(String(i * 30).padStart(3, "0"), cx + Math.cos(ang) * lr, cy + Math.sin(ang) * lr);
        }
      }

      // a faint radar sweep while connecting or working
      if (swirl > 0.02) {
        const sweep = t * 2.4;
        const g = ctx.createConicGradient ? ctx.createConicGradient(sweep, cx, cy) : null;
        if (g) {
          g.addColorStop(0, `rgba(${CYAN},${0.16 * swirl})`);
          g.addColorStop(0.12, `rgba(${CYAN},0)`);
          g.addColorStop(1, `rgba(${CYAN},0)`);
          ctx.fillStyle = g;
          ctx.beginPath();
          ctx.arc(cx, cy, scaleR, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      removeEventListener("resize", resize);
    };
  }, []);

  return <canvas ref={ref} className="orb" aria-hidden="true" />;
}
