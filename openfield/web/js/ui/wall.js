// Moving pictures. A recorded take's short muted loop plays while its tile is on screen, a few at a time; the poster
// stands in under reduced motion or data saver, in a hidden tab, and until the tile nears the viewport. The wall is
// the Takes station's monitor bank: every finished take playing, its timecode, its kind and its proof on the bezel.

import { timecode } from "../lib/format.js";
import { fileOf, titleOf } from "../lib/stages.js";
import { editPreset } from "../lib/edit.js";
import { holdStill, onMotionChange } from "../lib/motion.js";
import { pick } from "../lib/pictures.js";
import { h } from "./dom.js";
import { keykode } from "./keykode.js";
import { hoverClip, hoverPlay } from "./hoverplay.js";
import { identityPill } from "./monitor.js";
import { chipOn } from "./pathchip.js";
import { scrubbable } from "./scrub.js";

/** How many loops may play at once: a phone (under 720px, the app's own line) plays four, a wide screen twelve. */
export const cap = () => (globalThis.matchMedia?.("(max-width: 719px)")?.matches ? 4 : 12);
const playing = new Set();
const pinned = new Set(); // videos someone opened (a sheet's takes, the quiz): the loops that wake on their own never take their slot
const near = new Set(); // watched loops in or near the viewport: what plays when motion is allowed again
let watcher = null;

/** The oldest playing video that may yield its slot, or null when every slot holds a video someone opened. */
function oldestLoop() {
  for (const video of playing) if (!pinned.has(video)) return video;
  return null;
}
function settle(video) {
  playing.delete(video);
  pinned.delete(video);
  if (!video.paused) video.pause();
}
function release(video) {
  settle(video);
  if (video.getAttribute("src")) { video.removeAttribute("src"); video.load(); } // phones run out of decoders
}
function start(video) {
  if (holdStill() || document.hidden || !video.isConnected) return;
  if (!video.getAttribute("poster") && video.dataset.poster) video.poster = video.dataset.poster;
  while (playing.size >= cap()) { // the oldest loop yields its slot; a video someone opened never does
    const oldest = oldestLoop();
    if (!oldest) return;
    settle(oldest);
  }
  if (!video.getAttribute("src")) video.src = video.dataset.src;
  playing.add(video);
  video.play().catch(() => playing.delete(video));
}
function watch(video) {
  watcher ??= new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.target.isConnected) { watcher.unobserve(e.target); near.delete(e.target); release(e.target); }
      else if (e.isIntersecting) { near.add(e.target); start(e.target); }
      else { near.delete(e.target); release(e.target); }
    }
  }, { rootMargin: "160px 0px" });
  watcher.observe(video);
}
// a preference that changes while the page is open (reduced motion turned off, or on) takes effect at once: the loops
// stop or start, and a video someone opened stops too (its own Play button starts it again)
onMotionChange(() => {
  for (const v of [...near]) {
    if (!v.isConnected) near.delete(v);
    else if (holdStill()) release(v);
    else start(v);
  }
  if (holdStill()) for (const v of [...pinned]) if (v.isConnected && !v.paused) v.pause();
});
// a hidden tab pauses what plays; coming back plays again only what the hiding paused (not a take someone had paused)
const pausedByHiding = new Set();
globalThis.document?.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    for (const v of [...playing]) {
      if (!v.isConnected) { playing.delete(v); pinned.delete(v); }
      else if (!v.paused) { pausedByHiding.add(v); v.pause(); }
    }
    return;
  }
  for (const v of [...pausedByHiding]) if (v.isConnected && playing.has(v) && !holdStill()) v.play().catch(() => {});
  pausedByHiding.clear();
});

/** Take one of the shared slots for a video started outside the wall's watcher (a poster's take, the quiz, a move's
    page): the oldest playing loop yields, so the whole app stays within `cap()`. */
export function claimSlot(video, { pin = false } = {}) {
  if (!playing.has(video)) {
    while (playing.size >= cap()) { // only a loop yields: with every slot held by an opened video, the budget bends
      const oldest = oldestLoop();
      if (!oldest) break;
      settle(oldest);
    }
  }
  playing.add(video);
  if (pin) pinned.add(video); // `pin`: someone opened it, so no loop that wakes by itself may take the slot
}
/** Give the slot back when that video stops or leaves; loops left waiting near the screen may start again. */
export function freeSlot(video) {
  playing.delete(video);
  if (!pinned.delete(video)) return;
  for (const v of [...near]) if (v.isConnected && v.paused && !playing.has(v)) start(v);
}

/** What the loops are doing, for the smoke test and the console: how many play, how many someone opened, the cap. */
export const slots = () => ({ playing: playing.size, pinned: pinned.size, cap: cap() });

/** The showcase's preview loop for a take (a replay plays its recording's), as { video, poster } URLs, or null. `width` is
    the CSS width of the frame it fills: the copy that fills its pixels on this screen is chosen (lib/pictures.js: the 384px
    loop, the 768px one, or the take's own up to 1280px); `hd` stands for a large frame (640px). A tile that passes neither,
    a phone and a data saver keep the 384px loop whatever the screen. */
