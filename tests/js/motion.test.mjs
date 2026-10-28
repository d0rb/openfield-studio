import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";

import { holdStill, reducedMotion } from "../../openfield/web/js/lib/motion.js";

const native = { matchMedia: globalThis.matchMedia, navigator: globalThis.navigator };

/** The browser's globals, stubbed: a media query that may match, and a connection that may be saving its data. */
function stub({ reduced = false, saveData = false, connection = true } = {}) {
  globalThis.matchMedia = (query) => ({ media: query, matches: query.includes("prefers-reduced-motion") ? reduced : false });
  Object.defineProperty(globalThis, "navigator", { value: connection ? { connection: { saveData } } : {}, configurable: true, writable: true });
}

/** Put the browser's globals back as they were. */
function restore() {
  if (native.matchMedia === undefined) delete globalThis.matchMedia;
  else globalThis.matchMedia = native.matchMedia;
  Object.defineProperty(globalThis, "navigator", { value: native.navigator, configurable: true, writable: true });
}

test("without a browser, motion is allowed and nothing throws", () => {
  restore();
  assert.equal(reducedMotion(), false);
  assert.equal(holdStill(), false);
});

test("reduced motion is the person's preference, and only that", () => {
  stub({ reduced: true });
  try {
    assert.equal(reducedMotion(), true);
    assert.equal(holdStill(), true, "nothing plays on its own when motion is reduced");
  } finally {
    restore();
  }
});

test("Save-Data holds everything still, even when motion is allowed", () => {
  stub({ saveData: true });
  try {
    assert.equal(reducedMotion(), false);
    assert.equal(holdStill(), true);
  } finally {
    restore();
  }
});

test("a browser with no connection is not saving its data", () => {
  stub({ connection: false });
  try {
    assert.equal(reducedMotion(), false);
    assert.equal(holdStill(), false);
  } finally {
    restore();
  }
});

test("the browser is asked each time, so a changed preference is seen at once", () => {
  stub({ reduced: false });
  try {
    assert.equal(reducedMotion(), false);
    stub({ reduced: true });
    assert.equal(reducedMotion(), true);
  } finally {
    restore();
  }
});

test("the screens share one predicate: no room keeps its own copy", () => {
  // the Move Pad's hover plays through hoverplay.js now, so it gates nothing itself
  const rooms = ["lobby", "monitor", "takes", "wall", "filmstrip", "reveal", "shows", "screen", "hoverplay", "pathchip", "ambient", "shell"];
  for (const room of rooms) {
    const source = readFileSync(new URL(`../../openfield/web/js/ui/${room}.js`, import.meta.url), "utf8");
    assert.ok(source.includes("../lib/motion.js"), `${room}.js must use the shared motion helper`);
  }
  const ui = new URL("../../openfield/web/js/ui/", import.meta.url);
  for (const file of readdirSync(ui).filter((f) => f.endsWith(".js"))) {
    const source = readFileSync(new URL(file, ui), "utf8");
    assert.ok(!/matchMedia\?\.\("\(prefers-reduced-motion/.test(source), `${file} keeps its own copy of the predicate`);
  }
});

test("the Lobby gates its motion on holdStill, so Save-Data holds it as still as reduced motion does", () => {
  for (const room of ["lobby", "shows", "reveal", "screen"]) {
    const source = readFileSync(new URL(`../../openfield/web/js/ui/${room}.js`, import.meta.url), "utf8");
    assert.ok(!/reducedMotion\(/.test(source), `${room}.js asks only about reduced motion: a browser saving its data would still move`);
  }
});
