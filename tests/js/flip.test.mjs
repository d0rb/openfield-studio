import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { flip, flipPlan } from "../../openfield/web/js/ui/dom.js";

const rect = (top, left = 0) => ({ left, top, bottom: top + 10 });
const EASE = "cubic-bezier(0.16, 1, 0.3, 1)";
// the browser globals flip() reads: the window height (tall enough for every column here) and the page --ease
globalThis.innerHeight = 1000;
globalThis.document = { documentElement: {} };
globalThis.getComputedStyle = () => ({ getPropertyValue: (name) => (name === "--ease" ? ` ${EASE}` : "") });
const source = (name) => readFileSync(new URL(`../../openfield/web/js/ui/${name}.js`, import.meta.url), "utf8");

// -- the matching of old places to new ones (no DOM) -----------------------------------------------------------

test("children match by key, not by place: a re-rank moves them, a new key enters", () => {
  const before = new Map([["a", rect(0)], ["b", rect(10)], ["c", rect(20)]]);
  const after = new Map([["c", rect(0)], ["a", rect(10)], ["b", rect(20)], ["d", rect(30)]]);
  const { moved, entered } = flipPlan(before, after);
  assert.deepEqual(moved, [{ key: "c", dx: 0, dy: 20 }, { key: "a", dx: 0, dy: -10 }, { key: "b", dx: 0, dy: -10 }]);
  assert.deepEqual(entered, ["d"]);
});

test("a child that stayed, a jitter under a pixel and a child that left are not moves", () => {
  const before = new Map([["a", rect(0)], ["b", rect(10)], ["gone", rect(20)]]);
  const after = new Map([["a", rect(0)], ["b", rect(10.5)]]);
  assert.deepEqual(flipPlan(before, after), { moved: [], entered: [] });
  assert.deepEqual(flipPlan(before, after, { shift: 0.25 }).moved, [{ key: "b", dx: 0, dy: -0.5 }], "the threshold is the caller's");
});

test("a move sideways counts too (a grid of cards)", () => {
  const { moved } = flipPlan(new Map([["a", rect(0, 0)]]), new Map([["a", rect(0, 260)]]));
  assert.deepEqual(moved, [{ key: "a", dx: -260, dy: 0 }]);
});

test("only what can be seen animates: off screen before and after is skipped", () => {
  const within = { top: 0, bottom: 100 };
  const before = new Map([["near", rect(0)], ["rises", rect(300)], ["far", rect(400)]]);
  const after = new Map([["near", rect(10)], ["rises", rect(50)], ["far", rect(410)], ["new-far", rect(500)], ["new-near", rect(60)]]);
  const { moved, entered } = flipPlan(before, after, { within });
  assert.deepEqual(moved.map((m) => m.key), ["near", "rises"], "a child sliding into view still glides; one that stays below does not");
  assert.deepEqual(entered, ["new-near"]);
});

// -- flip(), on stand-ins for the few DOM parts it touches ------------------------------------------------------

/** A column of children, each 10 px tall: enough of the DOM for flip() (children, offsetParent, rects, animations). */
function column(keys) {
  const calls = [];
  const parent = { offsetParent: {}, children: [], getAnimations: () => parent.children.flatMap((el) => el.getAnimations()) }; // `{ subtree: true }` in the browser
  const make = (key) => ({
    dataset: key == null ? {} : { key },
    y: 0,
    running: [],
    getBoundingClientRect() { return rect(this.y); },
    getAnimations() { return this.running; },
    animate(keyframes, options) {
      const run = { id: options.id, cancelled: false, cancel() { this.cancelled = true; } };
      this.running.push(run);
      calls.push({ el: this, keyframes, options });
      return run;
    },
  });
  const settle = () => parent.children.forEach((el, i) => { el.y = i * 10; });
  parent.children = keys.map(make);
  settle();
  const byKey = (key) => parent.children.find((el) => el.dataset.key === key);
  return { parent, calls, make, settle, byKey };
}

const stubMotion = (reduced) => { globalThis.matchMedia = () => ({ matches: reduced }); };
const clearMotion = () => { delete globalThis.matchMedia; };

test("flip animates what moved from its old place and settles what appeared", () => {
  const { parent, calls, make, settle, byKey } = column(["a", "b", "c"]);
  const [a, b, c] = ["a", "b", "c"].map(byKey);
  let ran = 0;
  const out = flip(parent, () => {
    ran += 1;
    parent.children = [c, a, b, make("d")];
    settle();
    return "reranked";
  });
  assert.equal(ran, 1);
  assert.equal(out, "reranked", "the change's own result comes back");
  assert.deepEqual(calls.map((x) => x.el.dataset.key), ["c", "a", "b", "d"]);
  assert.deepEqual(calls[0].keyframes, [{ translate: "0px 20px" }, { translate: "0 0" }], "c starts where it was: 20 px below its new place");
  assert.deepEqual(calls[1].keyframes, [{ translate: "0px -10px" }, { translate: "0 0" }]);
  assert.deepEqual(calls[3].keyframes, [{ opacity: 0, translate: "0 4px" }, { opacity: 1, translate: "0 0" }], "a new child rises 4 px as it fades in");
  for (const { options } of calls) assert.deepEqual([options.duration, options.id], [180, "flip"]);
  assert.equal(calls[0].options.easing, EASE, "the page --ease itself, not a copy of it");
});