export function previewOf(state, take, api, { hd = false, width = hd ? 640 : 0 } = {}) {
  const entry = take && state.previews?.takes?.[take.replay_of ?? take.id];
  const copy = entry ? pick(entry, width) : null;
  return copy && api?.asset ? { video: api.asset(copy.video), poster: api.asset(copy.poster) } : null;
}

// A clip's poster loads as the clip nears the screen: a video fetches its poster at once, even far below the fold or
// in a hidden filter, and the Lobby's galleries hang sixty of them.
let posterWatcher = null;
function lazyPoster(video, poster) {
  if (!poster) return;
  video.dataset.poster = poster;
  posterWatcher ??= new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.target.isConnected && !e.isIntersecting) continue;
      posterWatcher.unobserve(e.target);
      if (e.target.isConnected) e.target.poster = e.target.dataset.poster;
    }
  }, { rootMargin: "900px 0px", scrollMargin: "600px" }); // scrollMargin: the rails scroll sideways
  posterWatcher.observe(video);
}

/** A muted loop that plays only while it is on screen, and never under reduced motion. */
export function liveClip({ video, poster }) {
  const el = h("video", { class: "live-clip", muted: true, loop: true, playsinline: true, preload: "none", "aria-hidden": "true", disablepictureinpicture: true, tabindex: "-1" });
  el.muted = true; // the attribute alone does not mute every browser, and an unmuted video may not autoplay
  el.dataset.src = video;
  lazyPoster(el, poster);
  watch(el);
  return el;
}

export const KIND = { direct: "Direct", reshoot: "Re-shoot", export: "Export", transition: "Transition", shots: "Shots", edit: "Edit", extend: "Extend", upscale: "Upscale" };

/** One monitor on the wall: the take's loop (or its poster), its timecode, its kind and its identity result. */
function wallTile(take, { state, store, api, onOpen, width = 0 }) {
  const clip = previewOf(state, take, api, { width });
  const poster = fileOf(take, "poster");
  const picture = clip ? liveClip(clip)
    : poster ? h("img", { class: "live-clip", src: api.media(take, poster), alt: "", loading: "lazy", draggable: "false" })
      : h("span", { class: "live-clip blank" });
  const kind = KIND[take.kind] ?? take.kind;
  // a Direct monitor is labelled with its move, the way a camera report names the setup, an edit with its preset
  const named = take.kind === "direct" ? state.moves?.moves.find((m) => m.id === take.recipe?.rig?.movement)?.label
    : take.kind === "edit" ? editPreset(state.moves, take.recipe?.preset)?.label : null;
  const tile = h("button", { type: "button", class: "wall-tile", "data-kind": take.kind, title: titleOf(take), "aria-label": `${titleOf(take)} (${named ?? kind})` },
    picture,
    keykode(take), // the take's serial, seed and recipe, printed up the frame's edge: never hidden behind a hover
    h("span", { class: "wall-bezel" },
      h("span", { class: "wall-kind" }, h("span", { class: "tally", "aria-hidden": "true" }), named ?? kind),
      identityPill(take.identity, { compact: true }) ?? h("span")),
    h("span", { class: "wall-foot" }, h("span", { class: "wall-title" }, titleOf(take)),
      take.seconds ? h("span", { class: "wall-tc num" }, timecode(take.seconds)) : null));
  tile.addEventListener("click", () => onOpen(take.id));
  if (clip) scrubbable(tile, picture); // the mouse runs the take back and forth, as on the Lobby's galleries
  hoverPlay(tile, hoverClip(store, take, api)); // the hand pins the loop, or plays a take that has none (after the scrub, whose leave resumes the loop)
  const movement = take.kind === "direct" && take.recipe?.rig?.movement;
  if (movement) chipOn(tile, () => tile.querySelector("video"), { catalog: () => store.get().moves, movement, angle: take.recipe.rig.angle ?? null });
  return tile;
}

/** The order of the wall: the showcase's reel first (its curated order), then everything else, newest first. */
export function wallOrder(items, reel = []) {
  const at = new Map(reel.map((id, i) => [id, i]));
  const rank = (t) => at.get(t.replay_of ?? t.id) ?? Infinity;
  return [...items].sort((a, b) => rank(a) - rank(b) || (b.created_at ?? "").localeCompare(a.created_at ?? ""));
}

export function createWall(ctx) {
  const { api, store, ui } = ctx;
  const el = h("div", { class: "wall", role: "list", "aria-label": "Every finished take, playing" });
  let key = "";
  function paint(items) {
    const state = store.get();
    const shown = wallOrder(items.filter((t) => t.status === "succeeded" || t.recording), state.status?.hero_reel ?? []);
    const next = shown.map((t) => `${t.id}:${t.seconds ?? ""}`).join() + `|${Boolean(state.previews)}`;
    if (next === key) return;
    key = next;
    const box = el.clientWidth; // 0 while the room is hidden: then the grid's minimum
    const per = Math.max(1, Math.floor((box + 6) / (232 + 6)));
    const column = box ? (box - (per - 1) * 6) / per : 232;
    el.replaceChildren(...shown.map((t, i) => {
      const big = i === 0 && globalThis.innerWidth >= 900; // the first tile spans 2x2 from 900px
      const tile = wallTile(t, { state, store, api, onOpen: (id) => ui.openTake(id), width: big ? column * 2 + 6 : column });
      tile.setAttribute("role", "listitem");
      return tile;
    }));
  }
  return { el, paint };
}
