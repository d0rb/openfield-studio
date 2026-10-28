import test from "node:test";
import assert from "node:assert/strict";

// The browser's globals the room's light asks for, stubbed before it loads: a document that makes elements and says when the
// tab hides, two media queries (a wide screen that hovers, reduced motion), a connection that may be saving data, and
// animation frames the tests run by hand. Every call is written down, so a test can see that loading the module did nothing.
const calls = [];
const media = { wide: true, reduced: false };
let saveData = false;
globalThis.matchMedia = (query) => {
  calls.push(`matchMedia ${query}`);
  const matches = query === "(prefers-reduced-motion: reduce)" ? media.reduced : query === "(hover: hover) and (min-width: 900px)" ? media.wide : false;
  return { media: query, matches };
};
Object.defineProperty(globalThis, "navigator", { configurable: true, get: () => ({ connection: { saveData } }) });
const frames = new Map();
let lastFrame = 0;
globalThis.requestAnimationFrame = (fn) => { calls.push("requestAnimationFrame"); frames.set(++lastFrame, fn); return lastFrame; };
globalThis.cancelAnimationFrame = (id) => { frames.delete(id); };
/** One turn of the browser's frame loop: run the frames that were waiting. Returns how many ran. */
const tick = () => { const due = [...frames.values()]; frames.clear(); for (const fn of due) fn(); return due.length; };

globalThis.Node = class Node {}; // dom.js's h() asks whether a child is a Node
/** An element as far as the light needs one: attributes, classes, a style, children, listeners and a box. */
class Fake extends globalThis.Node {
  constructor(tag) {
    super();
    this.tagName = tag.toUpperCase();
    this.attrs = {};
    this.names = new Set();
    this.children = [];
    this.listeners = {};
    this.style = {};
    this.box = { left: 0, top: 0, width: 0, height: 0 };
    this.classList = { add: (...n) => n.forEach((c) => this.names.add(c)), remove: (...n) => n.forEach((c) => this.names.delete(c)), contains: (c) => this.names.has(c) };
  }
  setAttribute(key, value) {
    this.attrs[key] = String(value);
    if (key === "class") this.names = new Set(String(value).split(/\s+/).filter(Boolean));
  }
  append(...kids) { this.children.push(...kids); }
  addEventListener(type, fn, options) { calls.push(`listen ${type}`); (this.listeners[type] ??= []).push({ fn, options }); }
  fire(type, event = {}) { for (const { fn } of this.listeners[type] ?? []) fn({ type, ...event }); }
  getBoundingClientRect() { return this.box; }
}
const doc = new Fake("#document");
doc.createElement = (tag) => { calls.push(`createElement ${tag}`); return new Fake(tag); };
doc.createTextNode = (text) => ({ text });
globalThis.document = doc;

const { createAmbient, lightStep, HALF } = await import("../../openfield/web/js/ui/ambient.js");
const atImport = [...calls];

const near = (a, b, within = 1e-9) => Math.abs(a - b) <= within;
/** The light's place from its transform: where its box's top left corner sits in the layer. */
const placeOf = (light) => {
  const m = /^translate3d\((-?[\d.]+)px, (-?[\d.]+)px, 0\)$/.exec(light.style.transform ?? "");
  return m ? { x: Number(m[1]), y: Number(m[2]) } : null;
};
/** A stage and its light layer, the layer's box 100 px from the left and 50 px down; motion allowed on a wide screen. */
function room() {
  Object.assign(media, { wide: true, reduced: false });
  saveData = false;
  frames.clear();
  const stage = new Fake("main");
  const { el } = createAmbient(stage);
  el.box = { left: 100, top: 50, width: 1000, height: 800 };
  const light = el.children[2];
  const move = (clientX, clientY, pointerType = "mouse") => stage.fire("pointermove", { pointerType, clientX, clientY });
  return { stage, el, light, move };
}

test("loading the module does nothing: no element, no listener, no media query, no frame", () => {
  assert.deepEqual(atImport, []);
});

test("one step of the glide goes k of the way, and the steps close in on the pointer", () => {
  const step = lightStep({ x: 0, y: 0 }, { x: 100, y: -50 }, 0.18);
  assert.ok(near(step.x, 18) && near(step.y, -9), JSON.stringify(step));
  assert.deepEqual(lightStep({ x: 5, y: 5 }, { x: 15, y: 25 }, 0), { x: 5, y: 5 });
  assert.deepEqual(lightStep({ x: 5, y: 5 }, { x: 15, y: 25 }, 1), { x: 15, y: 25 });
  assert.deepEqual(lightStep({ x: 10, y: 20 }, { x: 10, y: 20 }, 0.18), { x: 10, y: 20 }, "already there: it stays");
  let at = { x: 0, y: 0 };
  let steps = 0;
  while (Math.hypot(300 - at.x, 200 - at.y) > 0.5) { at = lightStep(at, { x: 300, y: 200 }, 0.18); steps += 1; }
  assert.ok(steps < 40, `${steps} frames to come within half a pixel from 360 px away`);
});

