import test from "node:test";
import assert from "node:assert/strict";

// The browser's globals the reveal asks for, stubbed before it loads: observers whose callbacks the tests call by hand, a
// viewport, and a motion preference that can change while the page is open.
const seen = { callback: null, options: null, observed: new Set() };
const late = { callback: null, lists: new Set() };
const prefs = { reduced: false, listeners: [] };
globalThis.IntersectionObserver = class {
  constructor(callback, options) { Object.assign(seen, { callback, options }); }
  observe(el) { seen.observed.add(el); }
  unobserve(el) { seen.observed.delete(el); }
};
globalThis.MutationObserver = class {
  constructor(callback) { late.callback = callback; }
  observe(el) { late.lists.add(el); }
};
globalThis.matchMedia = (query) => ({ matches: query.includes("reduce") && prefs.reduced, addEventListener: (_, fn) => prefs.listeners.push(fn) });
globalThis.innerWidth = 1000;
globalThis.innerHeight = 800;

const { ahead, rise, settle, wave } = await import("../../openfield/web/js/ui/reveal.js");

/** An element as far as the reveal needs one: classes, a style, children, a place in the page and a box. */
let place = 0;
class Fake {
  constructor(rect = { top: 0, left: 0 }) {
    this.pos = place++;
    this.rect = rect;
    this.nodeType = 1;
    this.children = [];
    this.parentElement = null;
    this.listeners = {};
    this.vars = {};
    const names = new Set();
    this.classList = { add: (...c) => c.forEach((n) => names.add(n)), contains: (n) => names.has(n) };
    this.style = { setProperty: (k, v) => { this.vars[k] = v; } };
  }
  append(...kids) { for (const k of kids) { k.parentElement = this; this.children.push(k); } return this; }
  addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
  dispatch(type, detail) { for (const fn of this.listeners[type] ?? []) fn({ currentTarget: this, ...detail }); }
  compareDocumentPosition(other) { return other.pos > this.pos ? 4 : 2; }
  getBoundingClientRect() { return this.rect; }
}
const list = (n, rect) => new Fake().append(...Array.from({ length: n }, () => new Fake(rect)));
const has = (el, ...names) => names.every((n) => el.classList.contains(n));
const entry = (target, isIntersecting = true) => ({ target, isIntersecting });

test("the wave takes what came into view together in the page's order, a step apart, at most seven steps", () => {
  const items = Array.from({ length: 10 }, () => new Fake());
  const shuffled = [items[3], items[9], items[0], items[7], items[1], items[8], items[2], items[6], items[4], items[5]];
  assert.deepEqual(wave(shuffled).map(([el, i]) => [items.indexOf(el), i]), [[0, 0], [1, 1], [2, 2], [3, 3], [4, 4], [5, 5], [6, 6], [7, 7], [8, 7], [9, 7]]);
  assert.deepEqual(wave([]), []);
});

test("a child added late waits only while it is still ahead of the view", () => {
  assert.equal(ahead({ top: 760, left: 0 }, 1000, 800), true, "below the line the reveal watches (8% up from the bottom)");
  assert.equal(ahead({ top: 300, left: 1200 }, 1000, 800), true, "past the right edge, further along a rail");
  assert.equal(ahead({ top: 300, left: 40 }, 1000, 800), false, "in view");
  assert.equal(ahead({ top: -900, left: 40 }, 1000, 800), false, "above the view: scrolled past");
  assert.equal(ahead({ top: 0, left: 0 }, 1000, 800), false, "a hidden room measures zeros: shown as it is");
});

test("a list is armed and watched item by item; what comes into view rises in a wave, the rest waits", () => {
  const wall = list(4);
  rise(wall);
  assert.ok(has(wall, "armed"));
  assert.equal(seen.options.rootMargin, "0px 0px -8% 0px");
  assert.ok(wall.children.every((c) => seen.observed.has(c)));
  const [a, b, c, d] = wall.children;
  seen.callback([entry(c), entry(a), entry(b, false), entry(d, false)]);
  assert.ok(has(a, "in") && has(c, "in") && !has(b, "in") && !has(d, "in"));
  assert.deepEqual([a.vars["--i"], c.vars["--i"]], ["0", "1"], "the page's order, not the order the entries came in");
  assert.ok(!seen.observed.has(a) && !seen.observed.has(c) && seen.observed.has(b), "a risen item is no longer watched");
  seen.callback([entry(b), entry(d)]);
  assert.deepEqual([b.vars["--i"], d.vars["--i"]], ["0", "1"], "a later arrival starts its own wave");
});

