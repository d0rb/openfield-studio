// The camera's path over a frame: a move's small stage (the glyph its Move Pad tile draws) laid on the footage, its track
// lit as far as the take under it has reached, so a dolly closes in and an orbit comes round while the take plays or the
// mouse scrubs it. The glyphs live here so the wall, the filmstrip and the galleries draw them without the Move Pad.

import { STAGE, endAngle, glyph, stagePoint, withAngle } from "../lib/pathview.js";
import { angleGeometry } from "../lib/direct.js";
import { holdStill } from "../lib/motion.js";
import { svg } from "./dom.js";

const ARROW = "M-4 -3.2 L4 0 L-4 3.2 Z";
const stroke = { "vector-effect": "non-scaling-stroke" };

export function tileGlyph(move) {
  const g = glyph(move);
  const root = svg("svg", { viewBox: "0 0 100 100", class: "glyph", "aria-hidden": "true" });
  if (g.kind === "path") {
    root.append(
      svg("path", { d: g.d, class: "g-path", ...stroke }),
      svg("circle", { cx: g.start.x, cy: g.start.y, r: 4, class: "g-start" }),
      svg("path", { d: ARROW, class: "g-head", transform: `translate(${g.end.x} ${g.end.y}) rotate(${g.angle}) scale(2)` }),
    );
  } else if (g.kind === "zoom") {
    const [outer, inner] = g.direction === "in" ? [34, 17] : [17, 34];
    root.append(
      svg("rect", { x: 50 - outer, y: 50 - outer * 0.62, width: outer * 2, height: outer * 1.24, rx: 3, class: "g-frame faint", ...stroke }),
      svg("rect", { x: 50 - inner, y: 50 - inner * 0.62, width: inner * 2, height: inner * 1.24, rx: 3, class: "g-frame", ...stroke }),
    );
  } else if (g.kind === "turn") {
    root.append(svg("path", { d: "M26 62 A26 26 0 0 1 74 62", class: "g-path", ...stroke }), svg("path", { d: ARROW, class: "g-head", transform: "translate(74 62) rotate(60) scale(1.5)" }));
  } else {
    root.append(svg("circle", { cx: 50, cy: 50, r: 16, class: "g-frame", ...stroke }));
  }
  return root;
}

/** A tile's own small stage: the camera's track seen as the stage view sees it, beside the subject's post, with its
 * start and end marked, so a crane rises and a dolly closes in even at tile size. */
export function tilePlan(move) {
  const poses = move.path ?? move.keys ?? [];
  if (!poses.length) return tileGlyph(move);
  if (glyph(move).kind !== "path") return tileGlyph(move); // a zoom or a turn has no track to draw: its symbol stays
  const track = poses.map((p) => stagePoint(p));
  const [eye, foot] = [stagePoint({ x: 0, y: 0, z: 0 }), stagePoint({ x: 0, y: STAGE.floor, z: 0 })];
  const all = [...track, eye, foot];
  const [xs, ys] = [all.map((p) => p.x), all.map((p) => p.y)];
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const scale = 68 / Math.max(x1 - x0, y1 - y0, 0.4);
  const at = (p) => ({ x: 50 + (p.x - (x0 + x1) / 2) * scale, y: 50 + (p.y - (y0 + y1) / 2) * scale });
  const pts = track.map(at);
  const [e, f] = [at(eye), at(foot)];
  const root = svg("svg", { viewBox: "0 0 100 100", class: "glyph tile-plan", "aria-hidden": "true" });
  root.append(
    svg("path", { d: `M${f.x.toFixed(1)} ${f.y.toFixed(1)} L${e.x.toFixed(1)} ${e.y.toFixed(1)}`, class: "g-post", ...stroke }),
    svg("circle", { cx: e.x.toFixed(1), cy: e.y.toFixed(1), r: 5.5, class: "g-subject" }),
    svg("path", { d: pts.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(" "), class: "g-path", ...stroke }),
    svg("circle", { cx: pts[0].x.toFixed(1), cy: pts[0].y.toFixed(1), r: 4, class: "g-start" }),
    svg("path", { d: ARROW, class: "g-head", transform: `translate(${pts.at(-1).x.toFixed(1)} ${pts.at(-1).y.toFixed(1)}) rotate(${endAngle(pts).toFixed(1)}) scale(1.6)` }),
  );
  return root;
}

const clamp = (t) => (Number.isFinite(t) ? Math.min(1, Math.max(0, t)) : 0);

/** A move's glyph for a chip over a frame, pivoted to where the camera started (`angle`, an angle id). `seek(t)` lights the
 * track to t (time / duration) as the stage view's lit path does; a zoom, a turn or a still has no track. Null for a move
 * the catalog does not have. */
export function pathChip(catalog, movementId, { angle = null } = {}) {
  const move = catalog?.moves?.find((m) => m.id === movementId);
  if (!move) return null;
  const pivot = angle ? angleGeometry(catalog, angle) : null;
  const el = tilePlan(pivot && move.path?.length ? { ...move, path: withAngle(move.path, pivot) } : move);
  const track = el.classList.contains("tile-plan") ? el.querySelector(".g-path") : null;
  // the travelled part: the track again, one dash of length 1 pushed back by what is still to come
  const lit = track ? svg("path", { d: track.getAttribute("d"), class: "g-lit", pathLength: "1", "stroke-dasharray": "1", "stroke-dashoffset": "1", fill: "none" }) : null;
  track?.after(lit);
  return {
    el,
    seek(t) {
      const off = (1 - clamp(t)).toFixed(4);
      if (lit && lit.getAttribute("stroke-dashoffset") !== off) lit.setAttribute("stroke-dashoffset", off);
    },
  };
}

const shown = new Map(); // chip -> its hide
let gone = null; // a chip whose frame is hidden or rebuilt under the hand comes down: no pointerleave or blur comes for it

/** Hover or keyboard focus on `box` lays the move's path chip over `into`; every frame it reads the video (or a function
 * that finds one made on hover), so the loop playing and the mouse scrubbing both drive it. Not for touch or held still. */
export function chipOn(box, video, { catalog, movement, angle = null, into = box }) {
  let chip = null;
  let frame = 0;
  const follow = () => {
    const v = typeof video === "function" ? video() : video;
    if (v?.duration > 0) chip.seek(v.currentTime / v.duration);
    frame = requestAnimationFrame(follow);
  };
  const hide = () => {
    cancelAnimationFrame(frame);
    if (!chip) return;
    shown.delete(chip.el);
    gone?.unobserve(chip.el);
    chip.el.remove();
    chip = null;
  };
  const show = (e) => {
    if (chip || e.pointerType === "touch" || (e.type === "focus" && !box.matches(":focus-visible")) || holdStill()) return;
    chip = pathChip(catalog(), movement, { angle });
    if (!chip) return;
    chip.el.classList.add("path-chip");
    into.append(chip.el);
    shown.set(chip.el, hide);
    gone ??= globalThis.IntersectionObserver ? new IntersectionObserver((list) => { for (const x of list) if (!x.isIntersecting) shown.get(x.target)?.(); }) : null;
    gone?.observe(chip.el);
    follow();
  };
  box.addEventListener("pointerenter", show);
  box.addEventListener("focus", show);
  box.addEventListener("pointerleave", () => { if (!box.matches(":focus-visible")) hide(); }); // keyboard focus keeps it, as it keeps the clip
  box.addEventListener("blur", () => { if (!box.matches(":hover")) hide(); });
}
