import test from "node:test";
import assert from "node:assert/strict";

import { copies, density, phone, pick, posterSet, savingData } from "../../openfield/web/js/lib/pictures.js";
import { posterAttrs, setPoster } from "../../openfield/web/js/lib/stages.js";
import { previewOf } from "../../openfield/web/js/ui/wall.js";

// the copies of one take, as previews.json lists them: the plain 384px loop, a 768px one (`mid`) and the take's own up to 1280px (`hd`)
const plain = { video: "showcase/previews/tk.mp4", poster: "showcase/previews/tk.jpg" };
const mid = (width) => ({ video: "showcase/previews/tk-mid.mp4", poster: "showcase/previews/tk-mid.jpg", ...(width ? { width } : {}) });
const hd = (width) => ({ video: "showcase/previews/tk-hd.mp4", poster: "showcase/previews/tk-hd.jpg", ...(width ? { width } : {}) });
const BEFORE_MID = { ...plain, hd: hd() }; // an index written before the 768px copy: {384, hd 1280}
const WITH_MID = { ...plain, mid: mid(768), hd: hd(1280) }; // {384, mid 768, hd 1280}
const PLAIN_ONLY = { ...plain }; // {384 only}

/** Run `fn` on a screen `width` CSS pixels wide with `dpr` device pixels to the CSS pixel (a wide one: 720px and up), saving data or not. */
function onScreen(width, dpr, fn, { saveData = false } = {}) {
  const had = { matchMedia: globalThis.matchMedia, devicePixelRatio: globalThis.devicePixelRatio };
  const navigator = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  globalThis.matchMedia = (query) => ({ matches: query === "(min-width: 720px)" && width >= 720 });
  globalThis.devicePixelRatio = dpr;
  if (saveData) Object.defineProperty(globalThis, "navigator", { value: { connection: { saveData: true } }, configurable: true, writable: true });
  try { return fn(); } finally {
    for (const [key, value] of Object.entries(had)) { if (value === undefined) delete globalThis[key]; else globalThis[key] = value; }
    if (navigator) Object.defineProperty(globalThis, "navigator", navigator); else delete globalThis.navigator;
  }
}
const wide = (dpr, fn) => onScreen(1440, dpr, fn);
const widthOf = (entry, frame) => pick(entry, frame).width;

test("the copies of a take come narrowest first, each with the width the builder recorded", () => {
  assert.deepEqual(copies(PLAIN_ONLY).map((c) => c.width), [384]);
  assert.deepEqual(copies(BEFORE_MID).map((c) => c.width), [384, 1280], "no recorded width: the nominal one");
  assert.deepEqual(copies(WITH_MID).map((c) => c.width), [384, 768, 1280]);
  // a take 896 px wide has an hd copy 896 px wide, and the index says so: the picks compare honest numbers
  assert.deepEqual(copies({ ...plain, mid: mid(768), hd: hd(896) }).map((c) => c.width), [384, 768, 896]);
  assert.deepEqual(copies({ ...plain, mid: mid(640), hd: hd(640) }).map((c) => c.width), [384, 640, 640], "a 640 px take: its mid copy is not claimed 768");
  assert.deepEqual(copies({ ...plain, mid: mid(768), hd: hd(600) }).map((c) => c.width), [384, 600, 768], "sorted by width, not by name");
  assert.deepEqual(copies(WITH_MID)[1], { width: 768, video: "showcase/previews/tk-mid.mp4", poster: "showcase/previews/tk-mid.jpg" });
  assert.equal(copies({ video: "a.mp4" })[0].poster, null, "a copy with no poster says so");
  assert.deepEqual(copies(null), []);
  assert.deepEqual(copies({ poster: "only.jpg" }), [], "no loop, no copies");
});

test("a frame gets the narrowest copy that fills its pixels on this screen: 296, 632, 262 and 530 px frames at 1x and 2x", () => {
  // [frame in CSS px, density, the width picked from {384, hd 1280}, from {384, mid 768, hd 1280}]
  const table = [
    [296, 1, 384, 384], [296, 2, 1280, 768],
    [632, 1, 1280, 768], [632, 2, 1280, 1280],
    [262, 1, 384, 384], [262, 2, 1280, 768],
    [530, 1, 1280, 768], [530, 2, 1280, 1280],
  ];
  for (const [frame, dpr, before, now] of table) {
    wide(dpr, () => {
      assert.equal(widthOf(BEFORE_MID, frame), before, `${frame}px at ${dpr}x, no mid copy`);
      assert.equal(widthOf(WITH_MID, frame), now, `${frame}px at ${dpr}x`);
      assert.equal(widthOf(PLAIN_ONLY, frame), 384, `${frame}px at ${dpr}x, only the plain loop`);
    });
  }
  wide(2, () => {
    const copy = pick(WITH_MID, 296);
    assert.deepEqual(copy, { width: 768, video: "showcase/previews/tk-mid.mp4", poster: "showcase/previews/tk-mid.jpg" }, "its loop and its poster, together");
  });
});

