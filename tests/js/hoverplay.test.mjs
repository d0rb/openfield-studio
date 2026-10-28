import test from "node:test";
import assert from "node:assert/strict";

// A page as far as the hover player needs one: elements with attributes, classes, children, listeners and the two states
// it asks about, videos that play and pause, observers whose callbacks the tests call by hand, a wide screen whose motion
// preference can change. The real decoder slots (ui/wall.js) count what plays.
class El {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.attrs = new Map();
    this.names = new Set();
    this.children = [];
    this.parentNode = null;
    this.listeners = {};
    this.dataset = {};
    this.states = new Set(); // ":hover", ":focus-visible"
    this.classList = { add: (...c) => { c.forEach((n) => this.names.add(n)); this.attrs.set("class", [...this.names].join(" ")); }, contains: (n) => this.names.has(n) };
  }
  setAttribute(k, v) { this.attrs.set(k, String(v)); if (k === "class") this.names = new Set(String(v).split(/\s+/).filter(Boolean)); }
  getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }
  removeAttribute(k) { this.attrs.delete(k); }
  append(...kids) { for (const k of kids) { k.remove(); k.parentNode = this; this.children.push(k); } }
  remove() { if (this.parentNode) this.parentNode.children.splice(this.parentNode.children.indexOf(this), 1); this.parentNode = null; }
  get isConnected() { let n = this; while (n.parentNode) n = n.parentNode; return n === page; }
  contains(el) { for (let n = el; n; n = n.parentNode) if (n === this) return true; return false; }
  matches(sel) {
    return sel.split(",").some((one) => {
      const s = one.trim();
      if (s.startsWith(":")) return this.states.has(s);
      const [tag, ...names] = s.split(".");
      return (!tag || tag.toUpperCase() === this.tagName) && names.every((n) => this.names.has(n));
    });
  }
  querySelector(sel) { for (const k of this.children) { if (k.matches(sel)) return k; const deep = k.querySelector(sel); if (deep) return deep; } return null; }
  addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
  dispatch(type, props = {}) { for (const fn of this.listeners[type] ?? []) fn({ type, target: this, ...props }); }
  getBoundingClientRect() { return { width: 320, height: 180 }; }
}
class Video extends El {
  constructor() { super("video"); this.paused = true; this.loads = 0; }
  set src(v) { this.setAttribute("src", v); }
  get src() { return this.getAttribute("src") ?? ""; }
  play() { this.paused = false; return Promise.resolve(); }
  pause() { this.paused = true; }
  load() { this.loads += 1; }
}
const page = new El("body");
globalThis.Node = El;
globalThis.document = {
  hidden: false, activeElement: page, addEventListener() {},
  createElement: (tag) => (tag === "video" ? new Video() : new El(tag)), createElementNS: (_, tag) => new El(tag), createTextNode: (text) => ({ text }),
};
const observers = [];
globalThis.IntersectionObserver = class { constructor(callback) { this.callback = callback; this.observed = new Set(); observers.push(this); } observe(el) { this.observed.add(el); } unobserve(el) { this.observed.delete(el); } };
const prefs = { reduced: false, listeners: [] };
globalThis.matchMedia = (query) => ({
  matches: query.includes("reduce") ? prefs.reduced : query.includes("min-width: 720px"), // a wide screen: twelve slots, sharp copies
  addEventListener: (_, fn) => prefs.listeners.push(fn),
});
const native = globalThis.navigator;
const saving = (on) => Object.defineProperty(globalThis, "navigator", { value: on ? { connection: { saveData: true } } : native, configurable: true, writable: true });

const { clipVideo, hoverClip, hoverPlay, pinLive, unpinLive } = await import("../../openfield/web/js/ui/hoverplay.js");
const { freeSlot, slots } = await import("../../openfield/web/js/ui/wall.js");

