import * as THREE from "three";
import { HDRLoader } from "three/examples/jsm/loaders/HDRLoader.js";
import type { Display } from "../lib/display";

/**
 * Jarvis's room: a penthouse at night. A dark polished floor, floor-to-ceiling windows with the Shanghai skyline
 * across the river (Poly Haven "Shanghai Bund", CC0, by Greg Zaal; the same panorama lights the scene, so the
 * suit and skin pick up real city light), two holographic panels with today's live numbers, and a ticker in the
 * window sill. Files: public/avatar/city.hdr (lighting) and skyline.webp (the view), made from avatar-source/.
 */
export type Penthouse = {
  setWall: (d: Display | null) => void;
  update: (dt: number, t: number, dim: boolean, wide: boolean) => void;
  dispose: () => void;
};

const WINDOW_Z = -6;       // the glass wall
const CITY_Z = -28;        // the skyline, far beyond it
const CYAN = "#4fd8ff";

export function buildPenthouse(scene: THREE.Scene, renderer: THREE.WebGLRenderer, base = "/avatar/"): Penthouse {
  const room = new THREE.Group();
  scene.add(room);
  const trash: { dispose: () => void }[] = [];
  const keep = <T extends { dispose: () => void }>(x: T) => (trash.push(x), x);
  let gone = false;

  // city light: the panorama lights him (reflections on the suit, colour on the skin)
  new HDRLoader().loadAsync(base + "city.hdr").then((tex) => {
    if (gone) return tex.dispose();
    tex.mapping = THREE.EquirectangularReflectionMapping;
    const pm = new THREE.PMREMGenerator(renderer);
    const env = keep(pm.fromEquirectangular(tex).texture);
    pm.dispose();
    tex.dispose();
    scene.environment = env;
    scene.environmentIntensity = 0.75;
    // its own, much weaker copy for the floor (a material's envMapIntensity only counts with its own envMap)
    floorMat.envMap = env;
    floorMat.envMapIntensity = 0.12;
    floorMat.needsUpdate = true;
  }).catch(() => undefined);

  // the view: the skyline far behind the glass, and the night sky above it
  const sky = new THREE.Mesh(keep(new THREE.PlaneGeometry(220, 90)), keep(new THREE.MeshBasicMaterial({ color: 0x141322, toneMapped: false, fog: false })));
  sky.position.set(0, 30, CITY_Z - 1);
  room.add(sky);
  const viewTex = keep(new THREE.TextureLoader().load(base + "skyline.webp"));
  viewTex.colorSpace = THREE.SRGBColorSpace;
  viewTex.anisotropy = 4;
  const VIEW_W = 70, VIEW_H = VIEW_W / (2400 / 650);
  const view = new THREE.Mesh(keep(new THREE.PlaneGeometry(VIEW_W, VIEW_H)),
    keep(new THREE.MeshBasicMaterial({ map: viewTex, toneMapped: false, color: new THREE.Color(0.58, 0.58, 0.64) })));   // dimmed: he's in focus, the city isn't
  view.position.set(1.5, -3.6 + VIEW_H / 2, CITY_Z);   // the river line sits just above the window sill
  room.add(view);
  // the sky in the photo fades into the night above it
  const fadeTex = keep(gradientTexture(["rgba(20,19,34,0)", "rgba(20,19,34,1)"]));
  const fade = new THREE.Mesh(keep(new THREE.PlaneGeometry(VIEW_W, 6)), keep(new THREE.MeshBasicMaterial({ map: fadeTex, transparent: true, toneMapped: false, depthWrite: false })));
  fade.position.set(view.position.x, view.position.y + VIEW_H / 2 - 2.9, CITY_Z + 0.01);
  room.add(fade);

  // the glass wall: slim frames, a sill, and a faint tint on the glass
  const frameMat = keep(new THREE.MeshStandardMaterial({ color: 0x0b0e14, roughness: 0.35, metalness: 0.8 }));
  for (let x = -26; x <= 26; x += 4.2) {
    const m = new THREE.Mesh(keep(new THREE.BoxGeometry(0.09, 14, 0.14)), frameMat);
    m.position.set(x, 7, WINDOW_Z);
    room.add(m);
  }
  const sill = new THREE.Mesh(keep(new THREE.BoxGeometry(60, 0.32, 0.4)), frameMat);
  sill.position.set(0, 0.16, WINDOW_Z);
  sill.receiveShadow = true;
  room.add(sill);
  const glass = new THREE.Mesh(keep(new THREE.PlaneGeometry(60, 14)),
    keep(new THREE.MeshBasicMaterial({ color: 0x0b1a2e, transparent: true, opacity: 0.18, depthWrite: false })));
  glass.position.set(0, 7, WINDOW_Z - 0.05);
  room.add(glass);

  // the floor: dark satin stone; the city's light reaches it as soft neon spill (below), not a bright mirror
  const floorMat = keep(new THREE.MeshStandardMaterial({ color: 0x0b0e15, roughness: 0.5, metalness: 0.15 }));   // dark satin stone
  const floor = new THREE.Mesh(keep(new THREE.PlaneGeometry(60, 20)), floorMat);
  floor.rotation.x = -Math.PI / 2;
  floor.position.set(0, -0.003, WINDOW_Z + 10);
  room.add(floor);

  // neon spill from the city: soft purple and cyan glows on the floor near the glass
  const glowTex = keep(gradientTexture(["rgba(255,255,255,0)", "rgba(255,255,255,.9)"], true));
  for (const [x, c, o] of [[-5, 0xb06cff, 0.12], [4, 0x4fd8ff, 0.1], [9, 0xff5fa2, 0.07]] as const) {
    const g = new THREE.Mesh(keep(new THREE.PlaneGeometry(9, 5)),
      keep(new THREE.MeshBasicMaterial({ map: glowTex, color: c, transparent: true, opacity: o, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false })));
    g.rotation.x = -Math.PI / 2;
    g.position.set(x, 0.002, WINDOW_Z + 2.2);
    room.add(g);
  }

  // two holographic panels with today's numbers, and a ticker along the sill
  const panels = [-1, 1].map((side) => {
    const canvas = document.createElement("canvas");
    canvas.width = 768;
    canvas.height = 480;
    const tex = keep(new THREE.CanvasTexture(canvas));
    tex.colorSpace = THREE.SRGBColorSpace;
    const mat = keep(new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0.9, depthWrite: false, toneMapped: false, side: THREE.DoubleSide }));
    const mesh = new THREE.Mesh(keep(new THREE.PlaneGeometry(1.9, 1.19)), mat);
    mesh.position.set(side * 3.0, 1.75, -2.6);
    mesh.rotation.y = -side * 0.28;
    room.add(mesh);
    return { canvas, tex, mat, mesh, side };
  });
  const tickCanvas = document.createElement("canvas");
  tickCanvas.width = 4096;
  tickCanvas.height = 64;
  const tickTex = keep(new THREE.CanvasTexture(tickCanvas));
  tickTex.colorSpace = THREE.SRGBColorSpace;
  tickTex.wrapS = THREE.RepeatWrapping;
  const TICK_W = 60, TICK_H = 0.15;
  const ticker = new THREE.Mesh(keep(new THREE.PlaneGeometry(TICK_W, TICK_H)),
    keep(new THREE.MeshBasicMaterial({ map: tickTex, transparent: true, toneMapped: false, depthWrite: false })));
  ticker.position.set(0, 0.17, WINDOW_Z + 0.21);
  room.add(ticker);

  const setWall = (d: Display | null) => {
    const stats = d?.stats ?? [];
    const lab = stats.filter((s) => s.label.includes("P&L"));
    const today = stats.filter((s) => !s.label.includes("P&L")).slice(0, 4);
    drawPanel(panels[0].canvas, "TODAY", today.length ? today : [{ label: "Jarvis", value: "Online" }]);
    drawPanel(panels[1].canvas, "TRADING LAB · PAPER", lab.length ? lab : [{ label: "Trading Lab", value: "—" }]);
    panels.forEach((p) => (p.tex.needsUpdate = true));
    const line = stats.length ? stats.map((s) => `${s.label.toUpperCase()}  ${s.value}`).join("     ·     ") : "J.A.R.V.I.S  ·  PRESQIO SALES ASSISTANT  ·  ONLINE";
    const unitW = drawTicker(tickCanvas, line);   // the canvas holds exactly one copy, repeated seamlessly
    tickTex.repeat.set(TICK_W / (TICK_H * (unitW / tickCanvas.height)), 1);
    tickTex.needsUpdate = true;
  };
  setWall(null);

  let fadeIn = 0;
  const update = (dt: number, t: number, dim: boolean, wide: boolean) => {
    fadeIn = Math.min(1, fadeIn + dt * 0.8);
    for (const p of panels) {
      p.mesh.visible = wide;   // a phone has no room beside him
      const to = (dim ? 0.22 : 0.88) * fadeIn;
      p.mat.opacity += (to - p.mat.opacity) * Math.min(1, dt * 4);
      p.mesh.position.y = 1.75 + Math.sin(t * 0.7 + p.side) * 0.03;
    }
    tickTex.offset.x = (tickTex.offset.x + dt * 0.04) % 1;
  };

  return {
    setWall, update,
    dispose: () => {
      gone = true;
      trash.forEach((x) => x.dispose());
      scene.remove(room);
    },
  };
}