test("an item is done when its rise ends or is cut off, so a room shown again never replays it", () => {
  const wall = list(3);
  rise(wall);
  const [a, b, c] = wall.children;
  seen.callback([entry(a), entry(b), entry(c)]);
  wall.dispatch("animationend", { target: a, animationName: "lobby-rise" });
  wall.dispatch("animationcancel", { target: b, animationName: "lobby-rise" }); // its room was hidden mid-rise
  assert.ok(has(a, "done") && has(b, "done"));
  const inner = new Fake();
  c.append(inner);
  wall.dispatch("animationend", { target: inner, animationName: "lobby-rise" });
  wall.dispatch("animationend", { target: c, animationName: "lobby-take-in" });
  assert.ok(!has(c, "done"), "only the item's own rise counts, not a picture's inside it");
});

test("a section head rises on its own", () => {
  const head = new Fake();
  rise(head, { self: true });
  assert.ok(has(head, "armed-self") && seen.observed.has(head));
  seen.callback([entry(head)]);
  assert.ok(has(head, "in") && head.vars["--i"] === "0");
  head.dispatch("animationend", { target: head, animationName: "lobby-lift" });
  assert.ok(has(head, "done"));
});

test("children added to a list that has begun arrive shown, unless they are still ahead of the view", () => {
  const grid = list(2);
  rise(grid);
  seen.callback([entry(grid.children[0])]);
  const near = new Fake({ top: 200, left: 0 });
  const below = new Fake({ top: 900, left: 0 });
  grid.append(near, below);
  late.callback([{ target: grid, addedNodes: [near, below], removedNodes: [] }]);
  assert.ok(has(near, "in", "done") && !seen.observed.has(near), "no second wave");
  assert.ok(!has(below, "in") && seen.observed.has(below), "its turn comes when it is reached");
});

test("a list that has not begun lets every new child wait its turn; a rebuilt list keeps the places it had shown", () => {
  const fresh = list(0);
  rise(fresh);
  const kids = [new Fake({ top: 100, left: 0 }), new Fake({ top: 900, left: 0 })];
  fresh.append(...kids);
  late.callback([{ target: fresh, addedNodes: kids, removedNodes: [] }]);
  assert.ok(kids.every((k) => !has(k, "in") && seen.observed.has(k)), "the move grid built when the previews arrive still rises");

  const wall = list(3);
  rise(wall);
  seen.callback([entry(wall.children[0]), entry(wall.children[1])]);
  const old = [...wall.children];
  const rebuilt = [new Fake({ top: 1200, left: 0 }), new Fake({ top: 1300, left: 0 }), new Fake({ top: 1400, left: 0 })];
  late.callback([{ target: wall, addedNodes: rebuilt, removedNodes: old }]);
  assert.ok(has(rebuilt[0], "done") && has(rebuilt[1], "done"), "the two places that had risen are shown, even scrolled away");
  assert.ok(!has(rebuilt[2], "in") && seen.observed.has(rebuilt[2]), "the place never reached still waits");
  assert.ok(old.every((o) => !seen.observed.has(o)), "a removed child is no longer watched");
});

test("settle shows a list as it stands: every child done, nothing left to rise", () => {
  const grid = list(5);
  rise(grid);
  settle(grid);
  assert.ok(grid.children.every((c) => has(c, "in", "done") && !seen.observed.has(c)));
  const added = new Fake({ top: 300, left: 0 });
  grid.append(added);
  late.callback([{ target: grid, addedNodes: [added], removedNodes: [] }]);
  assert.ok(has(added, "done"), "a settled list has begun: a frame added in view is simply there");
});

test("motion held mid-session shows everything at once, and nothing is armed while it is held", () => {
  const rail = list(3);
  const head = new Fake();
  rise(rail);
  rise(head, { self: true });
  prefs.reduced = true;
  for (const fn of prefs.listeners) fn();
  assert.ok(rail.children.every((c) => has(c, "in", "done")) && has(head, "in", "done"));
  const later = list(2);
  rise(later);
  assert.ok(!has(later, "armed") && later.children.every((c) => !seen.observed.has(c)), "nothing is hidden while motion is held");
  const added = new Fake({ top: 2000, left: 0 });
  rail.append(added);
  late.callback([{ target: rail, addedNodes: [added], removedNodes: [] }]);
  assert.ok(has(added, "done"), "even a child far below the view");
  prefs.reduced = false;
});
