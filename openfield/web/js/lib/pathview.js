// Camera-path geometry for the Move Pad: pure functions from poses to SVG coordinates.
//
// Rig space (see engine/rig.py): subject at the origin, the camera starts at z = -1 facing +z,
// x is to the camera's right, y is up. The top view plots (x, z), the side view plots (z, y).

const VIEW = 100; // SVG user units; callers scale the <svg> with CSS
const PAD = 12;

/** Bounds covering every pose, the subject at the origin, and at least +-1.3 so tiny moves keep scale. */
export function bounds(poses, a, b) {
  const values = poses.flatMap((p) => [p[a], p[b]]).concat([0, 0]);
  const half = Math.max(1.3, ...values.map((v) => Math.abs(v)));
  return { min: -half, max: half };
}

function scaler({ min, max }) {
  const span = max - min;
  return (v) => PAD + ((v - min) / span) * (VIEW - 2 * PAD);
}

/**
 * Project a pose list to a view. horizontal/vertical name the pose fields on each axis;
 * `flipVertical` makes +y point up on screen (SVG's y grows downward).
 */
export function project(poses, horizontal, vertical, { flipVertical = false } = {}) {
  const box = bounds(poses, horizontal, vertical);
  const sx = scaler(box);
  const sy = scaler(box);
  const point = (p) => ({
    x: sx(p[horizontal]),
    y: flipVertical ? VIEW - sy(p[vertical]) : sy(p[vertical]),
  });
  const points = poses.map(point);
  return {
    points,
    origin: point({ [horizontal]: 0, [vertical]: 0 }),
    d: points.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(" "),
  };
}

/** Top view: camera path on the floor plane, z up the page so the camera starts at the bottom. */
export const topView = (poses) => project(poses, "x", "z", { flipVertical: true });

/** Side view: distance across, height up. */
export const sideView = (poses) => project(poses, "z", "y", { flipVertical: true });

/**
 * Like `project`, but scaled to the path itself, for tiles and previews where the shape matters more
 * than the distance. The subject stays in frame, so the path is still read against it.
 */
export function fitView(poses, horizontal, vertical, { pad = 22, minHalf = 0.6, includeOrigin = true } = {}) {
  const xs = poses.map((p) => p[horizontal]).concat(includeOrigin ? [0] : []);
  const ys = poses.map((p) => p[vertical]).concat(includeOrigin ? [0] : []);
  const mid = (list) => (Math.min(...list) + Math.max(...list)) / 2;
  const span = (list) => Math.max(...list) - Math.min(...list);
  const [cx, cy] = [mid(xs), mid(ys)];
  const scale = (VIEW / 2 - pad) / Math.max(minHalf, span(xs) / 2, span(ys) / 2);
  const point = (p) => ({ x: VIEW / 2 + (p[horizontal] - cx) * scale, y: VIEW / 2 - (p[vertical] - cy) * scale });
  const points = poses.map(point);
  return {
    points,
    origin: point({ [horizontal]: 0, [vertical]: 0 }),
    d: points.map((q, i) => `${i ? "L" : "M"}${q.x.toFixed(2)} ${q.y.toFixed(2)}`).join(" "),
  };
}

export const topFit = (poses, options) => fitView(poses, "x", "z", options);
export const sideFit = (poses, options) => fitView(poses, "z", "y", options);

/** Points at the given fractions (0..1) along the path, for numbered anchor markers. They land exactly where the
 * camera is when the shot reaches each still (`pointAt` at k / (count - 1)). */
export function anchorsAlong(view, count) {
  const n = view.points.length;
  if (count <= 1 || n === 0) return count === 1 && n ? [view.points[0]] : [];
  return Array.from({ length: count }, (_, i) => pointAt(view, i / (count - 1)));
}

// -- timing: where the camera is a fraction t (0..1) of the way through the take --------------------------------------
// A move's path is sampled at equal key spans (engine/rig.py Move.path) and a keyframed take is anchors - 1 equal
// segments, so still k sits at exactly k / (anchors - 1) of the video: interpolating by index is the take's own timing.

const POSE_KEYS = ["x", "y", "z", "yaw", "pitch", "fov"];
const clamp01 = (t) => (Number.isFinite(t) ? Math.min(1, Math.max(0, t)) : 0);
function sampleAt(n, t) {
  const s = clamp01(t) * (n - 1);
  const i = Math.min(Math.floor(s), n - 2);
  return [i, s - i];
}

