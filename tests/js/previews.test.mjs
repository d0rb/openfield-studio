import test from "node:test";
import assert from "node:assert/strict";

import { previewOf } from "../../openfield/web/js/ui/wall.js";

// a take with both copies (a built copy gives every take the two) and one that has only the plain loop
const state = { previews: { takes: {
  tk_a: { video: "showcase/previews/tk_a.mp4", poster: "showcase/previews/tk_a.jpg",
    hd: { video: "showcase/previews/tk_a-hd.mp4", poster: "showcase/previews/tk_a-hd.jpg" } },
  tk_old: { video: "showcase/previews/tk_old.mp4", poster: "showcase/previews/tk_old.jpg" },
} } };
const api = { asset: (path) => `/${path}` };
const PLAIN = { video: "/showcase/previews/tk_a.mp4", poster: "/showcase/previews/tk_a.jpg" };
const SHARP = { video: "/showcase/previews/tk_a-hd.mp4", poster: "/showcase/previews/tk_a-hd.jpg" };

/** Run `fn` on a screen `width` CSS pixels wide with `density` device pixels to the CSS pixel, and give back what it returns. */
function onScreen(width, density, fn) {
  const had = { matchMedia: globalThis.matchMedia, devicePixelRatio: globalThis.devicePixelRatio };
  globalThis.matchMedia = (query) => ({ matches: query === "(min-width: 720px)" && width >= 720 });
  globalThis.devicePixelRatio = density;
  try { return fn(); } finally {
    for (const [key, value] of Object.entries(had)) { if (value === undefined) delete globalThis[key]; else globalThis[key] = value; }
  }
}
/** The loop a card that shows large would play on that screen. */
const large = (width, density, id = "tk_a") => onScreen(width, density, () => previewOf(state, { id }, api, { hd: true }));

test("a loop that shows large plays the sharper copy on a wide screen, its poster too", () => {
  assert.deepEqual(large(1440, 1), SHARP);
  assert.deepEqual(large(720, 1), SHARP, "720px and up");
});

test("a phone keeps the small loop whatever its pixel density: its cards are small and its budget the tightest", () => {
  assert.deepEqual(large(390, 1), PLAIN);
  assert.deepEqual(large(390, 1.25), PLAIN);
  assert.deepEqual(large(390, 3), PLAIN);
});

test("the Takes wall never asks for the sharper copy, whatever the screen", () => {
  assert.deepEqual(onScreen(2560, 2, () => previewOf(state, { id: "tk_a" }, api)), PLAIN);
});

test("a take with no sharper copy plays its plain loop, one with no loop has none, a replay plays its recording's", () => {
  assert.equal(large(1440, 2, "tk_old").video, "/showcase/previews/tk_old.mp4");
  assert.equal(large(1440, 2, "tk_none"), null);
  assert.deepEqual(onScreen(1440, 2, () => previewOf(state, { id: "tk_r", replay_of: "tk_a" }, api, { hd: true })), SHARP);
});
