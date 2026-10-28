// The light in the rooms: in the stage's cell, under the stage, a still projector beam and slow dust screen-blended over
// the floor, and a house light that follows the mouse (layout.css paints all three). The Lobby has its own light, so the
// layer hides there. Nothing runs at import time; the house light moves only for a mouse on a wide screen that hovers,
// with motion allowed.

import { h } from "./dom.js";
import { holdStill } from "../lib/motion.js";

export const HALF = 550; // half the house light's 1100 px box (layout.css): its centre sits on the pointer
const GLIDE = 0.18; // how far the light goes toward the pointer each frame

/** One frame of the light's glide: `k` of the way from `from` to `to`. */
export const lightStep = (from, to, k) => ({ x: from.x + (to.x - from.x) * k, y: from.y + (to.y - from.y) * k });

/** A mouse on a wide screen that hovers, with motion allowed: the only case where the house light moves. */
const canLight = () => !holdStill() && Boolean(globalThis.matchMedia?.("(hover: hover) and (min-width: 900px)")?.matches);

/** The light layer for `stage`. Mount `el` as the stage's sibling in the same grid cell, before it. */
export function createAmbient(stage) {
  const light = h("span", { class: "house-light" });
  const el = h("div", { class: "ambient", "aria-hidden": "true" }, h("span", { class: "ambient-beam" }), h("span", { class: "ambient-dust" }), light);
  let at = null; // where the light is, in the layer's own pixels
  let want = null; // where the pointer is
  let frame = 0;
  const place = () => { light.style.transform = `translate3d(${at.x - HALF}px, ${at.y - HALF}px, 0)`; };
  const glide = () => {
    frame = 0;
    if (!want) return;
    at = lightStep(at, want, GLIDE);
    place();
    if (Math.hypot(want.x - at.x, want.y - at.y) > 0.5) frame = requestAnimationFrame(glide);
  };
  stage.addEventListener("pointermove", (e) => {
    if (e.pointerType !== "mouse" || !canLight()) return;
    const box = el.getBoundingClientRect();
    want = { x: e.clientX - box.left, y: e.clientY - box.top };
    if (!at) { // the first move: the light comes up where the pointer is, with no glide from somewhere else
      at = want;
      place();
      el.classList.add("lit");
    } else if (!frame) frame = requestAnimationFrame(glide);
  }, { passive: true });
  stage.addEventListener("pointerleave", () => { el.classList.remove("lit"); want = null; at = null; });
  document.addEventListener("visibilitychange", () => { cancelAnimationFrame(frame); frame = 0; });
  return { el };
}