const api = { media: (take, file) => `/media/${take.id}/${file}`, asset: (path) => `/showcase/${path}` };
const take = { id: "tk_1", outputs: [{ role: "video", file: "take.mp4" }, { role: "poster", file: "poster.jpg" }] };
const store = (previews = null) => ({ get: () => ({ previews }) });
const CLIP = { video: "/loop.mp4", poster: "/loop.jpg" };
const counts = () => { const { playing, pinned } = slots(); return { playing, pinned }; };
const motionChanged = () => prefs.listeners.forEach((fn) => fn());
/** A tile on the page; `loop` puts a resting loop of the wall's in it. */
function tile({ loop = false } = {}) {
  const el = new El("button");
  page.append(el);
  if (loop) {
    const v = new Video();
    v.setAttribute("class", "live-clip");
    v.dataset.src = "/wall-loop.mp4";
    el.append(v);
  }
  return el;
}
const videos = (el) => el.children.filter((c) => c instanceof Video && c.matches(".hover-clip"));

test("a take with no loop cut yet plays its own file; one with loops plays the copy that fills the frame", () => {
  assert.deepEqual(hoverClip(store(), take, api)(320), { video: "/media/tk_1/take.mp4", poster: "/media/tk_1/poster.jpg" });
  const previews = { takes: { tk_1: { video: "p/tk_1.mp4", poster: "p/tk_1.jpg", mid: { video: "p/tk_1-768.mp4", poster: "p/tk_1-768.jpg", width: 768 } } } };
  assert.deepEqual(hoverClip(store(previews), take, api)(320), { video: "/showcase/p/tk_1.mp4", poster: "/showcase/p/tk_1.jpg" });
  assert.deepEqual(hoverClip(store(previews), take, api)(500), { video: "/showcase/p/tk_1-768.mp4", poster: "/showcase/p/tk_1-768.jpg" });
  assert.equal(hoverClip(store(), { id: "tk_2", outputs: [] }, api)(320), null, "a take with no footage plays nothing");
});

test("under reduced motion the hover wires nothing that plays", () => {
  prefs.reduced = true;
  try {
    let asked = 0;
    const el = tile();
    hoverPlay(el, () => { asked += 1; return CLIP; });
    el.dispatch("pointerenter", { pointerType: "mouse" });
    el.states.add(":focus-visible");
    el.dispatch("focusin");
    assert.equal(asked, 0, "no clip is even looked for");
    assert.equal(videos(el).length, 0);
    const looped = tile({ loop: true });
    hoverPlay(looped, () => CLIP);
    looped.dispatch("pointerenter", { pointerType: "mouse" });
    assert.equal(looped.children[0].getAttribute("src"), null, "a resting loop stays at rest");
    assert.deepEqual(counts(), { playing: 0, pinned: 0 });
  } finally {
    prefs.reduced = false;
  }
});

test("Save-Data plays nothing either, and a finger never does", () => {
  const el = tile();
  hoverPlay(el, () => CLIP);
  saving(true);
  try {
    el.dispatch("pointerenter", { pointerType: "mouse" });
  } finally {
    saving(false);
  }
  el.dispatch("pointerenter", { pointerType: "touch" });
  assert.equal(videos(el).length, 0);
  assert.deepEqual(counts(), { playing: 0, pinned: 0 });
});

test("the pointer plays the take over the still in a pinned slot; leaving gives the decoder back", () => {
  const el = tile();
  hoverPlay(el, (width) => (width === 320 ? CLIP : null));
  el.dispatch("pointerenter", { pointerType: "mouse" });
  const [video] = videos(el);
  assert.ok(video, "a clip is made for the frame's width");
  assert.ok(video.matches(".preview.hover-clip") && video.muted && video.getAttribute("src") === "/loop.mp4" && video.getAttribute("poster") === "/loop.jpg");
  assert.equal(video.getAttribute("aria-hidden"), "true");
  assert.equal(video.getAttribute("tabindex"), "-1");
  assert.equal(video.paused, false);
  assert.deepEqual(counts(), { playing: 1, pinned: 1 });
  assert.ok(!video.classList.contains("playing"), "the still shows until the first frame is up");
  video.dispatch("playing");
  assert.ok(video.classList.contains("playing"));
  el.dispatch("pointerenter", { pointerType: "mouse" });
  assert.equal(videos(el).length, 1, "a second enter does not double it");
  el.dispatch("pointerleave");
  assert.equal(videos(el).length, 0);
  assert.ok(video.paused && video.getAttribute("src") === null && video.loads === 1, "released, not just removed");
  assert.deepEqual(counts(), { playing: 0, pinned: 0 });
});