test("a copy exactly as wide as the frame's pixels fills it: the next one up is not fetched", () => {
  wide(1, () => {
    assert.equal(widthOf(WITH_MID, 384), 384);
    assert.equal(widthOf(WITH_MID, 385), 768);
    assert.equal(widthOf(WITH_MID, 768), 768);
    assert.equal(widthOf(WITH_MID, 769), 1280);
  });
  wide(2, () => {
    assert.equal(widthOf(WITH_MID, 192), 384);
    assert.equal(widthOf(WITH_MID, 384), 768);
    assert.equal(widthOf(WITH_MID, 640), 1280);
  });
  wide(1.5, () => assert.equal(widthOf(WITH_MID, 256), 384, "256px at 1.5x is 384 device pixels"));
});

test("a frame wider than every copy gets the widest, and a take 896 px wide is never asked for more", () => {
  const narrow = { ...plain, mid: mid(768), hd: hd(896) };
  wide(2, () => {
    assert.equal(widthOf(narrow, 632), 896, "1264 px asked, 896 px is all there is");
    assert.equal(widthOf(narrow, 5000), 896);
    assert.equal(widthOf(WITH_MID, 5000), 1280);
    assert.equal(widthOf(narrow, 380), 768, "760 px asked: the mid copy fills it");
  });
  wide(1, () => assert.equal(widthOf(narrow, 700), 768));
});

test("a 3x screen gains nothing from a third copy's bytes: density counts to 2", () => {
  assert.equal(wide(3, () => density()), 2);
  assert.equal(wide(0.75, () => density()), 1);
  assert.equal(wide(Number.NaN, () => density()), 1);
  assert.equal(wide(1.5, () => density()), 1.5);
  wide(3, () => {
    assert.equal(widthOf(WITH_MID, 632), 1280, "632 px at 3x asks 1264, not 1896");
    assert.equal(widthOf(WITH_MID, 296), 768);
  });
  assert.equal(density(), 1, "no device pixel ratio at all (Node): 1");
});

test("no width asked, no copies and no loop", () => {
  wide(2, () => {
    assert.equal(pick(WITH_MID).width, 384, "a tile that asks for nothing keeps the plain loop");
    assert.equal(pick(WITH_MID, 0).width, 384);
    assert.equal(pick(WITH_MID, Number.NaN).width, 384);
    assert.equal(pick(null, 300), null);
    assert.equal(pick({ poster: "x.jpg" }, 300), null);
  });
});

test("a phone keeps the 384px loop whatever the frame and the density", () => {
  for (const dpr of [1, 2, 3]) {
    onScreen(390, dpr, () => {
      assert.equal(phone(), true);
      for (const frame of [262, 296, 530, 632, 5000]) assert.equal(widthOf(WITH_MID, frame), 384, `${frame}px at ${dpr}x`);
      assert.equal(widthOf(BEFORE_MID, 632), 384);
    });
  }
  assert.equal(onScreen(719, 2, () => phone()), true, "719px is a phone");
  assert.equal(onScreen(720, 2, () => phone()), false, "720px is not");
  assert.equal(phone(), true, "no matchMedia at all (Node): not a screen that can show more");
});

test("a browser saving its data keeps the 384px loop on any screen", () => {
  onScreen(1440, 2, () => {
    assert.equal(savingData(), true);
    for (const frame of [262, 296, 530, 632]) assert.equal(widthOf(WITH_MID, frame), 384, `${frame}px`);
  }, { saveData: true });
  assert.equal(wide(2, () => savingData()), false);
  assert.equal(savingData(), false);
});

