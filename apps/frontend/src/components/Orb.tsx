import { useEffect, useRef } from "react";
import type { CallState } from "../lib/voice";

/**
 * The Jarvis orb: a slowly turning sphere of glowing fragments with a bright
 * core. It breathes when idle, ripples with your voice, swirls while thinking
 * and pulses with Jarvis's voice. Canvas 2D with additive blending for the glow.
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
    const particles = makeParticles(innerWidth < 700 ? 1000 : 1600);
    let raf = 0;
    let rot = 0;
    let smooth = 0;
    let swirl = 0;
    let last = performance.now();

    const resize = () => {
      const dpr = Math.min(devicePixelRatio || 1, 2);
      canvas.width = canvas.clientWidth * dpr;
      canvas.height = canvas.clientHeight * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    addEventListener("resize", resize);

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
      const t = now / 1000;
      const breathe = s === "idle" || s === "ended" || s === "error" ? 0.025 * Math.sin(t * 1.4) : 0.012 * Math.sin(t * 2);
      rot += dt * (0.12 + swirl * 1.1 + smooth * 0.5) * (reduced ? 0.2 : 1);
      const dim = s === "ended" || s === "error" ? 0.35 : s === "idle" ? 0.7 : 1;

      const cx = w / 2;
      const cy = h / 2;
      const R = Math.min(w, h) * 0.3 * (1 + breathe + smooth * 0.14);
      const tilt = 0.35 + Math.sin(t * 0.2) * 0.08;
      const ct = Math.cos(tilt);
      const st = Math.sin(tilt);

      ctx.clearRect(0, 0, w, h);
      ctx.globalCompositeOperation = "lighter";

      // halo
      const halo = ctx.createRadialGradient(cx, cy, R * 0.2, cx, cy, R * 1.7);
      halo.addColorStop(0, `rgba(255,140,30,${0.16 * dim + smooth * 0.18})`);
      halo.addColorStop(0.5, `rgba(255,90,10,${0.05 * dim})`);
      halo.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = halo;
      ctx.fillRect(0, 0, w, h);

      // particles
      for (const p of particles) {
        const th = p.th + rot * (p.kind === 1 ? -1.6 : 1) + p.spin * t * 0.1;
        const wobble = p.kind === 0 ? 1 + smooth * 0.35 * Math.sin(p.seed + t * 9) * Math.sin(p.ph * 3 + t * 4) : 1 + smooth * 0.2;
        const r = p.r * wobble;
        let x = r * Math.sin(p.ph) * Math.cos(th);
        let y = r * Math.cos(p.ph);
        let z = r * Math.sin(p.ph) * Math.sin(th);
        // tilt the sphere towards the viewer
        const y2 = y * ct - z * st;
        z = y * st + z * ct;
        y = y2;
        const persp = 1 / (1.9 - z * 0.55);
        const sx = cx + x * R * persp * 1.6;
        const sy = cy + y * R * persp * 1.6;
        const depth = (z + 1.2) / 2.4;
        const flicker = 0.75 + 0.25 * Math.sin(p.seed + t * (3 + p.spin * 10));
        const a = Math.max(0, Math.min(1, (0.08 + depth * 0.9) * flicker * dim * (p.kind === 2 ? 0.9 + smooth : 1)));
        const hue = p.kind === 2 ? 42 : 26 + depth * 14;
        ctx.globalAlpha = a;
        ctx.strokeStyle = ctx.fillStyle = `hsl(${hue},100%,${52 + depth * 20 + smooth * 10}%)`;
        if (p.kind === 0) {
          // short streak along the direction of travel, like the reference's data fragments
          const len = p.len * (1 + smooth * 1.5) * persp;
          const dx = -Math.sin(th) * len;
          const dy = Math.cos(th) * len * 0.35;
          ctx.lineWidth = 0.6 + depth * 0.9;
          ctx.beginPath();
          ctx.moveTo(sx - dx, sy - dy);
          ctx.lineTo(sx + dx, sy + dy);
          ctx.stroke();
        } else {
          const size = p.len * persp * (p.kind === 2 ? 1.2 + smooth * 2 : 1);
          ctx.fillRect(sx - size / 2, sy - size / 2, size, size);
        }
      }
      ctx.globalAlpha = 1;

      // core
      const coreR = R * (0.22 + smooth * 0.22 + swirl * 0.04);
      const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR);
      core.addColorStop(0, `rgba(255,245,220,${0.9 * dim})`);
      core.addColorStop(0.35, `rgba(255,190,80,${0.55 * dim})`);
      core.addColorStop(1, "rgba(255,110,20,0)");
      ctx.fillStyle = core;
      ctx.beginPath();
      ctx.arc(cx, cy, coreR, 0, Math.PI * 2);
      ctx.fill();

      // outer HUD arcs and ticks
      ctx.globalCompositeOperation = "source-over";
      ctx.lineWidth = 1;
      for (let i = 0; i < 3; i++) {
        const rr = R * (1.32 + i * 0.07);
        const start = rot * (i % 2 ? -0.6 : 0.4) + i * 2.1;
        ctx.strokeStyle = `rgba(255,150,50,${(0.28 - i * 0.07) * dim})`;
        ctx.beginPath();
        ctx.arc(cx, cy, rr, start, start + Math.PI * (0.55 + i * 0.2));
        ctx.stroke();
      }
      ctx.strokeStyle = `rgba(255,150,50,${0.22 * dim})`;
      for (let i = 0; i < 72; i++) {
        const ang = (i / 72) * Math.PI * 2 - rot * 0.15;
        const r1 = R * 1.5;
        const r2 = r1 + (i % 6 === 0 ? 10 : 4) * (1 + smooth);
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(ang) * r1, cy + Math.sin(ang) * r1);
        ctx.lineTo(cx + Math.cos(ang) * r2, cy + Math.sin(ang) * r2);
        ctx.stroke();
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
