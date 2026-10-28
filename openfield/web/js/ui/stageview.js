// The previs stage: the set seen from above and to one side, with the move's path, its numbered tape marks and the
// camera, which travels the path in step with the take on the wall (`seek(t)`, t = time / duration of the footage).

import { anchorsAlong, frustum, litCount, poseAt, spreadStacked, stageFit } from "../lib/pathview.js";
import { svg } from "./dom.js";

const W = 100;
const H = 62;
const FLOOR_SPAN = 3; // tape lines every half unit out to 3 units each way; the frame crops them
const xy = (p) => `${p.x.toFixed(2)} ${p.y.toFixed(2)}`;
const polyline = (points) => points.map((p, i) => `${i ? "L" : "M"}${xy(p)}`).join(" ");

/**
 * `hollow` draws the camera as planned rather than pinned: a prompt-only or quick shot has no approved stills along the
 * way, only the first. `dense` is the small copy on the wall, whose marks are drawn larger in plan units to stay readable.
 */
export function createStageView(move, { dense = false, hollow = false, aspect = 16 / 9, label, poses: given = null } = {}) {
  const poses = given?.length ? given : move.path?.length ? move.path : move.keys ?? []; // `poses`: the path pivoted to an angle
  const { to, floor, scale } = stageFit(poses, { width: W, height: H, aspect });
  const k = dense ? 1.35 : 1;
  const el = svg("svg", {
    viewBox: `0 0 ${W} ${H}`, class: `stage-view${hollow ? " hollow" : ""}`, role: "img",
    "aria-label": label ?? `Planned camera for ${move.label}: its path around the subject.`,
  });

  // the floor: a sparse grid of tape lines under the whole move, and the subject's mark with a post up to eye level
  const lines = [];
  for (let v = -FLOOR_SPAN; v <= FLOOR_SPAN; v += 0.5) {
    lines.push(`M${xy(to({ x: v, y: floor, z: -FLOOR_SPAN }))} L${xy(to({ x: v, y: floor, z: FLOOR_SPAN }))}`);
    lines.push(`M${xy(to({ x: -FLOOR_SPAN, y: floor, z: v }))} L${xy(to({ x: FLOOR_SPAN, y: floor, z: v }))}`);
  }
  const foot = to({ x: 0, y: floor, z: 0 });
  const eye = to({ x: 0, y: 0, z: 0 });
  const track = poses.map(to);
  const r = 0.09 * scale;
  const drop = svg("path", { class: "sv-drop" });
  const lit = svg("path", { class: "sv-lit", d: polyline(track), pathLength: "1", "stroke-dashoffset": "1" }); // the part travelled so far
  const dot = svg("circle", { class: "sv-dot", r: 0.9 * k });
  el.append(
    svg("path", { class: "sv-grid", d: lines.join(" ") }),
    svg("ellipse", { class: "sv-foot", cx: foot.x.toFixed(2), cy: foot.y.toFixed(2), rx: r.toFixed(2), ry: (r * 0.47).toFixed(2) }),
    drop, dot,
    svg("path", { class: "sv-path", d: polyline(track) }),
    lit,
    svg("path", { class: "sv-post", d: `M${xy(foot)} L${xy(eye)}` }),
    svg("circle", { class: "sv-head", cx: eye.x.toFixed(2), cy: eye.y.toFixed(2), r: 1.5 * k }),
  );

  // the camera's frame `depth` ahead and four rays back to the lens; the numbered marks sit above them, the lens on top
  const rays = svg("path", { class: "sv-rays" });
  const frame = svg("path", { class: "sv-frame" });
  const lens = svg("circle", { class: "sv-cam", r: 2 * k });
  el.append(rays, frame);

  // the numbered tape marks: one per approved still, where the camera is when the shot reaches it
  const count = hollow ? 1 : Math.max(2, move.anchors ?? 2);
  const marks = spreadStacked(anchorsAlong({ points: track }, count), 7.5 * k).map((p, i) => {
    const mark = svg("g", { class: "sv-mark", transform: `translate(${xy(p)})` },
      svg("circle", { r: 3 * k }),
      svg("text", { "text-anchor": "middle", "dominant-baseline": "central", "font-size": (3.4 * k).toFixed(2) }, String(i + 1)));
    el.append(mark);
    return mark;
  });
  el.append(lens);

  let last = -1;
  let reached = -1;
  function seek(t) {
    const v = Number.isFinite(t) ? Math.min(1, Math.max(0, t)) : 0;
    if (Math.abs(v - last) < 1 / 2400) return;
    last = v;
    const pose = poseAt(poses, v);
    const { apex, corners } = frustum(pose, { aspect });
    const a = to(apex);
    const c = corners.map(to);
    frame.setAttribute("d", `${polyline(c)} Z`);
    rays.setAttribute("d", c.map((p) => `M${xy(a)} L${xy(p)}`).join(" "));
    lens.setAttribute("cx", a.x.toFixed(2));
    lens.setAttribute("cy", a.y.toFixed(2));
    const g = to({ x: pose.x, y: floor, z: pose.z });
    drop.setAttribute("d", `M${xy(a)} L${xy(g)}`);
    dot.setAttribute("cx", g.x.toFixed(2));
    dot.setAttribute("cy", g.y.toFixed(2));
    lit.setAttribute("stroke-dashoffset", (1 - v).toFixed(4));
    el.dataset.t = v.toFixed(3);
    const n = litCount(marks.length, v);
    if (n !== reached) {
      reached = n;
      marks.forEach((m, i) => m.classList.toggle("lit", i < n));
    }
  }
  seek(0);
  return { el, seek };
}
