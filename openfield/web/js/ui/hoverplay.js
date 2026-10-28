// Hover to play: the pointer, or keyboard focus, on a tile that shows a take plays the take in it, muted, in a pinned slot
// of the shared decoders (ui/wall.js); a tile whose loop already runs keeps that loop, pinned while the hand is there.
// Touch, reduced motion, Save-Data and a hidden tab play nothing; the still stays underneath until the first frame is up.

import { holdStill, onMotionChange } from "../lib/motion.js";
import { fileOf } from "../lib/stages.js";
import { h } from "./dom.js";
import { claimSlot, freeSlot, previewOf } from "./wall.js";

const active = new Map(); // video -> the stop of the hover playing it
let gone = null; // a tile hidden or rebuilt under the hand gives its video back: no pointerleave comes for it

/** Keep a wall loop playing under the hand: a pinned slot, its address back if it rested, and play. */
export function pinLive(video) {
  claimSlot(video, { pin: true });
  if (!video.getAttribute("src") && video.dataset.src) video.src = video.dataset.src;
  video.play().catch(() => {});
}
/** The hand left: unpinned, a loop still playing counts again as one that may rest. */
export function unpinLive(video) {
  freeSlot(video);
  if (!video.paused) claimSlot(video);
}

/** A take made here before its loops were cut: its own file and poster. */
function fullTake(take, api) {
  const [file, poster] = [fileOf(take, "video"), fileOf(take, "poster")];
  return file && api?.media ? { video: api.media(take, file), poster: poster && api.media(take, poster) } : null;
}
/** What a frame `width` px wide plays: the copy of the take's loop that fills it, else the take's own file. */
export const hoverClip = (store, take, api) => (width) => previewOf(store.get(), take, api, { width }) ?? fullTake(take, api);

/** A muted loop of `clip` ({ video, poster }), out of the tab order and silent to readers. */
export function clipVideo(clip, cls) {
  const video = h("video", { class: cls, muted: true, loop: true, playsinline: true, preload: "none", "aria-hidden": "true", disablepictureinpicture: true, tabindex: "-1", poster: clip.poster });
  video.muted = true; // the attribute alone does not mute every browser, and an unmuted video may not autoplay
  video.src = clip.video;
  return video;
}

/** The pointer or keyboard focus on `tile` plays its take inside `into`: a loop already there (`existing`) is pinned, else
 * `clip(width)` names one ({ video, poster } or null) to play over the still. Leaving lets it go. */
export function hoverPlay(tile, clip, { into = tile, existing = "video.live-clip" } = {}) {
  let live = null;
  let own = null;
  const stop = () => {
    const video = live ?? own;
    if (!video) return;
    active.delete(video);
    gone?.unobserve(video);
    if (live) unpinLive(live);
    else { freeSlot(own); own.pause(); own.removeAttribute("src"); own.load(); own.remove(); } // released, not just removed: a phone has few decoders
    live = own = null;
  };
  const start = (e) => {
    // focus plays only where it shows (:focus-visible, the keyboard's): a tap that focuses a tile plays nothing
    if (live || own || e.pointerType === "touch" || (e.type === "focusin" && !e.target.matches(":focus-visible")) || holdStill() || document.hidden) return;
    live = into.querySelector(existing);
    if (live) pinLive(live);
    else {
      const c = clip(into.getBoundingClientRect().width);
      if (!c?.video) return;
      const video = (own = clipVideo(c, "preview hover-clip"));
      video.addEventListener("playing", () => video.classList.add("playing"), { once: true }); // it fades in over the still
      into.append(video);
      claimSlot(video, { pin: true });
      video.play().catch(() => {});
    }
    active.set(live ?? own, stop);
    gone ??= globalThis.IntersectionObserver ? new IntersectionObserver((list) => { for (const x of list) if (!x.isIntersecting) active.get(x.target)?.(); }) : null;
    gone?.observe(live ?? own);
  };
  const leave = () => {
    const focus = document.activeElement;
    if (!tile.matches(":hover") && !(tile.contains(focus) && focus.matches(":focus-visible"))) stop();
  };
  tile.addEventListener("pointerenter", start);
  tile.addEventListener("focusin", start);
  tile.addEventListener("pointerleave", leave);
  tile.addEventListener("focusout", () => setTimeout(leave, 0)); // focus moving within the tile is not leaving it
  return { stop };
}

// reduced motion turned on mid-hover: whatever plays under a hand stops
onMotionChange(() => { if (holdStill()) for (const stop of [...active.values()]) stop(); });