test("a poster set offers every copy on a wide screen, the small ones on a phone or a data saver", () => {
  const url = (path) => `/${path}`;
  const all = "/showcase/previews/tk.jpg 384w, /showcase/previews/tk-mid.jpg 768w, /showcase/previews/tk-hd.jpg 1280w";
  const small = "/showcase/previews/tk.jpg 384w, /showcase/previews/tk-mid.jpg 768w";
  const sizes = "(max-width: 719px) 46vw, 300px";
  wide(2, () => assert.deepEqual(posterSet(WITH_MID, sizes, url), { src: "/showcase/previews/tk.jpg", srcset: all, sizes }));
  onScreen(390, 3, () => assert.deepEqual(posterSet(WITH_MID, sizes, url), { src: "/showcase/previews/tk.jpg", srcset: small, sizes }));
  onScreen(1440, 2, () => assert.equal(posterSet(WITH_MID, sizes, url).srcset, small), { saveData: true });
  // an index from before the 768px copy: a phone is left with the plain poster alone
  onScreen(390, 3, () => assert.equal(posterSet(BEFORE_MID, "96px", url).srcset, "/showcase/previews/tk.jpg 384w"));
  wide(1, () => assert.equal(posterSet(BEFORE_MID, "96px", url).srcset, "/showcase/previews/tk.jpg 384w, /showcase/previews/tk-hd.jpg 1280w"));
  // the recorded widths are the descriptors: the hd poster of a take 896 px wide says 896
  wide(2, () => assert.equal(posterSet({ ...plain, hd: hd(896) }, "300px", url).srcset, "/showcase/previews/tk.jpg 384w, /showcase/previews/tk-hd.jpg 896w"));
  assert.equal(posterSet(WITH_MID, "300px").src, "showcase/previews/tk.jpg", "an address is used as it is when no url function is given");
});

test("a poster set has nothing to offer a take with no poster or no previews", () => {
  assert.equal(posterSet(null, "96px"), null);
  assert.equal(posterSet({ video: "a.mp4" }, "96px"), null);
  assert.equal(posterSet({ video: "a.mp4", poster: "a.jpg", mid: { video: "b.mp4" } }, "96px").srcset, "a.jpg 384w", "a copy with no poster is not offered");
});

// the loop a frame plays: previewOf asks lib/pictures.js with the frame's width
const state = { previews: { takes: { tk_a: { ...WITH_MID, video: "showcase/previews/tk_a.mp4", poster: "showcase/previews/tk_a.jpg",
  mid: { video: "showcase/previews/tk_a-mid.mp4", poster: "showcase/previews/tk_a-mid.jpg", width: 768 },
  hd: { video: "showcase/previews/tk_a-hd.mp4", poster: "showcase/previews/tk_a-hd.jpg", width: 1280 } } } } };
const api = { asset: (path) => `/${path}` };
const loopFor = (screen, dpr, options) => onScreen(screen, dpr, () => previewOf(state, { id: "tk_a" }, api, options)).video.replace("/showcase/previews/tk_a", "").replace(".mp4", "") || "plain";

test("a loop is chosen by the width of its frame: previewOf passes it on", () => {
  assert.equal(loopFor(1440, 1, { width: 296 }), "plain");
  assert.equal(loopFor(1440, 2, { width: 296 }), "-mid");
  assert.equal(loopFor(1440, 1, { width: 632 }), "-mid");
  assert.equal(loopFor(1440, 2, { width: 632 }), "-hd");
  assert.equal(loopFor(1440, 2, { width: 560 }), "-hd", "the Chat room's card: 560px at 2x asks for 1120");
  assert.equal(loopFor(1440, 1, { width: 560 }), "-mid");
  assert.equal(loopFor(1440, 2, { hd: true }), "-hd", "a large frame without a measured width counts as 640px");
  assert.equal(loopFor(1440, 2, {}), "plain", "a tile that passes neither keeps the plain loop");
  assert.equal(loopFor(390, 3, { width: 632 }), "plain", "a phone keeps the small loop");
  const poster = onScreen(1440, 2, () => previewOf(state, { id: "tk_a" }, api, { width: 296 })).poster;
  assert.equal(poster, "/showcase/previews/tk_a-mid.jpg", "the poster comes from the same copy as the loop");
});

// -- a take's poster <img>: posterAttrs says what it needs, setPoster puts it on an image that may be reused ----------------------------------------------

