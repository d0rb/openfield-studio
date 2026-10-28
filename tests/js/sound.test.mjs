// The studio's sound: one switch (the Lobby's Sound pill), remembered in this browser, and five short cues. Everything runs
// in Node against stubs: a Map-backed localStorage, a fake AudioContext that records what was scheduled on it, and a small
// fake page (elements, events that bubble, a document) for screen.js and quiz.js, which build real DOM.
import test, { afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = new URL("../../openfield/web/", import.meta.url);
const source = (path) => readFileSync(new URL(path, WEB), "utf8");
const catalog = JSON.parse(readFileSync(new URL("./fixtures/catalog.json", import.meta.url), "utf8"));

// the modules that run in Node without a page, loaded before any stub (as lobby.test.mjs does); `studio` is the one
// instance of sound.js that screen.js and quiz.js share
const { createScreen } = await import("../../openfield/web/js/ui/screen.js");
const { createQuiz } = await import("../../openfield/web/js/ui/quiz.js");
const { claimSlot, freeSlot, slots } = await import("../../openfield/web/js/ui/wall.js");
const { dailyQuiz, quizDay } = await import("../../openfield/web/js/lib/quiz.js");
const studio = await import("../../openfield/web/js/ui/sound.js");

// -- stubs ------------------------------------------------------------------------------------------------------------

const clock = { t: 10_000 }; // performance.now(), moved by hand; every test starts a second later than the last
const saved = new Map();
function stub(name, value) {
  if (!saved.has(name)) saved.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
  Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
}
function stubGetter(name, get) {
  if (!saved.has(name)) saved.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
  Object.defineProperty(globalThis, name, { get, configurable: true });
}

/** A scheduled value: records every call made on it. */
class Param {
  constructor() { this.value = 0; this.calls = []; }
  setValueAtTime(v, t) { this.calls.push(["set", v, t]); return this; }
  linearRampToValueAtTime(v, t) { this.calls.push(["linear", v, t]); return this; }
  exponentialRampToValueAtTime(v, t) { this.calls.push(["exp", v, t]); return this; }
}
/** An audio node: what it was connected to, and when it was told to start and stop. */
class Wire {
  constructor(kind, extra = {}) { Object.assign(this, { kind, to: [], at: null, until: null }, extra); }
  connect(next) { this.to.push(next); return next; }
  start(t) { this.at = t; }
  stop(t) { this.until = t; }
}
/** The page has one audio context; every `new` hands back that one and counts the call. */
class FakeAudio {
  static calls = 0;
  static one = null;
  constructor() {
    FakeAudio.calls += 1;
    if (FakeAudio.one) return FakeAudio.one;
    FakeAudio.one = this;
    Object.assign(this, { currentTime: 0, sampleRate: 48_000, state: "running", resumes: 0, destination: new Wire("destination"), gains: [], voices: [] });
  }
  resume() { this.resumes += 1; this.state = "running"; return Promise.resolve(); }
  createGain() { const g = new Wire("gain", { gain: new Param() }); this.gains.push(g); return g; }
  createOscillator() { const o = new Wire("osc", { type: "sine", frequency: new Param() }); this.voices.push(o); return o; }
  createBufferSource() { const s = new Wire("noise", { buffer: null }); this.voices.push(s); return s; }
  createBuffer(_, length) { return { length, getChannelData: () => new Float32Array(length) }; }
  createBiquadFilter() { return new Wire("filter", { type: "", frequency: new Param(), Q: { value: 0 } }); }
}

/** The observers the modules made, whatever test they were made in: the tests call their callbacks by hand. */
const observers = [];
class FakeObserver {
  constructor(callback, options) { Object.assign(this, { callback, options, seen: new Set() }); observers.push(this); }
  observe(el) { this.seen.add(el); }
  unobserve(el) { this.seen.delete(el); }
  disconnect() { this.seen.clear(); }
}
const loopWatcher = () => observers.find((o) => o.options?.rootMargin === "160px 0px"); // wall.js: the loops near the view
const nearView = (clip) => loopWatcher().callback([{ target: clip, isIntersecting: true }]);
const leaveView = (clip) => loopWatcher().callback([{ target: clip, isIntersecting: false }]);

/** A page: elements with attributes, classes, children and events that bubble (document-level capture runs first). */
class DomNode {} // the page's own `Node`, which dom.js asks about
const camel = (s) => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
const textOf = (n) => n.text ?? n.children.map(textOf).join("");
function addListener(target, type, fn, options) {
  const entry = { fn, capture: options === true || Boolean(options?.capture) };
  (target.listeners[type] ??= []).push(entry);
  options?.signal?.addEventListener("abort", () => { target.listeners[type] = target.listeners[type].filter((e) => e !== entry); });
}
function fire(target, type, init = {}) {
  const event = { type, target, currentTarget: null, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...init };
  const path = [];
  for (let n = target; n; n = n.parent) path.push(n);
  const top = path.at(-1);
  const doc = top.root ?? (top.body ? top : null);
  event.composedPath = () => [...path, ...(doc && !path.includes(doc) ? [doc] : [])]; // the path as it was when the event landed
  const run = (node, capture) => {
    event.currentTarget = node;
    for (const entry of [...(node.listeners[type] ?? [])]) if (entry.capture === capture) entry.fn(event);
  };
  if (doc) run(doc, true);
  for (const node of path) run(node, false);
  if (doc && !path.includes(doc)) run(doc, false);
  return event;
}
class El extends DomNode {
  #muted = false;
  constructor(tag) {
    super();
    Object.assign(this, { tag, attrs: {}, children: [], parent: null, listeners: {}, dataset: {}, hidden: false, disabled: false, paused: true, currentTime: 0, root: null, vars: {} });
    this.classes = new Set();
    this.classList = { add: (...c) => c.forEach((n) => this.classes.add(n)), remove: (...c) => c.forEach((n) => this.classes.delete(n)), contains: (c) => this.classes.has(c) };
    this.style = { setProperty: (k, v) => { this.vars[k] = v; } };
  }
  get muted() { return this.#muted; }
  set muted(v) { if (Boolean(v) !== this.#muted) { this.#muted = Boolean(v); this.dispatch("volumechange"); } } // a browser says so too
  get src() { return this.attrs.src ?? ""; }
  set src(v) { this.attrs.src = String(v); }
  get isConnected() { let n = this; while (n.parent) n = n.parent; return Boolean(n.root); }
  setAttribute(k, v) {
    this.attrs[k] = String(v);
    if (k === "class") this.classes = new Set(String(v).split(/\s+/).filter(Boolean));
    if (k.startsWith("data-")) this.dataset[camel(k.slice(5))] = String(v);
  }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  append(...kids) { for (const k of kids) { k.parent = this; this.children.push(k); } }
  replaceChildren(...kids) { for (const c of this.children) c.parent = null; this.children = []; this.append(...kids); }
  matches(sel) { // tag, .class, [attr] and [attr=value], comma-separated: what the code under test asks
    return sel.split(",").some((part) => {
      const [, tag = "", rest = ""] = /^\s*([a-z0-9]*)(.*?)\s*$/.exec(part);
      if (tag && tag !== this.tag) return false;
      for (const [, cls, attr, value] of rest.matchAll(/\.([\w-]+)|\[([\w-]+)(?:=([\w-]+))?\]/g)) {
        if (cls ? !this.classes.has(cls) : attr === "hidden" ? !this.hidden : value === undefined ? !(attr in this.attrs) : this.attrs[attr] !== value) return false;
      }
      return true;
    });
  }
  closest(sel) { for (let n = this; n; n = n.parent) if (n.matches?.(sel)) return n; return null; }
  querySelectorAll(sel) { return this.children.flatMap((c) => (c instanceof El ? [...(c.matches(sel) ? [c] : []), ...c.querySelectorAll(sel)] : [])); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] ?? null; }
  addEventListener(type, fn, options) { addListener(this, type, fn, options); }
  dispatch(type, init) { return fire(this, type, init); }
  play() { this.paused = false; this.dispatch("play"); return Promise.resolve(); }
  pause() { this.paused = true; this.dispatch("pause"); }
  load() {}
  focus() {}
}
function page(hidden) {
  const doc = {
    hidden, listeners: {}, body: new El("body"),
    createElement: (tag) => new El(tag), createElementNS: (_, tag) => new El(tag),
    createTextNode: (text) => Object.assign(new DomNode(), { text }),
    addEventListener(type, fn, options) { addListener(doc, type, fn, options); },
    removeEventListener(type, fn) { doc.listeners[type] = (doc.listeners[type] ?? []).filter((e) => e.fn !== fn); },
    dispatch: (type, init) => fire(doc, type, init),
  };
  doc.body.root = doc;
  return doc;
}
const waiting = () => Object.values(document.listeners).reduce((n, list) => n + list.length, 0); // listeners on the page

/** The browser, as a test needs it. `activated`: the person has pressed or typed on the page before. */
function world({ stored = null, hidden = false, reduced = false, audio = FakeAudio, activated = false } = {}) {
  const store = new Map(stored === null ? [] : [["openfield.sound", stored]]);
  const reads = { n: 0 };
  const doc = page(hidden);
  stub("localStorage", { getItem: (k) => { reads.n += 1; return store.get(k) ?? null; }, setItem: (k, v) => { store.set(k, String(v)); } });
  stub("document", doc);
  stub("Node", DomNode);
  stub("performance", { now: () => clock.t });
  stub("AudioContext", audio);
  stub("matchMedia", (query) => ({ media: query, matches: reduced && query.includes("prefers-reduced-motion"), addEventListener() {} }));
  stub("navigator", activated ? { userActivation: { hasBeenActive: true } } : {});
  stub("requestAnimationFrame", () => 1);
  stub("cancelAnimationFrame", () => {});
  stub("IntersectionObserver", FakeObserver);
  stub("fetch", async () => ({ ok: false }));
  clock.t += 1000;
  FakeAudio.calls = 0;
  if (FakeAudio.one) Object.assign(FakeAudio.one, { gains: [], voices: [], state: "running", resumes: 0 });
  return { store, reads, doc };
}

const mine = []; // the trailers and stand-in loops a test put on the decoder slots
afterEach(() => {
  const clips = mine.splice(0);
  if (loopWatcher()) loopWatcher().callback(clips.filter((v) => v.dataset.src).map((target) => ({ target, isIntersecting: false })));
  for (const v of clips) freeSlot(v);
  for (const [name, d] of saved) { if (d) Object.defineProperty(globalThis, name, d); else delete globalThis[name]; }
  saved.clear();
});

let fresh = 0;
const load = () => import(`../../openfield/web/js/ui/sound.js?fresh=${fresh++}`); // a module of its own: nothing carries over
const later = (ms = 100) => { clock.t += ms; }; // past the 60 ms gap
const cueOf = (voice, CUES = studio.CUES) => (voice.kind === "noise" ? "room"
  : Object.entries(CUES).find(([, [type, from]]) => type === voice.type && from === voice.frequency.calls[0][1])?.[0]);

// -- sound.js ---------------------------------------------------------------------------------------------------------

test("sound is off by default: no cue, no audio system, and importing reads and starts nothing", async () => {
  const w = world();
  const s = await load();
  assert.equal(w.reads.n, 0, "importing touches no storage");
  assert.equal(FakeAudio.calls, 0, "importing starts no audio");
  assert.equal(s.soundOn(), false);
  assert.equal(s.play("tick"), false);
  assert.equal(s.play("thunk"), false);
  assert.equal(FakeAudio.calls, 0, "a switch that is off never starts the audio system");
});

test("the choice is remembered: on writes on, off writes off, a stored on is read back", async () => {
  const w = world();
  const s = await load();
  s.setSound(true);
  assert.equal(w.store.get("openfield.sound"), "on");
  assert.equal(s.soundOn(), true);
  s.setSound(false);
  assert.equal(w.store.get("openfield.sound"), "off");
  assert.equal(s.soundOn(), false);
  world({ stored: "on" });
  assert.equal((await load()).soundOn(), true, "the next visit reads it");
  assert.equal(FakeAudio.calls, 0, "reading a stored on starts no audio: that waits for a gesture");
  world({ stored: "off" });
  assert.equal((await load()).soundOn(), false);
  world({ stored: "maybe" });
  assert.equal((await load()).soundOn(), false, "only a stored on turns it on");
});

test("the audio system starts once, in the gesture that turns the switch on or the first cue after it", async () => {
  world();
  const s = await load();
  s.setSound(true);
  assert.equal(FakeAudio.calls, 1);
  later();
  assert.equal(s.play("tick"), true);
  assert.equal(FakeAudio.calls, 1, "one context for the page, not one a cue");
  world({ stored: "on" });
  const remembered = await load();
  assert.equal(remembered.soundOn(), true);
  assert.equal(FakeAudio.calls, 0, "a remembered on does not start it at load");
  assert.equal(remembered.play("tick"), true);
  assert.equal(FakeAudio.calls, 1, "the first cue does");
});

test("a cue is soft and short: under -20 dBFS, no longer than 80 ms with its tail, into the speakers", async () => {
  world();
  const s = await load();
  s.setSound(true);
  assert.equal(s.play("tick"), true);
  const ac = FakeAudio.one;
  const [voice] = ac.voices;
  const [gain] = ac.gains;
  const peak = Math.max(...gain.gain.calls.map(([, v]) => v));
  assert.ok(peak <= 0.1 + 1e-9, `the peak ${peak} is over -20 dBFS`);
  assert.ok(gain.to.includes(ac.destination), "the cue reaches the destination");
  assert.ok(voice.to.includes(gain), "the voice goes through the gain");
  assert.ok(voice.until <= voice.at + 0.09 + 1e-9, `stops ${voice.until - voice.at}s after it starts`);
  assert.deepEqual(gain.gain.calls[0], ["set", 0, voice.at], "it starts from silence, so it never clicks in");
  assert.ok(gain.gain.calls.at(-1)[1] < 0.01, "and ends near silence, so it never clicks out");
});

test("all five cues stay within 80 ms and -20 dBFS, and the noise one is routed through its filter", async () => {
  world();
  const s = await load();
  s.setSound(true);
  assert.deepEqual(Object.keys(s.CUES).sort(), ["dull", "ping", "room", "thunk", "tick"]);
  for (const [name, [, , , seconds]] of Object.entries(s.CUES)) {
    assert.ok(seconds <= 0.08, `${name} lasts ${seconds}s`);
    later();
    assert.equal(s.play(name), true, name);
  }
  const ac = FakeAudio.one;
  assert.equal(ac.voices.length, 5);
  assert.deepEqual(ac.voices.map((v) => cueOf(v, s.CUES)), Object.keys(s.CUES), "every cue sounds as itself");
  ac.voices.forEach((voice, i) => {
    assert.ok(voice.until <= voice.at + 0.09 + 1e-9, `${i}: stops ${voice.until - voice.at}s after it starts`);
    assert.ok(Math.max(...ac.gains[i].gain.calls.map(([, v]) => v)) <= 0.1 + 1e-9, `${i}: over -20 dBFS`);
  });
  assert.equal(ac.voices[0].kind, "noise");
  assert.ok(ac.voices[0].to[0].kind === "filter" && ac.voices[0].to[0].to.includes(ac.gains[0]), "the clapper is a breath of noise through a band");
});

test("no cue in a hidden tab, on a held key, or twice within 60 ms; an unknown name is silent", async () => {
  const w = world();
  const s = await load();
  s.setSound(true);
  w.doc.hidden = true;
  later();
  assert.equal(s.play("tick"), false, "a hidden tab is silent");
  w.doc.hidden = false;
  assert.equal(s.play("tick", { repeat: true }), false, "a held key is silent");
  assert.equal(s.play("nothing"), false);
  assert.equal(FakeAudio.one.voices.length, 0, "nothing was scheduled by any of those");
  assert.equal(s.play("tick"), true);
  clock.t += 59;
  assert.equal(s.play("thunk"), false, "59 ms after the last cue is too soon");
  clock.t += 1;
  assert.equal(s.play("thunk"), true, "60 ms after it, and the dropped cue did not push the gap back");
  assert.equal(FakeAudio.one.voices.length, 2);
});

test("a localStorage that throws leaves the choice off, and the switch still works for the visit", async () => {
  world();
  stubGetter("localStorage", () => { throw new DOMException("denied", "SecurityError"); });
  const s = await load();
  assert.equal(s.soundOn(), false);
  assert.doesNotThrow(() => s.setSound(true));
  assert.equal(s.soundOn(), true, "it is on for this visit");
  later();
  assert.equal(s.play("tick"), true);
  world();
  stub("localStorage", { getItem: () => "on", setItem: () => { throw new DOMException("full", "QuotaExceededError"); } });
  const full = await load();
  assert.equal(full.soundOn(), true);
  assert.doesNotThrow(() => full.setSound(false));
  assert.equal(full.soundOn(), false, "a storage that cannot write still turns it off for the visit");
});

test("a browser with no audio, or only the prefixed one, never throws", async () => {
  world({ audio: null });
  const none = await load();
  assert.doesNotThrow(() => none.setSound(true));
  assert.equal(none.soundOn(), true, "the choice stands; the cues just cannot sound");
  assert.equal(none.play("tick"), false);
  world({ audio: null });
  stub("webkitAudioContext", FakeAudio);
  const prefixed = await load();
  prefixed.setSound(true);
  later();
  assert.equal(prefixed.play("tick"), true, "webkitAudioContext is used when it is all there is");
});

test("an audio system that cannot start leaves the switch working and the cues silent", async () => {
  world({ audio: class { constructor() { throw new Error("no audio device"); } } });
  const s = await load();
  assert.doesNotThrow(() => s.setSound(true), "the Lobby pill is also the trailer's sound switch: it must not depend on Web Audio");
  assert.equal(s.soundOn(), true);
  assert.doesNotThrow(() => assert.equal(s.play("tick"), false));
});

test("sound is not motion: reduced motion and Save-Data leave the cues alone", async () => {
  world({ reduced: true });
  stub("navigator", { connection: { saveData: true } });
  const s = await load();
  s.setSound(true);
  later();
  assert.equal(s.play("thunk"), true);
  assert.equal(FakeAudio.one.voices.length, 1);
});

test("listeners hear the switch change until they ask to stop", async () => {
  world();
  const s = await load();
  const seen = [];
  const stop = s.onSoundChange((on) => seen.push(on));
  s.setSound(true);
  s.setSound(false);
  stop();
  s.setSound(true);
  assert.deepEqual(seen, [true, false]);
});

// -- wireSounds -------------------------------------------------------------------------------------------------------

test("wireSounds puts exactly two listeners on the document, and none when there is no page", async () => {
  world();
  const s = await load();
  const calls = [];
  s.wireSounds({ addEventListener: (type, fn) => calls.push([type, typeof fn]) });
  assert.deepEqual(calls, [["click", "function"], ["keydown", "function"]]);
  assert.doesNotThrow(() => s.wireSounds({}));
  stub("document", undefined);
  assert.doesNotThrow(() => s.wireSounds(), "no document, no listeners, no error");
});

test("a click ticks a toggle, thunks the one primary action, and says nothing for any other button", async () => {
  const { doc } = world();
  const s = await load();
  s.wireSounds();
  s.setSound(true);
  const make = (tag, classes = "", attrs = {}) => {
    const el = new El(tag);
    el.setAttribute("class", classes);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    doc.body.append(el);
    return el;
  };
  const heard = (el) => { later(); const before = FakeAudio.one.voices.length; el.dispatch("click"); return FakeAudio.one.voices.slice(before).map((v) => cueOf(v, s.CUES)); };
  assert.deepEqual(heard(make("a", "btn primary lg", { href: "#/direct" })), ["thunk"], "Start directing is a link and thunks");
  assert.deepEqual(heard(make("button", "btn primary")), ["thunk"]);
  assert.deepEqual(heard(make("button", "rocker-stop", { role: "radio" })), ["tick"]);
  assert.deepEqual(heard(make("button", "", { role: "switch" })), ["tick"]);
  assert.deepEqual(heard(make("button", "", { "aria-pressed": "false" })), ["tick"], "a pressed toggle");
  assert.deepEqual(heard(make("button", "", { role: "tab" })), ["tick"]);
  assert.deepEqual(heard(make("button", "show-filter")), ["tick"], "a gallery filter");
  assert.deepEqual(heard(make("button", "btn secondary")), [], "a plain button is silent");
  assert.deepEqual(heard(make("div", "stage")), [], "so is anything that is not a control");
  const off = make("button", "btn primary");
  off.disabled = true;
  assert.deepEqual(heard(off), [], "a disabled button is silent");
  const inner = new El("span");
  const wrapped = make("button", "btn primary");
  wrapped.append(inner);
  assert.deepEqual(heard(inner), ["thunk"], "a click on a button's icon counts as a click on the button");
});

test("a click's own cue comes before the room change it starts, so Start directing is one thunk and not a clap", async () => {
  const { doc } = world();
  const s = await load();
  s.wireSounds();
  s.setSound(true);
  const lobbyRoom = new El("div"); // the Lobby's own click handler walks the link and the shell plays the room cue at once
  lobbyRoom.addEventListener("click", () => s.play("room"));
  const start = new El("a");
  start.setAttribute("class", "btn primary lg");
  start.setAttribute("href", "#/direct");
  lobbyRoom.append(start);
  doc.body.append(lobbyRoom);
  later();
  start.dispatch("click");
  assert.deepEqual(FakeAudio.one.voices.map((v) => cueOf(v, s.CUES)), ["thunk"], "one thunk; the clap that follows within 60 ms is the one dropped");
});

test("a control that repaints its own children while it handles the click still gets its cue", async () => {
  const { doc } = world();
  const s = await load();
  s.wireSounds();
  s.setSound(true);
  const toggle = new El("button");
  toggle.setAttribute("aria-pressed", "false");
  const label = new El("span");
  toggle.append(label);
  toggle.addEventListener("click", () => toggle.replaceChildren(new El("span"))); // the part that was hit is gone before the document hears the click
  doc.body.append(toggle);
  later();
  label.dispatch("click");
  assert.equal(label.closest("button"), null, "the part that was hit no longer sits in its button");
  assert.deepEqual(FakeAudio.one.voices.map((v) => cueOf(v, s.CUES)), ["tick"], "and the click still ticks");
});

test("the arrow keys inside a radio group tick once per press, never on a held key or anywhere else", async () => {
  const { doc } = world();
  const s = await load();
  s.wireSounds();
  s.setSound(true);
  const group = new El("div");
  group.setAttribute("role", "radiogroup");
  const stop = new El("button");
  group.append(stop);
  doc.body.append(group);
  const outside = new El("button");
  doc.body.append(outside);
  const count = () => FakeAudio.one.voices.length;
  later();
  stop.dispatch("keydown", { key: "ArrowRight", repeat: false });
  assert.equal(count(), 1, "one press, one tick");
  later();
  stop.dispatch("keydown", { key: "ArrowRight", repeat: true });
  assert.equal(count(), 1, "a held key is silent");
  later();
  stop.dispatch("keydown", { key: "a", repeat: false });
  assert.equal(count(), 1, "only arrow keys");
  outside.dispatch("keydown", { key: "ArrowDown", repeat: false });
  assert.equal(count(), 1, "only inside a radio group");
  later();
  stop.dispatch("keydown", { key: "ArrowLeft", repeat: false });
  assert.equal(count(), 2);
});

// -- the Lobby's screen -----------------------------------------------------------------------------------------------

/** The Lobby's front in a page: the screen in a station the shell can hide. */
function lobby() {
  const screen = createScreen({ openTake() {} }, { billing: "billing" });
  const station = new El("div");
  station.append(screen.el);
  document.body.append(station);
  const clip = screen.el.querySelector(".trailer");
  mine.push(clip);
  return { screen, station, clip, pill: screen.el.querySelector(".trailer-sound") };
}
const iconName = (pill) => pill.children[0].children[0].getAttribute("href").split("#i-")[1];
const standIn = () => { const v = new El("video"); mine.push(v); return v; };
const crowd = () => { for (let i = 0; i <= slots().cap; i += 1) claimSlot(standIn()); }; // one more loop than there are slots

test("the Lobby pill is the studio's switch: it shows the stored choice and a press writes it", () => {
  const w = world();
  studio.setSound(false);
  const { clip, pill } = lobby();
  assert.equal(pill.getAttribute("aria-pressed"), "false");
  assert.equal(textOf(pill), "Sound");
  assert.equal(iconName(pill), "volume-x");
  assert.equal(pill.getAttribute("aria-label"), "Sound: the takes' own sound and the studio's clicks");
  assert.equal(pill.getAttribute("title"), "Sound: the takes' own sound and the studio's clicks, remembered in this browser");
  assert.equal(clip.muted, true);
  assert.equal(waiting(), 0, "nothing waits for a gesture when the choice is off");

  pill.dispatch("click");
  assert.equal(w.store.get("openfield.sound"), "on");
  assert.equal(studio.soundOn(), true);
  assert.equal(pill.getAttribute("aria-pressed"), "true");
  assert.equal(textOf(pill), "Sound on");
  assert.equal(iconName(pill), "volume-2");
  assert.equal(clip.muted, false, "the takes' own sound is on");
  assert.equal(clip.paused, false, "and the trailer plays, as the press asked");

  pill.dispatch("click");
  assert.equal(w.store.get("openfield.sound"), "off");
  assert.equal(pill.getAttribute("aria-pressed"), "false");
  assert.equal(textOf(pill), "Sound");
  assert.equal(clip.muted, true);
});

test("a click on the pill ticks once each way, as a switch does", () => {
  world();
  studio.setSound(false);
  studio.wireSounds(); // the document's one listener, as main.js wires it
  const { pill } = lobby();
  later();
  FakeAudio.one?.voices.splice(0);
  pill.children[1].dispatch("click"); // pressed on its word
  assert.equal(studio.soundOn(), true);
  assert.deepEqual(FakeAudio.one.voices.map((v) => cueOf(v)), ["tick"], "on: one tick, from the pill, since the document hears the press before the switch is on");
  later();
  FakeAudio.one.voices.splice(0);
  pill.children[0].dispatch("click"); // pressed on its icon, which the last paint made
  assert.equal(studio.soundOn(), false);
  assert.deepEqual(FakeAudio.one.voices.map((v) => cueOf(v)), ["tick"], "off: one tick, the document hears the press before the switch is off");
});

test("the pill reads the stored choice wherever the Lobby is built, and the trailer still starts silent", () => {
  world();
  studio.setSound(true); // remembered from an earlier visit
  const { clip, pill } = lobby();
  assert.equal(pill.getAttribute("aria-pressed"), "true");
  assert.equal(textOf(pill), "Sound on");
  assert.equal(clip.muted, true, "a trailer never starts with its sound on");
  assert.equal(clip.paused, true, "and creating the screen plays nothing");
});

test("an audible trailer keeps its decoder when the galleries crowd the slots; a silent one is an ordinary loop", () => {
  world();
  studio.setSound(false);
  const quiet = lobby();
  nearView(quiet.clip); // the wall's watcher starts it, muted
  assert.equal(quiet.clip.paused, false);
  crowd();
  assert.equal(quiet.clip.paused, true, "a muted trailer is the oldest loop and yields its slot");

  const loud = lobby();
  const pinned = slots().pinned;
  loud.pill.dispatch("click");
  assert.equal(loud.clip.paused, false);
  assert.equal(slots().pinned, pinned + 1, "pressing the pill pins the trailer to a decoder");
  crowd();
  assert.equal(loud.clip.paused, false, "an audible trailer is not paused by another loop");
  assert.equal(slots().pinned, pinned + 1);
});

test("the wall's watcher starting the trailer again keeps it pinned while it is audible", () => {
  world();
  studio.setSound(false);
  const { clip, pill } = lobby();
  pill.dispatch("click");
  assert.equal(slots().pinned, 1);
  leaveView(clip); // scrolled away: the wall lets go of it
  assert.equal(slots().pinned, 0);
  assert.equal(clip.paused, true);
  nearView(clip); // back in view
  assert.equal(clip.paused, false);
  assert.equal(clip.muted, false);
  assert.equal(slots().pinned, 1, "it plays with its sound, so no loop may take its decoder");
});

test("leaving the room mutes the trailer and leaves the studio's choice alone", () => {
  const w = world({ activated: true });
  studio.setSound(true);
  const { screen, clip, pill } = lobby();
  pill.dispatch("click"); // off
  pill.dispatch("click"); // on, and heard
  assert.equal(clip.muted, false);
  screen.stop();
  assert.equal(clip.muted, true, "the trailer's sound never follows the person into another room");
  assert.equal(studio.soundOn(), true, "the choice stands");
  assert.equal(w.store.get("openfield.sound"), "on", "and nothing is written");
  assert.equal(pill.getAttribute("aria-pressed"), "true", "the pill still reads the choice");
  assert.equal(textOf(pill), "Sound on");
});

test("entering the room again by a click: sound on is heard at once, sound off stays silent", () => {
  world({ activated: true });
  studio.setSound(true);
  const on = lobby();
  on.screen.stop();
  on.screen.wake();
  assert.equal(on.clip.muted, false, "the person already pressed something on this page: the browser allows it");
  assert.equal(waiting(), 0);
  on.screen.stop();
  studio.setSound(false);
  on.screen.wake();
  assert.equal(on.clip.muted, true, "the choice is off");
});

test("a page nobody has pressed on yet waits for the first press instead of asking the browser for sound", () => {
  world({ activated: false });
  studio.setSound(true);
  const { screen, clip } = lobby();
  screen.wake();
  assert.equal(clip.muted, true);
  assert.equal(waiting(), 3, "waiting, once, for the first gesture");
  document.body.dispatch("pointerdown", { pointerType: "mouse" });
  assert.equal(clip.muted, false);
  assert.equal(waiting(), 0);
});

test("a remembered choice unmutes the trailer at the first press or key on the Lobby, then stops listening", () => {
  world();
  studio.setSound(true);
  const { clip, pill, station } = lobby();
  assert.equal(clip.muted, true);
  assert.equal(waiting(), 3, "pointerdown, pointerup and keydown wait for the first gesture");

  pill.dispatch("pointerdown", { pointerType: "mouse" });
  assert.equal(clip.muted, true, "the pill makes its own choice");
  document.body.dispatch("keydown", { key: "Escape" });
  assert.equal(clip.muted, true, "Escape is not a gesture a browser counts");
  document.body.dispatch("pointerdown", { pointerType: "touch" });
  assert.equal(clip.muted, true, "a touch counts when it lifts, not when it lands");
  station.hidden = true;
  document.body.dispatch("pointerdown", { pointerType: "mouse" });
  assert.equal(clip.muted, true, "a press in another room is not for this trailer");
  assert.equal(waiting(), 3, "and the listeners wait on");
  station.hidden = false;

  document.body.dispatch("pointerup", { pointerType: "touch" });
  assert.equal(clip.muted, false, "the first press on the Lobby unmutes it");
  assert.equal(waiting(), 0, "and the listeners are gone");
  assert.equal(studio.soundOn(), true);
});

test("a key is a gesture too, and a mouse press counts as it lands", () => {
  world();
  studio.setSound(true);
  const a = lobby();
  document.body.dispatch("keydown", { key: "Tab" });
  assert.equal(a.clip.muted, false);
  assert.equal(waiting(), 0);
  a.screen.stop();
  studio.setSound(true);
  const b = lobby();
  document.body.dispatch("pointerdown", { pointerType: "mouse" });
  assert.equal(b.clip.muted, false);
});

test("the pill's own press is the choice, not a first gesture: from a remembered on it turns the sound off", () => {
  const w = world();
  studio.setSound(true);
  const { clip, pill } = lobby();
  pill.dispatch("pointerdown", { pointerType: "mouse" });
  pill.dispatch("pointerup", { pointerType: "mouse" });
  pill.dispatch("click");
  assert.equal(studio.soundOn(), false);
  assert.equal(w.store.get("openfield.sound"), "off");
  assert.equal(clip.muted, true);
  assert.equal(waiting(), 0, "nothing is left waiting");
  document.body.dispatch("pointerdown", { pointerType: "mouse" });
  assert.equal(clip.muted, true, "and a later press does not turn it back on");
});

test("a press that unmutes a playing trailer pins it", () => {
  world();
  studio.setSound(true);
  const { clip } = lobby();
  nearView(clip);
  assert.equal(clip.paused, false);
  assert.equal(slots().pinned, 0, "a silent trailer is an ordinary loop");
  document.body.dispatch("pointerdown", { pointerType: "mouse" });
  assert.equal(clip.muted, false);
  assert.equal(slots().pinned, 1);
  crowd();
  assert.equal(clip.paused, false);
});

test("reduced motion holds the trailer still even when sound is on: a press unmutes, nothing plays", () => {
  world({ reduced: true });
  studio.setSound(true);
  const { clip } = lobby();
  nearView(clip);
  assert.equal(clip.paused, true, "the wall does not start it");
  document.body.dispatch("keydown", { key: "ArrowDown" });
  assert.equal(clip.muted, false, "sound is not motion");
  assert.equal(clip.paused, true, "but a press is not a request to play");
});

test("the reel plays from a cut, and the trailer is pinned only while it is audible", async () => {
  world();
  const segments = [{ start: 0, end: 2, label: "Dolly in", take: "tk_1" }, { start: 2, end: 5, label: "Orbit", take: "tk_2" }];
  stub("fetch", async () => ({ ok: true, json: async () => ({ segments }) }));
  studio.setSound(false);
  const { clip } = lobby();
  await new Promise((r) => setTimeout(r, 0));
  const cuts = document.body.querySelectorAll(".reel-cut");
  assert.equal(cuts.length, 2);
  const playing = slots().playing;
  cuts[1].dispatch("click");
  assert.equal(clip.currentTime, 2.01);
  assert.equal(clip.paused, false);
  assert.equal(slots().playing, playing + 1, "the trailer plays within the page's decoder budget, as any loop does");
  assert.equal(slots().pinned, 0, "a silent trailer is no one's pinned video");
  clip.pause();
  studio.setSound(true);
  clip.muted = false; // what the pill does when it turns the sound on
  cuts[0].dispatch("click");
  assert.equal(clip.currentTime, 0.01);
  assert.equal(slots().pinned, 1, "with its sound on it is");
});

// -- Name the move ----------------------------------------------------------------------------------------------------

const previews = (() => {
  const takes = {};
  const moves = {};
  for (const m of catalog.moves.filter((x) => x.validated)) { takes[`tk_${m.id}`] = { video: `showcase/${m.id}.mp4`, poster: `showcase/${m.id}.webp` }; moves[m.id] = `tk_${m.id}`; }
  return { takes, moves };
})();

test("Name the move pings a right answer and dulls a wrong one, and says nothing while sound is off", () => {
  world();
  const state = { moves: catalog, previews, recorded: [] };
  const quiz = createQuiz({ store: { get: () => state }, api: { asset: (p) => p, media: (_, f) => f }, ui: { openTake() {} } });
  document.body.append(quiz.el);
  const [first] = dailyQuiz({ moves: catalog.moves, previews, day: quizDay() });
  const answer = (right) => {
    quiz.start();
    const picks = quiz.el.querySelectorAll(".quiz-choice");
    assert.equal(picks.length, 4);
    FakeAudio.one?.voices.splice(0);
    later();
    picks.find((b) => (b.dataset.id === first.answer) === right).dispatch("click");
    return FakeAudio.one?.voices.map((v) => cueOf(v)) ?? [];
  };
  studio.setSound(true);
  assert.deepEqual(answer(true), ["ping"], "a right answer is a bulb's ping");
  assert.deepEqual(answer(false), ["dull"], "a wrong one is a low tick");
  assert.ok(quiz.el.querySelector(".quiz-reveal"), "and the reveal is built either way");
  studio.setSound(false);
  assert.deepEqual(answer(true), [], "nothing sounds while the switch is off");
  quiz.stop();
});

// -- the page's sources -----------------------------------------------------------------------------------------------

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* walk(path);
    else yield path;
  }
}

test("main.js wires the studio's sounds once, right after the shell is mounted", () => {
  const main = source("js/main.js");
  assert.match(main, /import \{ wireSounds \} from "\.\/ui\/sound\.js";/);
  assert.match(main, /mountShell\(ctx\);\s*wireSounds\(\);/);
  assert.equal(main.split("wireSounds(").length - 1, 1);
});

test("the quiz plays in the Lobby only: openQuiz and its sheet import are gone, and a choice cues", () => {
  const quiz = source("js/ui/quiz.js");
  assert.match(quiz, /import \{ play as cue \} from "\.\/sound\.js";/);
  assert.match(quiz, /cue\(right \? "ping" : "dull"\)/);
  assert.ok(!/from "\.\/sheet\.js"/.test(quiz), "nothing in the quiz opens a sheet any more");
  const root = fileURLToPath(new URL("js", WEB));
  const users = [...walk(root)].filter((p) => p.endsWith(".js") && /openQuiz/.test(readFileSync(p, "utf8")));
  assert.deepEqual(users, [], "no code is left that opens the quiz in a sheet");
});

test("no audio element and no Audio object anywhere in the page", () => {
  const files = [...walk(fileURLToPath(new URL("js", WEB))), fileURLToPath(new URL("index.html", WEB))].filter((p) => /\.(js|html)$/.test(p));
  assert.ok(files.length > 40, "the scan found the page's scripts");
  const found = files.filter((p) => /<audio\b|createElement\(["']audio["']\)|\bnew Audio\(|\bh\(["']audio["']/.test(readFileSync(p, "utf8")));
  assert.deepEqual(found, [], "sound comes from the video elements and the Web Audio cues only");
});

test("screen.js loads in Node, keeps the shared motion helper, and writes the choice only from the pill", () => {
  assert.equal(typeof createScreen, "function");
  const screen = source("js/ui/screen.js");
  assert.match(screen, /import \{ holdStill \} from "\.\.\/lib\/motion\.js";/);
  assert.ok(!/reducedMotion\(/.test(screen), "Save-Data holds the screen as still as reduced motion does");
  assert.equal(screen.match(/setSound\(/g).length, 1, "only the pill's own press writes the choice");
  assert.ok(!/sound\.click\(\)/.test(screen), "leaving the room no longer presses the pill");
});