/** The camera pose a fraction t through the move, every field interpolated. */
export function poseAt(poses, t) {
  if (!poses?.length) return null;
  if (poses.length === 1) return { ...poses[0] };
  const [i, f] = sampleAt(poses.length, t);
  const [a, b] = [poses[i], poses[i + 1]];
  return Object.fromEntries(POSE_KEYS.map((k) => [k, a[k] + (b[k] - a[k]) * f]));
}

/** The point a fraction t along a projected view, with the same timing as `poseAt`. */
export function pointAt(view, t) {
  const n = view.points.length;
  if (n < 2) return n ? { ...view.points[0] } : null;
  const [i, f] = sampleAt(n, t);
  const [a, b] = [view.points[i], view.points[i + 1]];
  return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f };
}

/** How many of `count` evenly spaced stills the shot has reached at t: the first at once, the last at the end. */
export function litCount(count, t) {
  if (count <= 1) return Math.max(0, count);
  return Math.min(count, Math.floor(clamp01(t) * (count - 1) + 1e-6) + 1);
}

// -- the previs stage: the set seen from above and to one side ----------------------------------------------------------

const RAD = Math.PI / 180;
/** Viewing angles (degrees) and the floor's height in rig units: y = 0 is the camera's starting height, about eye level. */
export const STAGE = { az: 58, el: 24, floor: -0.5 };

/** A rig-space point as seen from the stage view (orthographic): screen x to the right, screen y down. The camera's
 * starting mark (z = -1) lands in front of the subject, lower on screen; height goes straight up. */
export function stagePoint(p, { az = STAGE.az, el = STAGE.el } = {}) {
  const [a, e] = [az * RAD, el * RAD];
  const x1 = p.x * Math.cos(a) - p.z * Math.sin(a);
  const z1 = p.x * Math.sin(a) + p.z * Math.cos(a);
  return { x: x1, y: -(p.y * Math.cos(e) + z1 * Math.sin(e)) };
}

/** The camera as a pyramid in rig space: its position and the four corners of its frame `depth` ahead, `fov` being the
 * horizontal angle (yaw 0 looks along +z, positive pitch looks up, as in engine/rig.py). */
export function frustum(pose, { depth = 0.3, aspect = 16 / 9 } = {}) {
  const [yaw, pitch] = [pose.yaw * RAD, pose.pitch * RAD];
  const f = { x: Math.sin(yaw) * Math.cos(pitch), y: Math.sin(pitch), z: Math.cos(yaw) * Math.cos(pitch) };
  const r = { x: Math.cos(yaw), y: 0, z: -Math.sin(yaw) };
  const u = { x: f.y * r.z - f.z * r.y, y: f.z * r.x - f.x * r.z, z: f.x * r.y - f.y * r.x };
  const w = depth * Math.tan((pose.fov * RAD) / 2);
  const h = w / aspect;
  const c = { x: pose.x + f.x * depth, y: pose.y + f.y * depth, z: pose.z + f.z * depth };
  const at = (sx, sy) => ({ x: c.x + r.x * w * sx + u.x * h * sy, y: c.y + r.y * w * sx + u.y * h * sy, z: c.z + r.z * w * sx + u.z * h * sy });
  return { apex: { x: pose.x, y: pose.y, z: pose.z }, forward: f, corners: [at(-1, 1), at(1, 1), at(1, -1), at(-1, -1)] };
}

/**
 * Fit a move's set into a width x height box: the subject's mark and post, the path, the floor under it and the camera's
 * frame through the move all stay inside (the floor grid simply runs on past the edges). Returns `to(point)` in box units.
 */
export function stageFit(poses, { width = 100, height = 62, pad = 7, depth = 0.3, aspect = 16 / 9, floor = STAGE.floor, ...angles } = {}) {
  if (!poses?.length) poses = [{ x: 0, y: 0, z: -1, yaw: 0, pitch: 0, fov: 40 }]; // no path: the camera on its starting mark
  const frames = [0, 0.25, 0.5, 0.75, 1].flatMap((t) => frustum(poseAt(poses, t), { depth, aspect }).corners);
  const ground = poses.map((p) => ({ x: p.x, y: floor, z: p.z }));
  const seen = [{ x: 0, y: floor, z: 0 }, { x: 0, y: 0.1, z: 0 }, ...poses, ...ground, ...frames].map((p) => stagePoint(p, angles));
  const xs = seen.map((p) => p.x);
  const ys = seen.map((p) => p.y);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const scale = Math.min((width - 2 * pad) / Math.max(x1 - x0, 1e-6), (height - 2 * pad) / Math.max(y1 - y0, 1e-6));
  const ox = (width - (x1 + x0) * scale) / 2;
  const oy = (height - (y1 + y0) * scale) / 2;
  const to = (p) => { const s = stagePoint(p, angles); return { x: ox + s.x * scale, y: oy + s.y * scale }; };
  return { to, floor, scale, width, height };
}