function gradientTexture(stops: string[], radial = false): THREE.Texture {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d")!;
  const grad = radial ? g.createRadialGradient(64, 64, 64, 64, 64, 0) : g.createLinearGradient(0, 128, 0, 0);
  stops.forEach((s, i) => grad.addColorStop(i / (stops.length - 1), s));
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function drawPanel(c: HTMLCanvasElement, title: string, rows: { label: string; value: string; tone?: string | null }[]) {
  const g = c.getContext("2d")!;
  const w = c.width, h = c.height;
  g.clearRect(0, 0, w, h);
  // glass card
  const bg = g.createLinearGradient(0, 0, w, h);
  bg.addColorStop(0, "rgba(79,216,255,0.20)");
  bg.addColorStop(1, "rgba(6,22,40,0.55)");
  g.fillStyle = bg;
  roundRect(g, 4, 4, w - 8, h - 8, 18);
  g.fill();
  g.strokeStyle = "rgba(79,216,255,0.7)";
  g.lineWidth = 3;
  g.stroke();
  // scanlines
  g.fillStyle = "rgba(79,216,255,0.05)";
  for (let y = 8; y < h; y += 6) g.fillRect(8, y, w - 16, 1);
  // title
  g.fillStyle = CYAN;
  g.font = "600 26px 'JetBrains Mono', monospace";
  g.fillText(title.split("").join(" "), 36, 58);
  g.fillRect(36, 76, w - 72, 2);
  // rows
  const n = Math.min(rows.length, 4);
  rows.slice(0, 4).forEach((r, i) => {
    const y = 150 + i * ((h - 180) / Math.max(n, 1));
    g.fillStyle = "rgba(205,239,255,0.7)";
    g.font = "400 26px Inter, system-ui, sans-serif";
    g.fillText(r.label, 36, y);
    g.fillStyle = r.tone === "up" ? "#4ee6a0" : r.tone === "down" ? "#ff7b7b" : "#f0fbff";
    g.font = "600 44px Inter, system-ui, sans-serif";
    const tw = g.measureText(r.value).width;
    g.fillText(r.value, w - 36 - tw, y + 4);
  });
}

/** One copy of the ticker text, sized to fit the canvas exactly so it repeats without a seam. -> its width in pixels. */
function drawTicker(c: HTMLCanvasElement, text: string): number {
  const font = "500 34px 'JetBrains Mono', monospace";
  const unit = text + "     ·     ";
  let g = c.getContext("2d")!;
  g.font = font;
  c.width = Math.min(8192, Math.ceil(g.measureText(unit).width));   // resizing clears the canvas
  g = c.getContext("2d")!;
  g.fillStyle = "rgba(4,14,26,0.9)";
  g.fillRect(0, 0, c.width, c.height);
  g.font = font;
  g.fillStyle = "rgba(79,216,255,0.9)";
  g.fillText(unit, 0, 44);
  return c.width;
}

function roundRect(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  g.beginPath();
  g.moveTo(x + r, y);
  g.arcTo(x + w, y, x + w, y + h, r);
  g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r);
  g.arcTo(x, y, x + w, y, r);
  g.closePath();
}