test("flip takes its length from the caller", () => {
  const { parent, calls, byKey } = column(["a", "b"]);
  const [a, b] = ["a", "b"].map(byKey);
  flip(parent, () => { parent.children = [b, a]; parent.children.forEach((el, i) => { el.y = i * 10; }); }, { ms: 90 });
  assert.deepEqual(calls.map((x) => x.options.duration), [90, 90]);
});

test("a change that moves nothing animates nothing", () => {
  const { parent, calls, byKey } = column(["a", "b", "c"]);
  flip(parent, () => { byKey("a").dataset.label = "renamed"; });
  assert.equal(calls.length, 0);
});

test("keys already there in that order mean nothing is measured, and the change still runs once", () => {
  const { parent, calls } = column(["a", "b", "c"]);
  for (const el of parent.children) el.getBoundingClientRect = () => { throw new Error("measured a list that cannot move"); };
  let ran = 0;
  flip(parent, () => { ran += 1; }, { keys: ["a", "b", "c"] });
  assert.deepEqual([ran, calls.length], [1, 0]);
});

test("keys that differ from the ones there are measured as usual (a new key, another order)", () => {
  const first = column(["a", "b", "c"]);
  const [a, b, c] = first.parent.children;
  flip(first.parent, () => { first.parent.children = [c, a, b]; first.settle(); }, { keys: ["c", "a", "b"] });
  assert.equal(first.calls.length, 3);
  const second = column(["a"]);
  flip(second.parent, () => { second.parent.children.push(second.make("b")); second.settle(); }, { keys: ["a", "b"] });
  assert.deepEqual(second.calls.map((x) => x.el.dataset.key), ["b"]);
});

test("children with no key match by identity", () => {
  const { parent, calls, settle } = column([null, null, null]);
  const [x, y, z] = parent.children;
  flip(parent, () => { parent.children = [z, x, y]; settle(); });
  assert.deepEqual(calls.map((c) => c.el), [z, x, y]);
});

test("a rebuilt child with the same key still glides from where its old one stood", () => {
  const { parent, calls, make, settle, byKey } = column(["a", "b"]);
  const old = byKey("b");
  flip(parent, () => { parent.children = [make("b"), parent.children[0]]; settle(); });
  assert.deepEqual(calls.map((c) => c.el.dataset.key), ["b", "a"]);
  assert.notEqual(calls[0].el, old, "the new element is the one that moves");
  assert.deepEqual(calls[0].keyframes[0], { translate: "0px 10px" });
});

test("a glide still under way is cancelled before the change, and nobody else's animation is touched", () => {
  const { parent, byKey } = column(["a", "b"]);
  const a = byKey("a");
  const mine = { id: "flip", cancelled: false, cancel() { this.cancelled = true; } };
  const theirs = { id: "hover", cancelled: false, cancel() { this.cancelled = true; } };
  a.running = [mine, theirs];
  let cancelledByThen = null;
  flip(parent, () => { cancelledByThen = mine.cancelled; });
  assert.equal(cancelledByThen, true, "so the new places are measured without the old glide's offset");
  assert.equal(theirs.cancelled, false);
});

test("what is off screen is not animated", () => {
  const { parent, calls, make, settle } = column(["a", "b", "c"]);
  globalThis.innerHeight = 25;
  try {
    flip(parent, () => { parent.children.push(make("late")); settle(); }); // "late" lands at 30 px, below the 25 px window
  } finally {
    globalThis.innerHeight = 1000;
  }
  assert.equal(calls.length, 0);
});

test("with reduced motion nothing animates, and the change still runs once", () => {
  stubMotion(true);
  try {
    const { parent, calls, make, settle } = column(["a", "b"]);
    let ran = 0;
    const out = flip(parent, () => { ran += 1; parent.children.push(make("c")); settle(); return 7; });
    assert.deepEqual([ran, out, calls.length], [1, 7, 0]);
  } finally {
    clearMotion();
  }
});

test("with Save-Data nothing animates either", () => {
  const was = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  Object.defineProperty(globalThis, "navigator", { value: { connection: { saveData: true } }, configurable: true, writable: true });
  try {
    const { parent, calls, make, settle } = column(["a"]);
    let ran = 0;
    flip(parent, () => { ran += 1; parent.children.push(make("b")); settle(); });
    assert.deepEqual([ran, calls.length], [1, 0]);
  } finally {
    Object.defineProperty(globalThis, "navigator", was);
  }
});

test("a parent that is not on screen is not measured or animated, and the change still runs once", () => {
  const { parent, calls, make, settle } = column(["a", "b"]);
  parent.offsetParent = null; // display: none, or inside something that is
  for (const el of parent.children) el.getBoundingClientRect = () => { throw new Error("measured a hidden list"); };
  let ran = 0;
  flip(parent, () => { ran += 1; parent.children = [make("c")]; settle(); });
  assert.deepEqual([ran, calls.length], [1, 0]);
});

test("the Takes list and the Cast cards re-rank through flip, and the Takes head keeps a ledger line of its own", () => {
  assert.match(source("takes"), /flip\(list, \(\) => renderList\(list/);
  assert.match(source("cast"), /flip\(grid, \(\) => renderList\(grid/);
  assert.match(source("takes"), /class: "takes-ledger/);
});