/**
 * The planned camera pivoted to where the shot starts: every pose turned `azimuth` degrees around the subject (to the
 * camera's right, as `_orbit` in engine/rig.py turns), lifted to `elevation` degrees above eye level (negative: below,
 * looking up) and pushed to `distance` times its own distance. The default angle (0, 0, 1) is the identity.
 */
export function withAngle(poses, { azimuth = 0, elevation = 0, distance = 1 } = {}) {
  const [a, e] = [azimuth * RAD, elevation * RAD];
  return (poses ?? []).map((p) => {
    const x = p.x * distance;
    const y = p.y * distance;
    const z = p.z * distance;
    const r = Math.hypot(x, z);
    const lifted = r > 1e-9
      ? { x: x * Math.cos(e), y: y + r * Math.sin(e), z: z * Math.cos(e), pitch: p.pitch - elevation }
      : { x, y, z, pitch: p.pitch };
    return {
      x: lifted.x * Math.cos(a) - lifted.z * Math.sin(a), y: lifted.y, z: lifted.x * Math.sin(a) + lifted.z * Math.cos(a),
      yaw: p.yaw - azimuth, pitch: lifted.pitch, fov: p.fov,
    };
  });
}

/** Heading of the camera at a pose as a unit vector in the top view (screen space). */
export function heading(pose) {
  const yaw = (pose.yaw * Math.PI) / 180;
  return { x: Math.sin(yaw), y: -Math.cos(yaw) };
}

const length = (points) => points.slice(1).reduce((sum, p, i) => sum + Math.hypot(p.x - points[i].x, p.y - points[i].y), 0);

/** Angle of the path's last segment in degrees (0 = right, 90 = down), for an arrowhead. */
export function endAngle(points) {
  const a = points.at(-2) ?? points[0];
  const b = points.at(-1);
  return (Math.atan2(b.y - a.y, b.x - a.x) * 180) / Math.PI;
}

/**
 * What a move's tile should draw. A camera that travels gets its path in whichever view shows more
 * of it; one that only zooms or only turns gets a symbol, because its path is a point.
 */
export function glyph(move) {
  const poses = move.path ?? move.keys ?? [];
  if (!poses.length) return { kind: "still" };
  const top = topView(poses);
  const side = sideView(poses);
  const travelled = Math.max(length(top.points), length(side.points));
  const first = poses[0];
  const last = poses.at(-1);
  if (travelled < 2) {
    if (Math.abs(last.fov - first.fov) > 1) return { kind: "zoom", direction: last.fov < first.fov ? "in" : "out" };
    if (Math.abs(last.yaw - first.yaw) > 1 || Math.abs(last.pitch - first.pitch) > 1) return { kind: "turn" };
    return { kind: "still" };
  }
  const view = length(side.points) > length(top.points) * 1.05 ? "side" : "top"; // a pure dolly is equal in both: prefer the plan view
  const alone = { includeOrigin: false, pad: 15, minHalf: 0.2 }; // a tile is an icon of the move: the path alone sets the scale
  const v = view === "top" ? topFit(poses, alone) : sideFit(poses, alone);
  return { kind: "path", view, d: v.d, origin: v.origin, start: v.points[0], end: v.points.at(-1), angle: endAngle(v.points) };
}

/**
 * Tape marks that land on the same spot (a crane or a pedestal seen from above moves only in height) are fanned out
 * sideways by `step`, so every number stays readable instead of a stack of one.
 */
export function spreadStacked(spots, step) {
  const groups = [];
  for (const p of spots) {
    const group = groups.find((g) => Math.hypot(g[0].x - p.x, g[0].y - p.y) < 1);
    if (group) group.push(p);
    else groups.push([p]);
  }
  const out = new Map();
  for (const group of groups) {
    group.forEach((p, i) => out.set(p, group.length === 1 ? p : { ...p, x: p.x + (i - (group.length - 1) / 2) * step }));
  }
  return spots.map((p) => out.get(p));
}
