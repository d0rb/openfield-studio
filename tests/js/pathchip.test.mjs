import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// A page as far as the glyphs and the chip need one: elements with attributes, classes, children, listeners and the two
// states the chip asks about; frames run by hand; a motion preference that can change.
class El {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.attrs = new Map();
    this.names = new Set();
    this.children = [];
    this.parentNode = null;
    this.listeners = {};
    this.states = new Set(); // ":hover", ":focus-visible"
    this.classList = { add: (...c) => { c.forEach((n) => this.names.add(n)); this.attrs.set("class", [...this.names].join(" ")); }, contains: (n) => this.names.has(n) };
  }
  setAttribute(k, v) { this.attrs.set(k, String(v)); if (k === "class") this.names = new Set(String(v).split(/\s+/).filter(Boolean)); }
  getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null; }
  append(...kids) { for (const k of kids) { k.remove(); k.parentNode = this; this.children.push(k); } }
  after(...kids) { const p = this.parentNode; let i = p.children.indexOf(this); for (const k of kids) { k.remove(); k.parentNode = p; p.children.splice(++i, 0, k); } }
  remove() { if (this.parentNode) this.parentNode.children.splice(this.parentNode.children.indexOf(this), 1); this.parentNode = null; }
  matches(sel) { return sel.startsWith(":") ? this.states.has(sel) : sel.slice(1).split(".").every((c) => this.names.has(c)); }
  querySelector(sel) { for (const k of this.children) { if (k.matches(sel)) return k; const deep = k.querySelector(sel); if (deep) return deep; } return null; }
  addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
  dispatch(type, props = {}) { for (const fn of this.listeners[type] ?? []) fn({ type, target: this, ...props }); }
}
globalThis.Node = El;
globalThis.document = { createElementNS: (_, tag) => new El(tag), createElement: (tag) => new El(tag), createTextNode: (text) => ({ text }) };
const frames = new Map();
let frameId = 0;
globalThis.requestAnimationFrame = (fn) => { frames.set(++frameId, fn); return frameId; };
globalThis.cancelAnimationFrame = (id) => frames.delete(id);
const tick = () => { const due = [...frames.values()]; frames.clear(); due.forEach((fn) => fn()); };
const prefs = { reduced: false };
globalThis.matchMedia = (query) => ({ matches: query.includes("reduce") && prefs.reduced, addEventListener() {} });

const { chipOn, pathChip, tileGlyph, tilePlan } = await import("../../openfield/web/js/ui/pathchip.js");
const { glyph } = await import("../../openfield/web/js/lib/pathview.js");
const catalog = JSON.parse(readFileSync(new URL("./fixtures/catalog.json", import.meta.url), "utf8"));
const kindOf = (kind) => catalog.moves.find((m) => glyph(m).kind === kind);
const lit = (chip) => chip.el.querySelector(".g-lit");

test("a dolly's chip carries its track twice: the drawn one and the lit one over it, as one dash of length 1", () => {
  const chip = pathChip(catalog, "dolly_in");
  assert.ok(chip.el.classList.contains("tile-plan"));
  const track = chip.el.querySelector(".g-path");
  const over = lit(chip);
  assert.ok(over, "a travelling move has a lit track");
  assert.equal(over.getAttribute("pathLength"), "1");
  assert.equal(over.getAttribute("stroke-dashoffset"), "1", "nothing travelled before the footage starts");
  assert.equal(over.getAttribute("d"), track.getAttribute("d"));
  assert.equal(chip.el.children.indexOf(over), chip.el.children.indexOf(track) + 1, "right after the track: the start and the arrowhead stay on top");
});

test("seek lights the track to the footage's share, clamped to the move", () => {
  const chip = pathChip(catalog, "dolly_in");
  chip.seek(0.5);
  assert.equal(lit(chip).getAttribute("stroke-dashoffset"), "0.5000");
  chip.seek(0.25);
  assert.equal(lit(chip).getAttribute("stroke-dashoffset"), "0.7500");
  chip.seek(3);
  assert.equal(lit(chip).getAttribute("stroke-dashoffset"), "0.0000");
  chip.seek(-1);
  assert.equal(lit(chip).getAttribute("stroke-dashoffset"), "1.0000");
  chip.seek(Number.NaN);
  assert.equal(lit(chip).getAttribute("stroke-dashoffset"), "1.0000", "a length not known yet is the start");
});

