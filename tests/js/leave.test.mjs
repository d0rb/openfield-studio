import test, { mock } from "node:test";
import assert from "node:assert/strict";

import { leave } from "../../openfield/web/js/ui/dom.js";

const native = { matchMedia: globalThis.matchMedia, navigator: globalThis.navigator };

/** The browser's globals, stubbed as tests/js/motion.test.mjs does: a media query that may match, a connection that may be saving data. */
function stub({ reduced = false, saveData = false } = {}) {
  globalThis.matchMedia = (query) => ({ media: query, matches: query.includes("prefers-reduced-motion") ? reduced : false });
  Object.defineProperty(globalThis, "navigator", { value: { connection: { saveData } }, configurable: true, writable: true });
}

/** Put the browser's globals back as they were, and the real timers with them. */
function restore() {
  mock.timers.reset();
  if (native.matchMedia === undefined) delete globalThis.matchMedia;
  else globalThis.matchMedia = native.matchMedia;
  Object.defineProperty(globalThis, "navigator", { value: native.navigator, configurable: true, writable: true });
}

/** Run `check` with the page's motion preference stubbed and `setTimeout` on a clock the test turns by hand. */
async function withMotion(options, check) {
  stub(options);
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    await check();
  } finally {
    restore();
  }
}

/** Just what leave() touches of an element: its classes, whether it is in the page, and its transitionend listeners. */
function fakeElement({ connected = true } = {}) {
  const classes = new Set();
  const listeners = new Set();
  return {
    isConnected: connected,
    classList: { add: (name) => classes.add(name), contains: (name) => classes.has(name) },
    addEventListener: (type, fn) => { if (type === "transitionend") listeners.add(fn); },
    removeEventListener: (type, fn) => { if (type === "transitionend") listeners.delete(fn); },
    listening: () => listeners.size,
    /** The browser reporting a finished transition: on the element itself, or on `target` (a child's, bubbling up). */
    transitionEnd(target = this) { for (const fn of [...listeners]) fn({ type: "transitionend", target }); },
  };
}

/** Whether `promise` has resolved by now (the microtasks run first; setImmediate is not on the test's clock). */
async function resolvedNow(promise) {
  let done = false;
  promise.then(() => { done = true; });
  await new Promise((resolve) => setImmediate(resolve));
  return done;
}

test("an element that is not there resolves at once", async () => {
  await withMotion({}, async () => {
    assert.equal(await resolvedNow(leave(null)), true);
    assert.equal(await resolvedNow(leave(undefined)), true);
  });
});

test("under reduced motion it adds .leaving and resolves without waiting for anything", async () => {
  await withMotion({ reduced: true }, async () => {
    const el = fakeElement();
    const done = leave(el);
    assert.ok(el.classList.contains("leaving"), "the class is still added, so the caller's code path is the same");
    assert.equal(el.listening(), 0, "no transition is waited for");
    assert.equal(await resolvedNow(done), true, "resolved before any timer could run");
  });
});

test("Save-Data holds it still the same way", async () => {
  await withMotion({ saveData: true }, async () => {
    const el = fakeElement();
    const done = leave(el);
    assert.ok(el.classList.contains("leaving"));
    assert.equal(el.listening(), 0);
    assert.equal(await resolvedNow(done), true);
  });
});

test("an element already out of the page resolves at once, and still gets .leaving", async () => {
  await withMotion({}, async () => {
    const el = fakeElement({ connected: false });
    const done = leave(el);
    assert.ok(el.classList.contains("leaving"));
    assert.equal(el.listening(), 0);
    assert.equal(await resolvedNow(done), true);
  });
});

test("with motion allowed it adds .leaving, ignores a child's transitionend and resolves on the element's own", async () => {
  await withMotion({}, async () => {
    const el = fakeElement();
    const done = leave(el);
    assert.ok(el.classList.contains("leaving"));
    assert.equal(el.listening(), 1, "it waits for the element's transition");
    assert.equal(await resolvedNow(done), false, "nothing has ended yet");
    el.transitionEnd({}); // the sheet inside a scrim finishing its own fade
    assert.equal(await resolvedNow(done), false, "a child's transitionend is not the element's");
    assert.equal(el.listening(), 1, "and it keeps waiting");
    el.transitionEnd();
    assert.equal(await resolvedNow(done), true, "the element's own ends it");
    assert.equal(el.listening(), 0, "it lets go of the listener");
    el.transitionEnd();
    mock.timers.tick(500); // the timeout that was set along the way fires into nothing
  });
});

test("when no transitionend comes it resolves at the floor: ms plus 40", async () => {
  await withMotion({}, async () => {
    const el = fakeElement();
    const done = leave(el, { ms: 100 });
    mock.timers.tick(139);
    assert.equal(await resolvedNow(done), false, "not before the floor");
    mock.timers.tick(1);
    assert.equal(await resolvedNow(done), true, "at 140 ms");
    assert.equal(el.listening(), 0);
  });
});

test("the floor is 160 ms by default, the length of --t-fast plus the margin", async () => {
  await withMotion({}, async () => {
    const el = fakeElement();
    const done = leave(el);
    mock.timers.tick(159);
    assert.equal(await resolvedNow(done), false);
    mock.timers.tick(1);
    assert.equal(await resolvedNow(done), true);
  });
});
