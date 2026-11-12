import { useEffect, useRef, type RefObject } from "react";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import type { CallState } from "../lib/voice";
import { loadHuman, type Human } from "./human";

/**
 * Jarvis as a smooth, stylised person standing on a softly lit stage (three.js, loaded only when picked).
 * Built from rounded shapes on a simple skeleton and animated in code: it walks (legs, knees, arm swing,
 * hip bob), breathes, blinks, follows your pointer, waves hello, nods while you talk, and while Jarvis
 * speaks its mouth moves with the real audio and its hands gesture.
 *   standby: walks onto the stage, then strolls about now and then · a call starts: walks back and waves
 *   a command runs (`focus` "work"): steps aside, raises a hand, and pulls data in from the card along a beam
 *   the result is in ("present"): holds the card up and looks between it and you
 * The card is HTML (crisp text) that this component moves each frame to sit by the character's hand.
 * The canvas fills the page behind everything; `frame` is the empty box in the layout the character stands in.
 * To swap in an artist-made rigged model later, replace the build section and drive its bones the same way.
 */
export type AvatarFocus = "work" | "present" | null;

type Props = {
  state: CallState | "idle";
  levels: () => { you: number; jarvis: number };
  focus: AvatarFocus;
  onFail: () => void;
  frame: RefObject<HTMLElement | null>;
  card: RefObject<HTMLElement | null>;
};

const CYAN = new THREE.Color(0x4fd8ff);

/** A soft round blob: white fading to transparent, or (for an alphaMap, which reads brightness) white fading to black. */
function radialTexture(asMask = false): THREE.Texture {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d")!;
  const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  const col = (a: number) => (asMask ? `rgb(${Math.round(a * 255)},${Math.round(a * 255)},${Math.round(a * 255)})` : `rgba(255,255,255,${a})`);
  grad.addColorStop(0, col(1));
  grad.addColorStop(asMask ? 0.45 : 0.3, col(asMask ? 0.8 : 0.5));
  grad.addColorStop(1, col(0));
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
}

type Arm = { shoulder: THREE.Group; elbow: THREE.Group; wrist: THREE.Group; hand: THREE.Mesh; side: number };
type Leg = { hip: THREE.Group; knee: THREE.Group; ankle: THREE.Group; side: number };