const take = { id: "tk_a", outputs: [{ role: "poster", file: "poster.png" }], media_base: "showcase/takes/tk_a" };
const hosted = { asset: (path) => `/${path}`, media: (t, file) => `/${t.media_base}/${file}` };
const WITH = { previews: { takes: { tk_a: { video: "showcase/previews/tk_a.mp4", poster: "showcase/previews/tk_a.jpg",
  mid: { video: "x", poster: "showcase/previews/tk_a-mid.jpg", width: 768 }, hd: { video: "x", poster: "showcase/previews/tk_a-hd.jpg", width: 1280 } } } } };

test("a poster asks for the copies of its take and says how wide it is drawn", () => {
  wide(2, () => assert.deepEqual(posterAttrs(WITH, take, hosted, "96px"), {
    src: "/showcase/previews/tk_a.jpg", decoding: "async", sizes: "96px",
    srcset: "/showcase/previews/tk_a.jpg 384w, /showcase/previews/tk_a-mid.jpg 768w, /showcase/previews/tk_a-hd.jpg 1280w" }));
  onScreen(390, 3, () => assert.equal(posterAttrs(WITH, take, hosted, "46vw").srcset, "/showcase/previews/tk_a.jpg 384w, /showcase/previews/tk_a-mid.jpg 768w", "a phone: the small copies"));
  assert.equal(posterAttrs(WITH, { ...take, id: "tk_r", replay_of: "tk_a" }, hosted, "96px").src, "/showcase/previews/tk_a.jpg", "a replay shows its recording's");
});

test("a take with no previews gets its own poster, and one with no poster gets nothing", () => {
  assert.deepEqual(posterAttrs({}, take, hosted, "96px"), { src: "/showcase/takes/tk_a/poster.png", decoding: "async" });
  assert.deepEqual(posterAttrs({ previews: { takes: {} } }, take, hosted, "96px"), { src: "/showcase/takes/tk_a/poster.png", decoding: "async" });
  assert.equal(posterAttrs({}, { id: "tk_b", outputs: [] }, hosted, "96px"), null);
  assert.equal(posterAttrs(WITH, null, hosted, "96px"), null);
});

/** An <img> as far as setPoster needs one, noting every write. */
function image() {
  const attributes = new Map();
  const writes = [];
  return {
    hidden: false, writes,
    getAttribute: (name) => attributes.get(name) ?? null,
    setAttribute: (name, value) => { attributes.set(name, String(value)); writes.push(name); },
    removeAttribute: (name) => { attributes.delete(name); writes.push(`-${name}`); },
  };
}

test("an image gets its poster once, src last, and is left alone while the picture is the same", () => {
  const img = image();
  const attrs = wide(2, () => posterAttrs(WITH, take, hosted, "96px"));
  setPoster(img, attrs);
  assert.equal(img.hidden, false);
  assert.equal(img.getAttribute("srcset"), attrs.srcset);
  assert.equal(img.getAttribute("sizes"), "96px");
  assert.equal(img.getAttribute("decoding"), "async");
  assert.equal(img.writes.at(-1), "src", "the browser picks once, with srcset and sizes in place");
  const writes = img.writes.length;
  setPoster(img, attrs);
  assert.equal(img.writes.length, writes, "the same picture is not set again");
});

test("an image reused for another take loses the srcset of the one before, and hides when there is no picture", () => {
  const img = image();
  setPoster(img, wide(2, () => posterAttrs(WITH, take, hosted, "96px")));
  const lean = posterAttrs({}, { ...take, id: "tk_c", media_base: "showcase/takes/tk_c" }, hosted, "96px"); // no previews: the poster alone
  setPoster(img, lean);
  assert.equal(img.getAttribute("srcset"), null, "a stale srcset would win over the new src");
  assert.equal(img.getAttribute("sizes"), null);
  assert.equal(img.getAttribute("src"), "/showcase/takes/tk_c/poster.png");
  setPoster(img, null);
  assert.equal(img.hidden, true);
  assert.equal(img.getAttribute("src"), "/showcase/takes/tk_c/poster.png", "hidden, not emptied");
  setPoster(img, lean);
  assert.equal(img.hidden, false);
  // the same src with a new srcset (a window crossing the phone line) is a new picture
  const a = { src: "/a.jpg", srcset: "/a.jpg 384w", sizes: "96px", decoding: "async" };
  setPoster(img, a);
  setPoster(img, { ...a, srcset: "/a.jpg 384w, /a-mid.jpg 768w" });
  assert.equal(img.getAttribute("srcset"), "/a.jpg 384w, /a-mid.jpg 768w");
});
