import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";

/**
 * The realistic Jarvis: an Avaturn model (public/avatar/jarvis.glb) moved by Mixamo motion capture
 * (public/avatar/animations.json, made by scripts/avatar-animations.mjs from apps/frontend/avatar-source/).
 *
 * The stage (Avatar.tsx) decides what he's doing; this blends the matching clips (walk, idle, talking
 * gestures, nods, thinking, pointing, waving) and layers what clips can't know: eye contact and head turns,
 * blinking, expressions, and lip sync driven by the loudness of Jarvis's actual voice.
 */
export type HumanCtx = {
  dt: number;
  t: number;
  state: string;            // the call state
  jarvis: number;           // 0..1 loudness of Jarvis's voice
  you: number;              // 0..1 loudness of your voice
  walking: boolean;
  walkW: number;            // 0..1, eases in and out
  waving: boolean;
  working: boolean;         // a command is running
  holding: boolean;         // a card is up
  lookAtCard: boolean;
  cardSide: number;         // -1: the card is on the viewer's left
  gazeX: number;            // -1..1, where to look (viewer's left .. right)
  gazeY: number;
  moveSpeed: number;        // world units / s he's walking at
};

export type Human = {
  root: THREE.Group;
  height: number;
  update: (c: HumanCtx) => void;
  hand: (out: THREE.Vector3) => THREE.Vector3;   // the right hand, which points at the card
  headTop: (out: THREE.Vector3) => THREE.Vector3;
  dispose: () => void;
};

const HEIGHT = 2.55;   // world units, the size the stage was built for
const FADE = 0.4;
// seconds of a clip where the pose is held (measured: the right hand stays up), looped on their own
const HOLD: Record<string, [number, number]> = { think: [0.9, 2.6], point2: [0.6, 1.75] };
const VISEMES = ["viseme_aa", "viseme_E", "viseme_I", "viseme_O", "viseme_U", "viseme_aa", "viseme_E", "viseme_O",
  "viseme_SS", "viseme_DD", "viseme_nn", "viseme_kk", "viseme_RR", "viseme_CH", "viseme_TH", "viseme_FF", "viseme_PP"];

type ClipJSON = { name: string; duration: number; tracks: { name: string; type: string; times: number[]; values: number[] }[] };