test("the layer is a decorative div holding the beam, the dust and the house light, and it listens only once it is made", () => {
  const before = calls.length;
  const { stage, el } = room();
  assert.equal(el.tagName, "DIV");
  assert.ok(el.classList.contains("ambient"));
  assert.equal(el.attrs["aria-hidden"], "true");
  assert.deepEqual(el.children.map((c) => [c.tagName, c.attrs.class]), [["SPAN", "ambient-beam"], ["SPAN", "ambient-dust"], ["SPAN", "house-light"]]);
  assert.deepEqual(Object.keys(stage.listeners).sort(), ["pointerleave", "pointermove"]);
  assert.equal(stage.listeners.pointermove[0].options?.passive, true, "a pointer move never waits on the light");
  assert.ok(doc.listeners.visibilitychange?.length >= 1);
  assert.ok(!calls.slice(before).includes("requestAnimationFrame"), "no frame until the pointer moves");
});

test("a mouse on a wide screen with motion allowed lights the floor where it is, then the light glides after it", () => {
  const { el, light, move } = room();
  move(600, 450);
  assert.ok(el.classList.contains("lit"));
  assert.deepEqual(placeOf(light), { x: 500 - HALF, y: 400 - HALF }, "centred on the pointer, in the layer's own pixels (600 - 100 - HALF, 450 - 50 - HALF)");
  assert.equal(frames.size, 0, "the first move places the light: nothing to glide");
  move(700, 450);
  assert.equal(frames.size, 1, "a move asks for a frame");
  move(800, 450);
  assert.equal(frames.size, 1, "and only one, however many moves come before it runs");
  tick();
  assert.deepEqual(placeOf(light), { x: 536 - HALF, y: 400 - HALF }, "18% of the way from 500 to 700");
  assert.equal(frames.size, 1, "still far off: it asks for the next frame");
  let ran = 0;
  while (tick()) ran += 1;
  const at = placeOf(light);
  assert.ok(ran < 40 && Math.hypot(700 - HALF - at.x, 400 - HALF - at.y) <= 0.5, `settled within half a pixel after ${ran} more frames at ${JSON.stringify(at)}`);
  assert.equal(frames.size, 0, "settled: no frame is left running");
});

test("nothing lights or moves for a touch, a pen, a narrow or touch screen, reduced motion or a data saver", () => {
  const cases = {
    touch: (r) => { r.move(600, 450, "touch"); r.move(700, 450, "touch"); },
    pen: (r) => { r.move(600, 450, "pen"); r.move(700, 450, "pen"); },
    "a narrow or touch screen": (r) => { media.wide = false; r.move(600, 450); r.move(700, 450); },
    "reduced motion": (r) => { media.reduced = true; r.move(600, 450); r.move(700, 450); },
    "a data saver": (r) => { saveData = true; r.move(600, 450); r.move(700, 450); },
  };
  for (const [name, run] of Object.entries(cases)) {
    const r = room();
    run(r);
    assert.ok(!r.el.classList.contains("lit"), `${name}: not lit`);
    assert.equal(frames.size, 0, `${name}: no frame`);
    assert.equal(placeOf(r.light), null, `${name}: the light never moved`);
  }
});

test("the pointer leaving the stage puts the light out, and the next move lights it where the pointer is, with no glide across", () => {
  const { stage, el, light, move } = room();
  move(600, 450);
  move(700, 450);
  stage.fire("pointerleave");
  assert.ok(!el.classList.contains("lit"));
  const left = placeOf(light);
  tick();
  assert.deepEqual(placeOf(light), left, "the waiting frame does nothing once the pointer has gone");
  assert.equal(frames.size, 0);
  move(300, 300);
  assert.ok(el.classList.contains("lit"));
  assert.deepEqual(placeOf(light), { x: 200 - HALF, y: 250 - HALF }, "it comes up at the pointer");
  assert.equal(frames.size, 0, "no glide from where it went out");
});

test("a hidden tab cancels the frame that was waiting", () => {
  const { move } = room();
  move(600, 450);
  move(700, 450);
  assert.equal(frames.size, 1);
  doc.fire("visibilitychange");
  assert.equal(frames.size, 0);
});