export default function Avatar({ state, levels, focus, onFail, frame, card }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const live = useRef({ state, levels, focus, onFail });
  live.current = { state, levels, focus, onFail };

  useEffect(() => {
    const host = ref.current!;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    } catch {
      live.current.onFail();
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.setClearColor(0x000000, 0);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    host.appendChild(renderer.domElement);
    const lost = (e: Event) => { e.preventDefault(); live.current.onFail(); };
    renderer.domElement.addEventListener("webglcontextlost", lost);

    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const trash: { dispose: () => void }[] = [];
    const keep = <T extends { dispose: () => void }>(x: T) => (trash.push(x), x);

    // ── stage ─────────────────────────────────────────────
    const scene = new THREE.Scene();
    const pmrem = new THREE.PMREMGenerator(renderer);
    scene.environment = keep(pmrem.fromScene(new RoomEnvironment(), 0.04).texture);
    scene.environmentIntensity = 0.45;
    pmrem.dispose();

    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
    scene.add(new THREE.HemisphereLight(0xd4ecff, 0x0a1826, 0.75));
    const key = new THREE.DirectionalLight(0xffffff, 2.3);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    Object.assign(key.shadow.camera, { left: -3, right: 3, top: 4, bottom: -1, near: 0.5, far: 20 });
    key.shadow.bias = -0.0004;
    key.shadow.radius = 5;
    scene.add(key, key.target);
    const rim = new THREE.DirectionalLight(0x4fd8ff, 2.2);
    rim.position.set(-3, 3, -4);
    const fill = new THREE.DirectionalLight(0x9fc7ff, 0.5);
    fill.position.set(-3, 1.5, 3);
    scene.add(rim, fill);

    const radial = keep(radialTexture());
    const floor = new THREE.Mesh(keep(new THREE.PlaneGeometry(14, 14)),
      keep(new THREE.MeshStandardMaterial({ color: 0x0a1c2c, roughness: 0.9, envMapIntensity: 0.25, transparent: true, alphaMap: keep(radialTexture(true)), depthWrite: false })));
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.002;
    scene.add(floor);
    const shadowFloor = new THREE.Mesh(keep(new THREE.PlaneGeometry(30, 30)), keep(new THREE.ShadowMaterial({ opacity: 0.42 })));
    shadowFloor.rotation.x = -Math.PI / 2;
    shadowFloor.receiveShadow = true;
    scene.add(shadowFloor);
    // a pool of light that follows the character, with two faint rings
    const spot = new THREE.Group();
    scene.add(spot);
    const additive = (opacity: number, map?: THREE.Texture) => keep(new THREE.MeshBasicMaterial({
      color: CYAN, map, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false, side: THREE.DoubleSide }));
    const pool = new THREE.Mesh(keep(new THREE.PlaneGeometry(3.2, 3.2)), additive(0.16, radial));
    const ring1 = new THREE.Mesh(keep(new THREE.RingGeometry(0.62, 0.635, 96)), additive(0.28));
    const ring2 = new THREE.Mesh(keep(new THREE.RingGeometry(0.9, 0.905, 96)), additive(0.14));
    for (const m of [pool, ring1, ring2]) { m.rotation.x = -Math.PI / 2; m.position.y = 0.004; spot.add(m); }

    // floating dust for depth
    const DUST = 140;
    const dustPos = new Float32Array(DUST * 3);
    for (let i = 0; i < DUST; i++) dustPos.set([(Math.random() - 0.5) * 12, Math.random() * 4.5, -3 + Math.random() * 4.5], i * 3);
    const dustGeo = keep(new THREE.BufferGeometry());
    dustGeo.setAttribute("position", new THREE.BufferAttribute(dustPos, 3));
    const dust = new THREE.Points(dustGeo, keep(new THREE.PointsMaterial({ map: radial, color: 0x9fe6ff, size: 0.035, transparent: true, opacity: 0.4, blending: THREE.AdditiveBlending, depthWrite: false })));
    dust.frustumCulled = false;
    scene.add(dust);

    // ── the character ─────────────────────────────────────
    const skin = keep(new THREE.MeshPhysicalMaterial({ color: 0xf1e8e3, roughness: 0.5, sheen: 1, sheenRoughness: 0.6, sheenColor: new THREE.Color(0xbfe6ff), clearcoat: 0.25, clearcoatRoughness: 0.5 }));
    const jacket = keep(new THREE.MeshPhysicalMaterial({ color: 0x1c2d48, roughness: 0.6, sheen: 0.8, sheenRoughness: 0.5, sheenColor: new THREE.Color(0x4f7fb0) }));
    const pants = keep(new THREE.MeshPhysicalMaterial({ color: 0x232d3d, roughness: 0.7, sheen: 0.4, sheenColor: new THREE.Color(0x5a6b85) }));
    const shoe = keep(new THREE.MeshPhysicalMaterial({ color: 0xf2f5f8, roughness: 0.35, clearcoat: 0.6 }));
    const hairMat = keep(new THREE.MeshPhysicalMaterial({ color: 0x1a2130, roughness: 0.62, clearcoat: 0.12, sheen: 0.7, sheenColor: new THREE.Color(0x4f6f9f) }));
    const eyeMat = keep(new THREE.MeshPhysicalMaterial({ color: 0x0d1220, roughness: 0.08, clearcoat: 1 }));
    const shine = keep(new THREE.MeshBasicMaterial({ color: 0xffffff }));
    const mouthMat = keep(new THREE.MeshStandardMaterial({ color: 0x4a2232, roughness: 0.6 }));
    const light = keep(new THREE.MeshBasicMaterial({ color: CYAN, toneMapped: false }));

    const part = (g: THREE.BufferGeometry, m: THREE.Material, parent: THREE.Object3D, p: [number, number, number] = [0, 0, 0], s?: [number, number, number]) => {
      const mesh = new THREE.Mesh(keep(g), m);
      mesh.position.set(...p);
      if (s) mesh.scale.set(...s);
      mesh.castShadow = true;
      parent.add(mesh);
      return mesh;
    };
    const group = (parent: THREE.Object3D, p: [number, number, number] = [0, 0, 0]) => {
      const g = new THREE.Group();
      g.position.set(...p);
      parent.add(g);
      return g;
    };

    // smooth shapes: a torso turned from a profile curve, and tapered limbs whose joints are balls of the
    // same radius, so elbows and knees bend without gaps
    const lathe = (pts: [number, number][], segs = 48) =>
      new THREE.LatheGeometry(new THREE.SplineCurve(pts.map(([r, y]) => new THREE.Vector2(r, y))).getPoints(48), segs);
    const limb = (parent: THREE.Object3D, mat: THREE.Material, r1: number, r2: number, len: number) => {
      part(new THREE.SphereGeometry(r1, 24, 16), mat, parent);
      part(new THREE.CylinderGeometry(r1, r2, len, 24, 1, true), mat, parent, [0, -len / 2, 0]);
    };

    const char = group(scene);
    const HIP_Y = 1.02;
    const hips = group(char, [0, HIP_Y, 0]);
    part(lathe([[0.001, -0.15], [0.15, -0.135], [0.225, -0.06], [0.24, 0.04], [0.228, 0.15], [0.001, 0.16]]), pants, hips, [0, 0, 0], [1, 1, 0.74]);
    const spine = group(hips);
    part(lathe([[0.25, 0.03], [0.238, 0.16], [0.245, 0.32], [0.272, 0.5], [0.282, 0.6], [0.245, 0.69], [0.16, 0.755], [0.09, 0.785], [0.001, 0.79]]), jacket, spine, [0, 0, 0], [1, 1, 0.72]);
    part(new THREE.BoxGeometry(0.005, 0.62, 0.004), light, spine, [0, 0.38, 0.186]);                  // zip line
    part(new THREE.CircleGeometry(0.03, 24), light, spine, [0.12, 0.55, 0.197]);                      // Jarvis badge
    const collar = part(new THREE.TorusGeometry(0.095, 0.03, 14, 36), jacket, spine, [0, 0.775, 0]);
    collar.rotation.x = Math.PI / 2;
    const collarLight = part(new THREE.TorusGeometry(0.1, 0.006, 8, 40), light, spine, [0, 0.803, 0]);
    collarLight.rotation.x = Math.PI / 2;
    part(new THREE.CylinderGeometry(0.07, 0.08, 0.14, 24), skin, spine, [0, 0.82, 0]);

    const head = group(spine, [0, 0.85, 0]);
    part(new THREE.SphereGeometry(0.36, 64, 48), skin, head, [0, 0.37, 0], [0.92, 1, 0.95]);
    // hair: a cap, fuller at the back, and a soft fringe swept to one side
    const cap = part(new THREE.SphereGeometry(0.378, 64, 32, 0, Math.PI * 2, 0, Math.PI * 0.55), hairMat, head, [0, 0.39, -0.01], [0.95, 1.02, 0.99]);
    cap.rotation.x = -0.42;
    part(new THREE.SphereGeometry(0.36, 48, 32), hairMat, head, [0, 0.41, -0.07], [0.93, 0.92, 0.9]);
    const fringe = part(new THREE.SphereGeometry(0.2, 48, 24), hairMat, head, [-0.05, 0.6, 0.19], [1.3, 0.42, 0.66]);
    fringe.rotation.set(0.55, 0, 0.28);
    const fringe2 = part(new THREE.SphereGeometry(0.14, 32, 16), hairMat, head, [0.15, 0.59, 0.18], [1, 0.45, 0.7]);
    fringe2.rotation.set(0.5, 0, -0.35);
    for (const s of [-1, 1]) part(new THREE.SphereGeometry(0.065, 20, 16), skin, head, [s * 0.325, 0.38, 0], [0.42, 1, 0.75]);   // ears
    const face = group(head, [0, 0.36, 0]);
    const eyes = [-1, 1].map((s) => part(new THREE.SphereGeometry(0.056, 32, 20), eyeMat, face, [s * 0.118, 0.025, 0.3], [0.8, 1.08, 0.5]));
    for (const s of [-1, 1]) part(new THREE.SphereGeometry(0.013, 12, 8), shine, face, [s * 0.118 + 0.016, 0.048, 0.327]);
    const brows = [-1, 1].map((s) => {
      const b = part(new THREE.CapsuleGeometry(0.013, 0.06, 4, 10), hairMat, face, [s * 0.12, 0.118, 0.306]);
      b.rotation.z = Math.PI / 2;
      return b;
    });
    const blushMat = keep(new THREE.MeshBasicMaterial({ color: 0xff9aa8, transparent: true, opacity: 0.22, depthWrite: false }));
    for (const s of [-1, 1]) {
      const c = part(new THREE.CircleGeometry(0.045, 24), blushMat, face, [s * 0.19, -0.06, 0.27]);
      c.rotation.y = s * 0.55;
      c.castShadow = false;
    }
    part(new THREE.SphereGeometry(0.024, 16, 12), skin, face, [0, -0.035, 0.333]);                  // nose
    const mouth = part(new THREE.SphereGeometry(0.05, 24, 12), mouthMat, face, [0, -0.118, 0.31], [1, 0.14, 0.35]);

    const arms: Arm[] = [-1, 1].map((side) => {
      const shoulder = group(spine, [side * 0.29, 0.62, 0]);
      part(new THREE.SphereGeometry(0.088, 24, 16), jacket, shoulder, [0, 0.005, 0]);                 // shoulder
      limb(shoulder, jacket, 0.072, 0.062, 0.29);
      const elbow = group(shoulder, [0, -0.29, 0]);
      limb(elbow, jacket, 0.062, 0.054, 0.26);
      const cuff = part(new THREE.TorusGeometry(0.056, 0.008, 8, 32), light, elbow, [0, -0.25, 0]);
      cuff.rotation.x = Math.PI / 2;
      const wrist = group(elbow, [0, -0.26, 0]);
      part(new THREE.SphereGeometry(0.04, 16, 12), skin, wrist);
      const hand = part(new THREE.SphereGeometry(0.068, 24, 16), skin, wrist, [0, -0.065, 0.005], [0.78, 1.15, 0.6]);
      const thumb = part(new THREE.CapsuleGeometry(0.02, 0.04, 4, 10), skin, wrist, [-side * 0.04, -0.035, 0.032]);
      thumb.rotation.z = -side * 0.6;
      return { shoulder, elbow, wrist, hand, side };
    });
    const legs: Leg[] = [-1, 1].map((side) => {
      const hip = group(hips, [side * 0.115, -0.03, 0]);
      limb(hip, pants, 0.105, 0.08, 0.44);
      const knee = group(hip, [0, -0.44, 0]);
      limb(knee, pants, 0.08, 0.06, 0.44);
      const ankle = group(knee, [0, -0.44, 0]);
      part(new THREE.SphereGeometry(0.06, 16, 12), shoe, ankle);
      const foot = part(new THREE.CapsuleGeometry(0.068, 0.14, 8, 20), shoe, ankle, [0, -0.06, 0.055], [1, 1, 0.85]);
      foot.rotation.x = Math.PI / 2;
      part(new THREE.BoxGeometry(0.1, 0.01, 0.25), light, ankle, [0, -0.118, 0.055]);                 // sole light
      return { hip, knee, ankle, side };
    });

    // the realistic Jarvis (human.ts) loads in the background; the figure above is shown only if it can't load
    let human: Human | null = null, gone = false;
    char.visible = false;
    loadHuman().then((h) => {
      if (gone) return h.dispose();
      human = h;
      scene.add(h.root);
      x = reduced ? 0 : minX - 0.4;   // walks on once he's here
      entering = !reduced;
    }).catch(() => { char.visible = true; });

    // ── data link: hologram over the hand, beam to the card, particle stream ──
    const scanMat = keep(new THREE.MeshBasicMaterial({ color: CYAN, wireframe: true, transparent: true, opacity: 0, toneMapped: false, blending: THREE.AdditiveBlending, depthWrite: false }));
    const scan = new THREE.Mesh(keep(new THREE.IcosahedronGeometry(0.13, 1)), scanMat);
    scene.add(scan);
    const beamGeo = keep(new THREE.BufferGeometry());
    const beamPos = new Float32Array(18);
    beamGeo.setAttribute("position", new THREE.BufferAttribute(beamPos, 3));
    const hi = [0.55, 0.9, 1], lo = [0.05, 0.16, 0.22];
    beamGeo.setAttribute("color", new THREE.BufferAttribute(new Float32Array([...hi, ...lo, ...lo, ...hi, ...lo, ...lo]), 3));
    const beamMat = keep(new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide, toneMapped: false }));
    const beam = new THREE.Mesh(beamGeo, beamMat);
    beam.frustumCulled = false;
    scene.add(beam);
    const N = 40;
    const dotGeo = keep(new THREE.BufferGeometry());
    const dotPos = new Float32Array(N * 3);
    dotGeo.setAttribute("position", new THREE.BufferAttribute(dotPos, 3));
    const dotMat = keep(new THREE.PointsMaterial({ map: radial, color: CYAN, size: 0.07, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }));
    const dots = new THREE.Points(dotGeo, dotMat);
    dots.frustumCulled = false;
    scene.add(dots);
    const dotT = Array.from({ length: N }, () => Math.random());
    const dotS = Array.from({ length: N }, () => Math.random());

    // ── framing: the character fills the layout's empty box; the stage spans the whole page ──
    let W = 1, H = 1, u = 0.01, minX = -3, maxX = 3, side = true;
    const resize = () => {
      W = host.clientWidth || 1;
      H = host.clientHeight || 1;
      renderer.setSize(W, H, false);
      const hr = host.getBoundingClientRect();
      const fr = frame.current?.getBoundingClientRect();
      const fx = fr ? fr.left - hr.left + fr.width / 2 : W / 2;
      const fy = fr ? fr.top - hr.top + fr.height / 2 : H * 0.42;
      const fh = Math.max(160, fr?.height ?? H * 0.5);
      u = 3.0 / fh;                               // world units per pixel: 3 units (head to toe plus margin) fill the box
      const fov = THREE.MathUtils.degToRad(camera.fov);
      const dist = (H * u) / 2 / Math.tan(fov / 2);
      const tilt = 0.12;
      const target = new THREE.Vector3(0, 1.3, 0);
      camera.position.set(0, target.y + Math.sin(tilt) * dist, Math.cos(tilt) * dist);
      camera.lookAt(target);
      camera.aspect = W / H;
      camera.setViewOffset(W, H, W / 2 - fx, H / 2 - fy, W, H);   // put the character's centre on the box's centre
      camera.updateProjectionMatrix();
      minX = -fx * u;
      maxX = (W - fx) * u;
      side = W >= 700;                            // wide: the card goes beside the character; narrow: above it
    };
    const ro = new ResizeObserver(resize);
    ro.observe(host);
    if (frame.current) ro.observe(frame.current);
    resize();

    const gaze = { x: 0, y: 0, tx: 0, ty: 0, at: -1e9 };
    const move = (e: PointerEvent) => {
      gaze.tx = THREE.MathUtils.clamp((e.clientX / window.innerWidth) * 2 - 1, -1, 1);
      gaze.ty = THREE.MathUtils.clamp((e.clientY / window.innerHeight) * 2 - 1, -1, 1);
      gaze.at = performance.now();
    };
    window.addEventListener("pointermove", move, { passive: true });

    // ── motion ────────────────────────────────────────────
    const timer = new THREE.Timer();
    let raf = 0;
    let x = reduced ? 0 : minX - 0.4, targetX = 0, yaw = 0, walkW = 0, phase = 0;
    let entering = !reduced, waveUntil = reduced ? 0 : -1, wanderAt = 25, away = false;
    let bye = false, size = 1, squint = 0, browUp = 0, furrow = 0, talk = 0, open = 0, nextBlink = 2, blinkAt = -1, lookAt = 0, lookAway = 0;
    let prevState = live.current.state, beamOn = 0;
    const arm = arms.map(() => ({ x: 0, z: 0, e: 0 }));
    const v = new THREE.Vector3(), handW = new THREE.Vector3(), headW = new THREE.Vector3();
    const anchor = new THREE.Vector3(), a = new THREE.Vector3(), b = new THREE.Vector3(), mid = new THREE.Vector3();

    const frameFn = () => {
      raf = requestAnimationFrame(frameFn);
      if (document.hidden) return;
      timer.update();
      const dt = Math.min(timer.getDelta(), 0.05);
      const t = timer.getElapsed();
      const k = 1 - Math.exp(-dt * 7);
      const { state: s, focus: f } = live.current;
      const lv = live.current.levels();
      const inCall = s === "connecting" || s === "listening" || s === "thinking" || s === "speaking";
      const working = f === "work" || s === "thinking";
      const holding = !!f;

      if (s === "connecting" && prevState !== "connecting") waveUntil = t + 2.4;   // says hello when you call
      if ((s === "ended" || s === "error") && prevState !== s && prevState !== "idle") bye = true;   // and goodbye, once the card is put away
      prevState = s;

      // where to stand: centre, aside for the card, or a short stroll while idle
      const cardLeft = !!human;   // the realistic one points with his right hand: the card sits on the viewer's left
      // wide: he stands beside the card; a phone: he steps to the right edge, the card takes the left
      const home = holding ? (side ? (cardLeft ? 1.0 : -1.0) : maxX - 0.45) : 0;
      if (inCall || holding || reduced) { targetX = home; away = false; wanderAt = Math.max(wanderAt, t + 15); }
      else if (!entering && t > wanderAt && walkW < 0.05) {
        away = !away;
        targetX = away ? THREE.MathUtils.clamp((Math.random() < 0.5 ? -1 : 1) * (0.8 + Math.random() * 0.8), minX + 0.8, maxX - 0.8) : home;
        wanderAt = t + (away ? 5 + Math.random() * 4 : 20 + Math.random() * 15);
      }
      else if (!away && !entering) targetX = home;   // back to the middle once a call or a card is done
      const dx = targetX - x;
      const walking = Math.abs(dx) > 0.03 ? 1 : 0;
      walkW += (walking - walkW) * (1 - Math.exp(-dt * 5));
      const speed = human ? 1.9 : 1.15;
      x += Math.sign(dx) * Math.min(Math.abs(dx), speed * dt * Math.max(walkW, 0.15) * walking);
      phase += dt * Math.PI * 2 * 0.85 * walkW;   // stride matched to speed so the feet don't slide
      if (entering && !walking) { entering = false; waveUntil = t + 2.2; }
      const body = human ? human.root : char;
      body.position.x = x;
      size += ((holding && !side ? 0.55 : 1) - size) * k * 0.5;   // on a phone he steps back a little, beside the card
      body.scale.setScalar(size);
      const yawTarget = walking ? Math.sign(dx) * (human ? Math.PI / 2 : 1.15) : (holding && side ? (cardLeft ? -0.35 : 0.3) : 0) + gaze.x * 0.18;
      yaw += (yawTarget - yaw) * k * 0.6;
      body.rotation.y = yaw;
      spot.position.x += (x - spot.position.x) * k * 0.5;
      key.position.set(x + 2.5, 5, 4);
      key.target.position.set(x, 1, 0);

      // pointer, or a glance around now and then
      if (performance.now() - gaze.at > 4000) {
        if (t > lookAt) { lookAt = t + 2.5 + Math.random() * 3; gaze.tx = inCall ? (Math.random() - 0.5) * 0.3 : (Math.random() - 0.5) * 1.2; gaze.ty = (Math.random() - 0.5) * 0.4; }
      }
      gaze.x += (gaze.tx - gaze.x) * k * 0.5;
      gaze.y += (gaze.ty - gaze.y) * k * 0.5;

      talk += ((s === "speaking" ? Math.min(1, lv.jarvis * 1.8) : 0) - talk) * (1 - Math.exp(-dt * 3));
      if (bye && !holding && !walking) { bye = false; waveUntil = t + 2.4; }
      const waving = t < waveUntil && !walking;
      if (holding && t > lookAway) lookAway = t + 2 + Math.random() * 2;
      const atCard = working || (holding && lookAway - t > 1.2);

      if (human) {
        human.update({ dt, t, state: s, jarvis: lv.jarvis, you: lv.you, walking: !!walking, walkW, waving, working, holding,
          lookAtCard: atCard && side, cardSide: -1, gazeX: gaze.x, gazeY: gaze.y, moveSpeed: speed * size });
      } else {
      // legs: a walk cycle that fades in and out
      const A = 0.5 * walkW;
      for (const l of legs) {
        const p = phase + (l.side > 0 ? 0 : Math.PI);
        l.hip.rotation.x = -A * Math.sin(p);
        l.knee.rotation.x = 0.95 * walkW * Math.max(0, Math.cos(p)) + 0.03;
        l.ankle.rotation.x = -l.knee.rotation.x * 0.35 + A * 0.25 * Math.sin(p);
      }
      const breath = Math.sin(t * 1.5);
      hips.position.y = HIP_Y - 0.035 * walkW * Math.abs(Math.sin(phase)) - 0.004 * (1 - walkW) * (1 + breath);
      hips.position.x = (1 - walkW) * 0.015 * Math.sin(t * 0.45) * (reduced ? 0 : 1);
      hips.rotation.z = 0.035 * walkW * Math.sin(phase) + (1 - walkW) * 0.015 * Math.sin(t * 0.45);
      spine.rotation.y = 0.1 * walkW * Math.sin(phase);
      spine.rotation.x = 0.05 * walkW + 0.012 * breath + (s === "listening" ? 0.04 : 0);
      spine.rotation.z = -hips.rotation.z * 0.8;

      // arms: swing when walking, gesture while talking, wave hello, hold the data up
      arms.forEach((r, i) => {
        const p = phase + (r.side > 0 ? 0 : Math.PI);
        let tx = 0.04 + 0.8 * A * Math.sin(p), tz = r.side * 0.1, te = -0.2 - 0.3 * walkW;
        if (s === "listening") { tx -= 0.1; te -= 0.15; }
        if (talk > 0.02 && !walking) {
          const g = talk * (0.55 + 0.45 * Math.sin(t * 1.7 + i * 2.1));
          tx = -0.25 - 0.55 * g; tz = r.side * (0.15 + 0.15 * g); te = -0.75 - 0.6 * g;
        }
        if (r.side > 0 && waving) { tx = -0.15; tz = 2.5; te = -0.35 + 0.4 * Math.sin(t * 10); }
        if (r.side > 0 && holding) {
          if (side) { tx = -1.25; tz = 0.35; te = -0.45; }
          else { tx = -2.5; tz = 0.25; te = -0.2; }
        }
        arm[i].x += (tx - arm[i].x) * k;
        arm[i].z += (tz - arm[i].z) * k;
        arm[i].e += (te - arm[i].e) * k;
        r.shoulder.rotation.set(arm[i].x, 0, arm[i].z);
        r.elbow.rotation.x = arm[i].e;
        r.wrist.rotation.set(talk * 0.3 * Math.sin(t * 2.3 + i), 0, 0);
      });

      // head: looks at you, the card, or where it's walking; nods along
      let hy = walking ? 0 : gaze.x * 0.4;
      let hx = gaze.y * 0.2;
      let hz = 0;
      if (atCard) { hy = side ? 0.5 : 0; hx = side ? 0.08 : -0.35; }
      if (s === "listening") { hz = 0.09; hx += lv.you * 0.15; }
      if (s === "speaking") { hx += 0.05 * Math.sin(t * 4.3) * talk; hy += 0.05 * Math.sin(t * 2.1) * talk; }
      head.rotation.x += (hx - head.rotation.x) * k;
      head.rotation.y += (hy - head.rotation.y) * k;
      head.rotation.z += (hz - head.rotation.z) * k;

      // face: blinks, brows, and a mouth that moves with Jarvis's voice
      if (t > nextBlink) { blinkAt = t; nextBlink = t + 2.5 + Math.random() * 3.5; }
      const bl = blinkAt >= 0 && t - blinkAt < 0.15 ? Math.max(0.08, Math.abs(Math.cos(((t - blinkAt) / 0.15) * Math.PI))) : 1;
      // expressions ease in and out instead of snapping
      squint += ((working ? 1 : 0) - squint) * k * 0.6;
      browUp += ((s === "listening" ? 1 : 0) + talk * 1.4 - browUp) * k * 0.6;
      furrow += ((working ? 0.18 : 0) - furrow) * k * 0.6;
      eyes.forEach((e) => { e.scale.y = 1.05 * bl * (1 - 0.25 * squint); });
      face.position.x = gaze.x * 0.01;
      brows.forEach((br, i) => {
        br.position.y = 0.115 + 0.01 * browUp;
        br.rotation.z = Math.PI / 2 + (i === 0 ? 1 : -1) * furrow;
      });
      open += ((s === "speaking" ? Math.min(1, lv.jarvis * 2.2) : 0) - open) * Math.min(1, dt * 25);
      mouth.scale.set(1.05 - open * 0.25, 0.14 + open * 0.8, 0.35);
      }

      // dust drifts up
      for (let i = 0; i < DUST; i++) {
        const y = dustPos[i * 3 + 1] + dt * 0.06;
        dustPos[i * 3 + 1] = y > 4.5 ? 0 : y;
      }
      dustGeo.attributes.position.needsUpdate = true;

      // the card follows the hand; the beam and particles join them
      if (human) { human.hand(handW); human.headTop(headW); }
      else { arms[1].hand.getWorldPosition(handW); head.getWorldPosition(headW).add(v.set(0, 1.15, 0)); }
      const el = card.current;
      const cw = el?.offsetWidth ?? 0, ch = el?.offsetHeight ?? 0;
      anchor.copy(handW).add(v.set(side && !cardLeft ? 0.45 : -0.45, 0.3, 0));
      if (el && holding) {   // a card that's fading out stays where it was
        // place the card at the anchor, kept on screen (below the top bar); then aim the beam where it really is
        v.copy(anchor).project(camera);
        const px = ((v.x + 1) / 2) * W, py = ((1 - v.y) / 2) * H;
        const left = side ? THREE.MathUtils.clamp(cardLeft ? px - cw : px, 8, Math.max(8, W - cw - 8)) : 12;
        const top = THREE.MathUtils.clamp(side ? py - ch / 2 : 60, 60, Math.max(60, H - ch - 8));
        el.style.transform = `translate(${left}px, ${top}px)`;
        el.style.visibility = "visible";
        const sx = side && !cardLeft ? left : left + cw, sy = top + ch / 2;   // the beam meets the card's edge nearest him
        anchor.set((sx / W) * 2 - 1, 1 - (sy / H) * 2, v.z).unproject(camera);
      }
      a.copy(anchor).add(v.set(0, ch * u * 0.42, 0));
      b.copy(anchor).add(v.set(0, -ch * u * 0.42, 0));
      const apex = handW.clone().add(v.set(0, 0.06, 0.05));
      mid.copy(a).lerp(b, working ? 0.5 + 0.5 * Math.sin(t * 2.4) : 0.5);   // a scan line runs along the card while working
      [apex, a, mid, apex, mid, b].forEach((p, i) => beamPos.set([p.x, p.y, p.z], i * 3));
      beamGeo.attributes.position.needsUpdate = true;
      const beamTo = (working ? 0.7 : holding ? 0.35 : 0) * (el ? 1 : 0) * (0.85 + Math.random() * 0.15);
      beamOn += (beamTo - beamOn) * (beamTo > beamOn ? k : Math.min(1, k * 3));   // switches off faster than on
      beamMat.opacity = beamOn;
      scanMat.opacity += ((working ? 0.85 : 0) - scanMat.opacity) * k;
      scan.position.copy(handW).add(v.set(0, 0.2, 0.05));
      scan.rotation.set(t * 1.3, t * 1.9, 0);
      for (let i = 0; i < N; i++) {
        dotT[i] += dt * (0.5 + (i % 5) * 0.08);
        if (dotT[i] > 1) { dotT[i] -= 1; dotS[i] = Math.random(); }
        const p = working ? dotT[i] : 1 - dotT[i];
        const q = a.clone().lerp(b, dotS[i]).lerp(apex, p);
        dotPos.set([q.x, q.y, q.z], i * 3);
      }
      dotGeo.attributes.position.needsUpdate = true;
      dotMat.opacity += ((holding && el ? (working ? 0.9 : 0.4) : 0) - dotMat.opacity) * k;

      renderer.render(scene, camera);
    };
    frameFn();

    return () => {
      cancelAnimationFrame(raf);
      gone = true;
      human?.dispose();
      ro.disconnect();
      window.removeEventListener("pointermove", move);
      renderer.domElement.removeEventListener("webglcontextlost", lost);
      trash.forEach((d) => d.dispose());
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return <div ref={ref} className="stage-3d" aria-hidden="true" />;
}