export async function loadHuman(base = "/avatar/"): Promise<Human> {
  const loader = new GLTFLoader();
  loader.setMeshoptDecoder(MeshoptDecoder);
  const [gltf, anims] = await Promise.all([
    loader.loadAsync(base + "jarvis.glb"),
    fetch(base + "animations.json").then((r) => {
      if (!r.ok) throw new Error(`animations: ${r.status}`);
      return r.json() as Promise<{ clips: ClipJSON[]; walkSpeed: number }>;
    }),
  ]);

  const model = gltf.scene;
  const root = new THREE.Group();
  root.add(model);
  const box = new THREE.Box3().setFromObject(model);
  const scale = HEIGHT / Math.max(0.5, box.max.y - box.min.y);
  model.scale.setScalar(scale);
  model.position.y = -box.min.y * scale;

  // every face shape by name, on every mesh that has it (head, teeth, tongue, lashes...)
  const shapes = new Map<string, { inf: number[]; i: number }[]>();
  model.traverse((o) => {
    const m = o as THREE.SkinnedMesh;
    if (!m.isMesh) return;
    m.castShadow = true;
    m.frustumCulled = false;   // skinned: its bounds move with the animation
    const mat = m.material as THREE.MeshStandardMaterial;
    if (mat && "envMapIntensity" in mat) mat.envMapIntensity = 0.8;
    if (m.morphTargetDictionary && m.morphTargetInfluences) {
      for (const [name, i] of Object.entries(m.morphTargetDictionary)) {
        if (!shapes.has(name)) shapes.set(name, []);
        shapes.get(name)!.push({ inf: m.morphTargetInfluences, i });
      }
    }
  });
  const face: Record<string, number> = {};   // the current value of each shape we drive
  const setShape = (name: string, v: number) => {
    face[name] = v;
    for (const s of shapes.get(name) ?? []) s.inf[s.i] = v;
  };
  const ease = (name: string, to: number, rate: number, dt: number) => {
    const cur = face[name] ?? 0;
    setShape(name, cur + (to - cur) * Math.min(1, dt * rate));
  };

  const bone = (name: string) => model.getObjectByName(name) as THREE.Bone | undefined;
  const neck = bone("Neck"), head = bone("Head"), handR = bone("RightHand");

  // motion capture
  const mixer = new THREE.AnimationMixer(model);
  const actions: Record<string, THREE.AnimationAction> = {};
  for (const c of anims.clips) {
    let clip = THREE.AnimationClip.parse({ ...c, uuid: THREE.MathUtils.generateUUID(), blendMode: THREE.NormalAnimationBlendMode } as Parameters<typeof THREE.AnimationClip.parse>[0]);
    const hold = HOLD[c.name];
    // a gesture that's held (hand on chin, pointing): loop just the held part, easing back and forth
    if (hold) clip = THREE.AnimationUtils.subclip(clip, c.name, Math.round(hold[0] * 30), Math.round(hold[1] * 30), 30);
    const a = mixer.clipAction(clip);
    a.setLoop(hold ? THREE.LoopPingPong : THREE.LoopRepeat, Infinity);
    actions[c.name] = a;
  }
  const walkRoot = (anims.walkSpeed || 1.7) * scale;   // how fast the walk clip's feet travel, in world units / s
  let current = actions.idle;
  current?.play();
  let currentName = "idle", since = 0, talkPick = 0, nextNod = 0;
  const play = (name: string, t: number) => {
    const next = actions[name];
    if (!next || name === currentName) return;
    const fade = HOLD[name] || HOLD[currentName] ? 0.7 : FADE;   // raising or lowering a hand takes a moment
    next.reset().setEffectiveTimeScale(1).setEffectiveWeight(1).fadeIn(fade).play();
    current?.fadeOut(fade);
    current = next;
    currentName = name;
    since = t;
  };

  // face timing
  let nextBlink = 1.5, blinkAt = -1, viseme = "viseme_sil", nextViseme = 0, talking = 0;
  const qa = new THREE.Quaternion(), qb = new THREE.Quaternion(), X = new THREE.Vector3(1, 0, 0), Y = new THREE.Vector3(0, 1, 0);
  const look = { x: 0, y: 0 };

  const update = (c: HumanCtx) => {
    const { dt, t } = c;
    const speaking = c.state === "speaking" && c.jarvis > 0.03;
    talking += ((c.state === "speaking" ? 1 : 0) - talking) * Math.min(1, dt * 2.5);   // stays up between words

    // which clip: one at a time, crossfaded; talking gestures rotate so they don't repeat
    const held = t - since;
    let want = "idle";
    if (c.walkW > 0.5) want = "walk";
    else if (c.waving) want = "wave";
    else if (c.working) want = "think";
    else if (c.holding && (!talking || Math.sin(t * 0.6) > 0)) want = "point2";   // points at the card, then talks it through
    else if (talking > 0.3) want = currentName.startsWith("talk") && held < (actions[currentName]?.getClip().duration ?? 4) * 2 ? currentName : `talk${1 + (talkPick++ % 3)}`;
    else if (c.state === "listening" && c.you > 0.25 && t > nextNod) { want = Math.random() < 0.5 ? "nod1" : "nod2"; nextNod = t + 5 + Math.random() * 4; }
    else if (currentName.startsWith("nod") && held < (actions[currentName]?.getClip().duration ?? 2.5)) want = currentName;   // let a nod finish
    if (want !== currentName && (held > 0.5 || want === "walk" || currentName === "walk")) play(want, t);
    // the walk clip runs at the speed he actually moves, so the feet don't slide
    if (actions.walk) actions.walk.setEffectiveTimeScale(THREE.MathUtils.clamp(c.moveSpeed / walkRoot, 0.4, 1.3));
    mixer.update(dt);

    // eye contact and head turns, added on top of the clip (neck takes a little, the head the rest)
    const tx = c.lookAtCard ? c.cardSide * 0.9 : c.walking ? 0 : c.gazeX;
    const ty = c.lookAtCard ? -0.1 : c.gazeY;
    look.x += (tx - look.x) * Math.min(1, dt * 4);
    look.y += (ty - look.y) * Math.min(1, dt * 4);
    const yaw = look.x * 0.55, pitch = look.y * 0.25 + (c.state === "listening" ? 0.04 : 0);
    if (neck) neck.quaternion.multiply(qa.setFromAxisAngle(Y, yaw * 0.35)).multiply(qb.setFromAxisAngle(X, pitch * 0.3));
    if (head) head.quaternion.multiply(qa.setFromAxisAngle(Y, yaw * 0.65)).multiply(qb.setFromAxisAngle(X, pitch * 0.7));
    // the eyes lead the head
    const ex = THREE.MathUtils.clamp(look.x * 1.2, -1, 1), ey = THREE.MathUtils.clamp(-look.y * 1.2, -1, 1);
    ease("eyeLookOutLeft", Math.max(0, ex) * 0.6, 12, dt);   // his left eye looks out when you're to the viewer's right
    ease("eyeLookInRight", Math.max(0, ex) * 0.6, 12, dt);
    ease("eyeLookInLeft", Math.max(0, -ex) * 0.6, 12, dt);
    ease("eyeLookOutRight", Math.max(0, -ex) * 0.6, 12, dt);
    ease("eyeLookUpLeft", Math.max(0, ey) * 0.5, 12, dt);
    ease("eyeLookUpRight", Math.max(0, ey) * 0.5, 12, dt);
    ease("eyeLookDownLeft", Math.max(0, -ey) * 0.5, 12, dt);
    ease("eyeLookDownRight", Math.max(0, -ey) * 0.5, 12, dt);

    // blinking: every few seconds, sometimes twice
    if (t > nextBlink) { blinkAt = t; nextBlink = t + (Math.random() < 0.15 ? 0.3 : 2.5 + Math.random() * 3.5); }
    const bt = (t - blinkAt) / 0.16;
    const blink = blinkAt >= 0 && bt < 1 ? Math.sin(bt * Math.PI) : 0;
    setShape("eyeBlinkLeft", blink);
    setShape("eyeBlinkRight", blink);

    // expressions: friendly at rest, attentive while listening, focused while working, lively while talking
    const listening = c.state === "listening" ? 1 : 0;
    ease("mouthSmileLeft", c.working ? 0 : 0.16 + listening * 0.12, 3, dt);
    ease("mouthSmileRight", c.working ? 0 : 0.16 + listening * 0.12, 3, dt);
    ease("browInnerUp", listening * 0.25 + talking * 0.15 + (speaking ? c.jarvis * 0.25 : 0), 5, dt);
    ease("browDownLeft", c.working ? 0.35 : 0, 4, dt);
    ease("browDownRight", c.working ? 0.35 : 0, 4, dt);
    ease("eyeSquintLeft", c.working ? 0.3 : 0.05, 4, dt);
    ease("eyeSquintRight", c.working ? 0.3 : 0.05, 4, dt);
    ease("mouthPressLeft", c.working ? 0.25 : 0, 4, dt);
    ease("mouthPressRight", c.working ? 0.25 : 0, 4, dt);

    // lip sync: mouth shapes change every ~80 ms while there's sound, opening with the loudness
    if (speaking && t > nextViseme) {
      viseme = VISEMES[Math.floor(Math.random() * VISEMES.length)];
      nextViseme = t + 0.06 + Math.random() * 0.06;
    } else if (!speaking) viseme = "viseme_sil";
    const amp = speaking ? THREE.MathUtils.clamp(c.jarvis * 1.6, 0.25, 1) : 0;
    for (const v of new Set(VISEMES)) ease(v, v === viseme ? amp * 0.85 : 0, 18, dt);
    ease("jawOpen", speaking ? c.jarvis * 0.35 : 0, 16, dt);
  };

  return {
    root, height: HEIGHT, update,
    hand: (out) => (handR ? handR.getWorldPosition(out) : root.getWorldPosition(out).add(new THREE.Vector3(0, HEIGHT * 0.6, 0))),
    headTop: (out) => (head ? head.getWorldPosition(out).add(new THREE.Vector3(0, 0.35 * root.scale.y, 0)) : root.getWorldPosition(out).add(new THREE.Vector3(0, HEIGHT, 0))),
    dispose: () => {
      mixer.stopAllAction();
      model.traverse((o) => {
        const m = o as THREE.Mesh;
        if (!m.isMesh) return;
        m.geometry.dispose();
        for (const mat of ([] as THREE.Material[]).concat(m.material)) {
          for (const v of Object.values(mat)) if (v instanceof THREE.Texture) v.dispose();
          mat.dispose();
        }
      });
    },
  };
}
