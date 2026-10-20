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

/** Points at the given fractions (0..1) along the path, for numbered anchor markers. */
export function anchorsAlong(view, count) {
  const n = view.points.length;
  if (count <= 1 || n === 0) return count === 1 && n ? [view.points[0]] : [];
  return Array.from({ length: count }, (_, i) => view.points[Math.round((i / (count - 1)) * (n - 1))]);
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