test("keyboard focus plays as hover does; focus that does not show (a click, a tap) does not; leaving with focus kept keeps it", async () => {
  const el = tile();
  hoverPlay(el, () => CLIP);
  el.dispatch("focusin");
  assert.equal(videos(el).length, 0);
  el.states.add(":focus-visible");
  document.activeElement = el;
  el.dispatch("focusin");
  assert.equal(videos(el).length, 1);
  el.dispatch("pointerleave");
  assert.equal(videos(el).length, 1, "the pointer leaving does not take it from the keyboard");
  el.states.delete(":focus-visible");
  document.activeElement = page;
  el.dispatch("focusout");
  assert.equal(videos(el).length, 1, "a blur is read a tick later, once focus has landed");
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(videos(el).length, 0);
  assert.deepEqual(counts(), { playing: 0, pinned: 0 });
});

test("a loop already there is pinned and played, never doubled; leaving makes it an ordinary loop again", () => {
  const el = tile({ loop: true });
  const loop = el.children[0];
  hoverPlay(el, () => CLIP);
  el.dispatch("pointerenter", { pointerType: "mouse" });
  assert.equal(el.children.length, 1, "no second video");
  assert.equal(loop.getAttribute("src"), "/wall-loop.mp4", "a rested loop gets its address back");
  assert.equal(loop.paused, false);
  assert.deepEqual(counts(), { playing: 1, pinned: 1 });
  el.dispatch("pointerleave");
  assert.deepEqual(counts(), { playing: 1, pinned: 0 }, "still playing, now one any loop that wakes may replace");
  freeSlot(loop);
});

test("pinLive and unpinLive go through the shared slots", () => {
  const loop = new Video();
  loop.dataset.src = "/a.mp4";
  page.append(loop);
  pinLive(loop);
  assert.equal(loop.getAttribute("src"), "/a.mp4");
  assert.deepEqual(counts(), { playing: 1, pinned: 1 });
  unpinLive(loop);
  assert.deepEqual(counts(), { playing: 1, pinned: 0 });
  pinLive(loop);
  loop.pause();
  unpinLive(loop);
  assert.deepEqual(counts(), { playing: 0, pinned: 0 }, "a loop that stopped meanwhile gives its slot back");
});

test("reduced motion turned on mid-hover stops what plays, and a tile that leaves the screen gives its clip back", () => {
  const el = tile();
  hoverPlay(el, () => CLIP);
  el.dispatch("pointerenter", { pointerType: "mouse" });
  prefs.reduced = true;
  try {
    motionChanged();
  } finally {
    prefs.reduced = false;
  }
  assert.equal(videos(el).length, 0);
  assert.deepEqual(counts(), { playing: 0, pinned: 0 });
  el.dispatch("pointerenter", { pointerType: "mouse" });
  const [video] = videos(el);
  const watcher = observers.find((o) => o.observed.has(video));
  assert.ok(watcher, "the clip is watched");
  watcher.callback([{ target: video, isIntersecting: false }]); // its room was hidden, or the list rebuilt under the hand
  assert.equal(videos(el).length, 0);
  assert.deepEqual(counts(), { playing: 0, pinned: 0 });
});

test("a tile with nothing to play stays a still", () => {
  const el = tile();
  hoverPlay(el, () => null);
  el.dispatch("pointerenter", { pointerType: "mouse" });
  assert.equal(el.children.length, 0);
  assert.deepEqual(counts(), { playing: 0, pinned: 0 });
});

test("a clip's video is muted, looping, out of the tab order and silent to readers", () => {
  const v = clipVideo(CLIP, "preview all");
  assert.ok(v.muted && v.loop && v.matches(".preview.all"));
  assert.equal(v.getAttribute("src"), "/loop.mp4");
  assert.equal(v.getAttribute("aria-hidden"), "true");
  assert.equal(v.getAttribute("tabindex"), "-1");
});