test("a zoom, a turn and a still keep their symbols: no track to light, and seek does nothing", () => {
  for (const kind of ["zoom", "turn", "still"]) {
    const move = kindOf(kind);
    assert.ok(move, `the catalog has a ${kind}`);
    const chip = pathChip(catalog, move.id);
    assert.ok(!chip.el.classList.contains("tile-plan") && !lit(chip), `${move.id} has no lit track`);
    assert.doesNotThrow(() => chip.seek(0.5));
  }
  assert.ok(pathChip(catalog, kindOf("turn").id).el.querySelector(".g-path"), "a turn's arc is a .g-path too, outside a .tile-plan");
});

test("a move the catalog does not have gets no chip", () => {
  assert.equal(pathChip(catalog, "no_such_move"), null);
  assert.equal(pathChip(null, "dolly_in"), null, "the catalog has not loaded yet");
});

test("the camera's starting position pivots the drawn path; the hero's own position leaves it as it was", () => {
  const plain = lit(pathChip(catalog, "dolly_in")).getAttribute("d");
  assert.notEqual(lit(pathChip(catalog, "dolly_in", { angle: "back_left/low/wide" })).getAttribute("d"), plain);
  assert.equal(lit(pathChip(catalog, "dolly_in", { angle: catalog.angles.default })).getAttribute("d"), plain);
});

test("the glyphs moved here unchanged: a travelling move draws its plan, a zoom its frames", () => {
  const plan = tilePlan(catalog.moves.find((m) => m.id === "crane_up"));
  assert.deepEqual(plan.children.map((c) => c.getAttribute("class")), ["g-post", "g-subject", "g-path", "g-start", "g-head"]);
  assert.deepEqual(tileGlyph(kindOf("zoom")).children.map((c) => c.getAttribute("class")), ["g-frame faint", "g-frame"]);
});

test("hover lays the chip on the frame and the footage's own time drives it, the scrub included; leaving takes it down", () => {
  const box = new El("button");
  const frame = new El("span");
  box.append(frame);
  const video = { duration: 4, currentTime: 1 };
  chipOn(box, () => video, { catalog: () => catalog, movement: "dolly_in", into: frame });
  box.dispatch("pointerenter", { pointerType: "touch" });
  assert.equal(frame.querySelector(".path-chip"), null, "a finger gets no chip");
  box.dispatch("pointerenter", { pointerType: "mouse" });
  const chip = frame.querySelector(".path-chip");
  assert.ok(chip?.querySelector(".g-lit"), "the chip of a travelling move, with its lit track");
  assert.equal(chip.querySelector(".g-lit").getAttribute("stroke-dashoffset"), "0.7500", "read at once: a quarter through");
  video.currentTime = 3; // the loop played on, or the mouse scrubbed it there
  tick();
  assert.equal(chip.querySelector(".g-lit").getAttribute("stroke-dashoffset"), "0.2500");
  box.dispatch("pointerleave");
  assert.equal(frame.querySelector(".path-chip"), null);
  assert.equal(frames.size, 0, "no frame keeps running once the chip is down");
});

test("keyboard focus shows the chip as hover does; a click's focus or a held-still page does not", () => {
  const box = new El("a");
  chipOn(box, null, { catalog: () => catalog, movement: "dolly_in" });
  box.dispatch("focus");
  assert.equal(box.querySelector(".path-chip"), null, "focus that does not show (a click, a tap) brings no chip");
  box.states.add(":focus-visible");
  box.dispatch("focus");
  assert.ok(box.querySelector(".path-chip"));
  box.dispatch("pointerleave");
  assert.ok(box.querySelector(".path-chip"), "the pointer leaving does not take it from the keyboard");
  box.states.delete(":focus-visible");
  box.dispatch("blur");
  assert.equal(box.querySelector(".path-chip"), null);
  prefs.reduced = true;
  try {
    box.dispatch("pointerenter", { pointerType: "mouse" });
    assert.equal(box.querySelector(".path-chip"), null, "nothing follows the footage under reduced motion");
  } finally {
    prefs.reduced = false;
  }
  frames.clear();
});
