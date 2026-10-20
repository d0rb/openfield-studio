import test from "node:test";
import assert from "node:assert/strict";

import { createStore } from "../../openfield/web/js/lib/store.js";
import { anchorsAlong, bounds, heading, sideView, topView } from "../../openfield/web/js/lib/pathview.js";
import { ago, diffParams, sameRecipe, shortId, timecode } from "../../openfield/web/js/lib/format.js";
import { followTake } from "../../openfield/web/js/lib/sse.js";

test("store notifies only on real changes and supports function patches", () => {
  const store = createStore({ a: 1, b: 2 });
  const seen = [];
  const off = store.subscribe((state, changed) => seen.push([state.a, changed]));
  store.set({ a: 1 });
  assert.equal(seen.length, 0);
  store.set({ a: 5 });
  store.set((s) => ({ a: s.a + 1 }));
  assert.deepEqual(seen, [[5, ["a"]], [6, ["a"]]]);
  off();
  store.set({ a: 9 });
  assert.equal(seen.length, 2);
  assert.equal(store.get().b, 2);
});

test("a dolly-in path runs up the top view toward the subject", () => {
  const poses = [{ x: 0, y: 0, z: -1, yaw: 0 }, { x: 0, y: 0, z: -0.45, yaw: 0 }];
  const view = topView(poses);
  assert.ok(view.points[0].y > view.points[1].y, "camera moves up the page toward the subject");
  assert.ok(Math.abs(view.points[0].x - view.points[1].x) < 1e-9);
  assert.deepEqual([view.origin.x, view.origin.y], [50, 50]);
  assert.match(view.d, /^M[\d.]+ [\d.]+ L[\d.]+ [\d.]+$/);
});

test("the side view shows height up and distance across", () => {
  const view = sideView([{ z: -1, y: 0 }, { z: -1.2, y: 0.8 }]);
  assert.ok(view.points[1].y < view.points[0].y, "rising camera ends higher on screen");
  assert.ok(view.points[1].x < view.points[0].x, "pulling back moves left");
});

test("bounds keep a minimum scale and cover the whole path", () => {
  assert.deepEqual(bounds([{ x: 0.1, z: -1 }], "x", "z"), { min: -1.3, max: 1.3 });
  assert.equal(bounds([{ x: 3, z: 0 }], "x", "z").max, 3);
});

test("anchors are spread evenly along a path", () => {
  const poses = Array.from({ length: 9 }, (_, i) => ({ x: i, z: 0 }));
  const view = topView(poses);
  const three = anchorsAlong(view, 3);
  assert.deepEqual(three, [view.points[0], view.points[4], view.points[8]]);
  assert.deepEqual(anchorsAlong(view, 1), [view.points[0]]);
  assert.deepEqual(anchorsAlong(view, 0), []);
});

test("heading follows yaw", () => {
  assert.deepEqual(heading({ yaw: 0 }), { x: 0, y: -1 });
  const right = heading({ yaw: 90 });
  assert.ok(Math.abs(right.x - 1) < 1e-9 && Math.abs(right.y) < 1e-9);
});

test("timecode, ago and shortId", () => {
  assert.equal(timecode(3.5, 24), "00:00:03:12");
  assert.equal(timecode(3725.0), "01:02:05:00");
  assert.equal(timecode(-4), "00:00:00:00");
  const now = Date.parse("2026-10-16T12:00:00Z");
  assert.equal(ago("2026-10-16T11:59:50Z", now), "just now");
  assert.equal(ago("2026-10-16T11:57:00Z", now), "3 min ago");
  assert.equal(ago("2026-10-16T09:00:00Z", now), "3 h ago");
  assert.equal(ago("2026-10-10T12:00:00Z", now), "6 d ago");
  assert.equal(shortId("tk_20261016_153012_ab12"), "ab12");
});

test("recipes compare regardless of key order and diff to readable rows", () => {
  assert.ok(sameRecipe({ a: 1, b: { c: [1, 2] } }, { b: { c: [1, 2] }, a: 1 }));
  assert.ok(!sameRecipe({ a: 1 }, { a: 1, b: 2 }));
  assert.ok(!sameRecipe([1], { 0: 1 }));
  const rows = diffParams({ rig: { lens: "clean_sharp", focal: 35 }, seed: 1 }, { rig: { lens: "anamorphic", focal: 35 }, seed: 2 });
  assert.deepEqual(rows, [
    { path: "rig.lens", from: "clean_sharp", to: "anamorphic" },
    { path: "seed", from: 1, to: 2 },
  ]);
});

class FakeEventSource {
  static last = null;
  constructor(url) {
    this.url = url;
    this.closed = false;
    FakeEventSource.last = this;
  }
  close() {
    this.closed = true;
  }
  emit(event) {
    this.onmessage({ data: JSON.stringify(event) });
  }
}

test("followTake forwards events, ends once on `end`, and closes the stream", () => {
  const events = [];
  const ends = [];
  const api = { eventsUrl: (id) => `/e/${id}`, take: async () => ({ status: "running" }) };
  followTake(api, "tk_1", { onEvent: (e) => events.push(e.type), onEnd: (s) => ends.push(s), EventSourceImpl: FakeEventSource });
  const source = FakeEventSource.last;
  assert.equal(source.url, "/e/tk_1");
  source.emit({ type: "stage" });
  source.onmessage({ data: "not json" });
  source.emit({ type: "end", status: "succeeded" });
  source.emit({ type: "end", status: "succeeded" });
  assert.deepEqual(events, ["stage", "end", "end"]);
  assert.deepEqual(ends, ["succeeded"]);
  assert.ok(source.closed);
});

test("followTake polls when EventSource is unavailable and stops at a terminal status", async () => {
  const states = ["running", "running", "succeeded"];
  const api = { eventsUrl: () => "", take: async () => ({ status: states.shift() }) };
  const ends = [];
  await new Promise((resolve) => {
    followTake(api, "tk_2", { onEnd: (s) => { ends.push(s); resolve(); }, pollMs: 5, EventSourceImpl: null });
  });
  assert.deepEqual(ends, ["succeeded"]);
});
