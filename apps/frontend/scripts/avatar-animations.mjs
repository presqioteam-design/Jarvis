// Mixamo FBX clips -> one animations.json for the avatar: bone names mapped, scaled to the avatar,
// the walk kept in place (its forward speed reported), values rounded. Also poses the avatar's skeleton
// with each clip to check the fit (where the hands end up).
import fs from "fs";
import path from "path";
const root = new URL("../../../node_modules/three", import.meta.url).pathname;   // the repo's three.js
const THREE = await import(root + "/build/three.module.js");
const { FBXLoader } = await import(root + "/examples/jsm/loaders/FBXLoader.js");
const dir = process.argv[2] ?? new URL("../avatar-source", import.meta.url).pathname;
const outFile = process.argv[3] ?? new URL("../public/avatar/animations.json", import.meta.url).pathname;
const CLIPS = {
  idle: "Breathing Idle.fbx", walk: "Walking.fbx", wave: "Waving.fbx",
  talk1: "Talking.fbx", talk2: "Talking (1).fbx", talk3: "Talking (2).fbx",
  nod1: "Head Nod Yes.fbx", nod2: "Thoughtful Head Nod.fbx", think: "Thinking.fbx",
  point2: "Pointing.fbx", beckon: "Beckoning.fbx", thanks: "Thankful.fbx",
};
// the avatar's skeleton from the GLB (rest pose), to size and check the clips
const glb = fs.readFileSync(path.join(dir, "jarvis.glb"));
const jlen = glb.readUInt32LE(12), J = JSON.parse(glb.subarray(20, 20 + jlen).toString());
const objs = J.nodes.map((n) => { const o = new THREE.Bone(); o.name = n.name || "";
  if (n.translation) o.position.fromArray(n.translation); if (n.rotation) o.quaternion.fromArray(n.rotation); if (n.scale) o.scale.fromArray(n.scale); return o; });
J.nodes.forEach((n, i) => (n.children || []).forEach((c) => objs[i].add(objs[c])));
const rig = new THREE.Group(); J.scenes[0].nodes.forEach((i) => rig.add(objs[i]));
const bone = (name) => rig.getObjectByName(name);
const hipsY = bone("Hips").position.y;

const loader = new FBXLoader();
const out = { clips: [], walkSpeed: 0 };
for (const [key, file] of Object.entries(CLIPS)) {
  const buf = fs.readFileSync(path.join(dir, file));
  const fbx = loader.parse(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength), dir + "/");
  const clip = fbx.animations[0];
  const tracks = [];
  let mixHipsY = null;
  for (const t of clip.tracks) {
    const [b, prop] = t.name.replace(/^mixamorig:?/, "").split(".");
    if (!bone(b) || prop === "scale") continue;
    if (prop === "position" && b !== "Hips") continue;   // only the hips move; other bones keep the avatar's proportions
    let values = Array.from(t.values);
    if (prop === "position") {
      mixHipsY ??= values[1];
      const s = hipsY / values[1], n = values.length / 3;
      const x0 = values[0], z0 = values[2], dx = values[(n - 1) * 3] - x0, dz = values[(n - 1) * 3 + 2] - z0;
      const dur = t.times[n - 1] - t.times[0];
      if (key === "walk") out.walkSpeed = +(Math.hypot(dx, dz) * s / dur).toFixed(4);   // metres per second, avatar size
      values = values.map((v, i) => {
        const k = Math.floor(i / 3), f = (t.times[k] - t.times[0]) / (dur || 1), c = i % 3;
        if (c === 1) return v * s;
        const base = c === 0 ? x0 + (key === "walk" ? dx * f : 0) : z0 + (key === "walk" ? dz * f : 0);
        return (v - base) * s * (key === "walk" ? 1 : 0.6);   // in place; a little natural sway kept
      });
    }
    const round = prop === "quaternion" ? 1e4 : 1e4;
    tracks.push({ name: `${b}.${prop}`, type: prop === "quaternion" ? "quaternion" : "vector",
      times: Array.from(t.times, (x) => Math.round(x * 1000) / 1000), values: values.map((v) => Math.round(v * round) / round) });
  }
  const json = { name: key, duration: +clip.duration.toFixed(3), tracks };
  out.clips.push(json);
  // fit check: pose the avatar mid-clip and measure the hands (relative to the hips, metres; +x = his left, +z = forward)
  const c3 = THREE.AnimationClip.parse({ ...json, tracks: json.tracks.map((t) => ({ ...t })) });
  const mixer = new THREE.AnimationMixer(rig);
  mixer.clipAction(c3).play(); mixer.update(json.duration * 0.55); rig.updateMatrixWorld(true);
  const hp = bone("Hips").getWorldPosition(new THREE.Vector3());
  const L = bone("LeftHand").getWorldPosition(new THREE.Vector3()).sub(hp), R = bone("RightHand").getWorldPosition(new THREE.Vector3()).sub(hp);
  const head = bone("Head").getWorldPosition(new THREE.Vector3());
  console.log(`${key.padEnd(7)} ${json.duration.toFixed(1)}s ${String(tracks.length).padStart(3)} tracks | head y ${head.y.toFixed(2)} | L hand ${L.toArray().map((v) => v.toFixed(2))} | R hand ${R.toArray().map((v) => v.toFixed(2))}`);
  mixer.stopAllAction(); mixer.uncacheRoot(rig);
}
fs.writeFileSync(outFile, JSON.stringify(out));
console.log("hips rest y", hipsY.toFixed(3), "| walk speed", out.walkSpeed, "m/s | file", (fs.statSync(outFile).size / 1e6).toFixed(2), "MB");
