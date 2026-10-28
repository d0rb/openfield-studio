import test from "node:test";
import assert from "node:assert/strict";

import { createStore } from "../../openfield/web/js/lib/store.js";
import { anchorsAlong, bounds, frustum, heading, litCount, pointAt, poseAt, sideView, stagePoint, topView } from "../../openfield/web/js/lib/pathview.js";
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

test("the camera's pose and point a fraction of the way through follow the samples evenly", () => {
  const poses = [0, 1, 2].map((x) => ({ x, y: 0, z: -1, yaw: 0, pitch: 0, fov: 40 - 10 * x }));
  assert.deepEqual(poseAt(poses, 0), poses[0]);
  assert.deepEqual(poseAt(poses, 1), poses[2]);
  assert.equal(poseAt(poses, 0.25).x, 0.5);
  assert.equal(poseAt(poses, 0.75).fov, 25);
  assert.equal(poseAt(poses, 7).x, 2, "t is clamped");
  assert.equal(poseAt(poses, Number.NaN).x, 0);
  assert.deepEqual(poseAt([poses[1]], 0.5), poses[1]);
  assert.equal(poseAt([], 0.5), null);
  const view = topView(Array.from({ length: 9 }, (_, i) => ({ x: i, z: 0 })));
  assert.deepEqual(pointAt(view, 0.5), { x: view.points[4].x, y: view.points[4].y });
  const between = pointAt(view, 0.5 / 8);
  assert.ok(Math.abs(between.x - (view.points[0].x + view.points[1].x) / 2) < 1e-9);
});

test("a still is lit once the shot reaches it, the first at once", () => {
  assert.deepEqual([0, 0.49, 0.5, 0.99, 1].map((t) => litCount(3, t)), [1, 1, 2, 2, 3]);
  assert.deepEqual([litCount(2, 0), litCount(2, 1), litCount(1, 0.5), litCount(0, 0.5)], [1, 2, 1, 0]);
});

test("the stage view looks from above and to one side", () => {
  const origin = stagePoint({ x: 0, y: 0, z: 0 });
  assert.ok(Math.abs(origin.x) < 1e-12 && Math.abs(origin.y) < 1e-12);
  assert.ok(stagePoint({ x: 0, y: 1, z: 0 }).y < 0, "height goes up the screen");
  assert.ok(stagePoint({ x: 0, y: 0, z: -1 }).y > 0, "the camera's start lands in front of the subject, lower down");
  assert.ok(stagePoint({ x: 1, y: 0, z: 0 }).x > 0, "the camera's right is to the right");
});

test("the camera's frame points the way it looks and narrows when it zooms", () => {
  const near = (a, b) => Math.abs(a - b) < 1e-9;
  const side = frustum({ x: 1, y: 0, z: 0, yaw: -90, pitch: 0, fov: 40 }); // an orbit pose a quarter of the way round
  assert.ok(near(side.forward.x, -1) && near(side.forward.y, 0) && near(side.forward.z, 0), "it looks at the subject");
  const down = frustum({ x: 0, y: 1, z: 0, yaw: 0, pitch: -90, fov: 40 });
  assert.ok(near(down.forward.y, -1), "pitch -90 looks at the floor");
  const span = (a, b) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
  const wide = frustum({ x: 0, y: 0, z: -1, yaw: 0, pitch: 0, fov: 40 });
  assert.ok(near(span(wide.corners[0], wide.corners[1]) / span(wide.corners[1], wide.corners[2]), 16 / 9), "the frame is 16:9");
  const tight = frustum({ x: 0, y: 0, z: -1, yaw: 0, pitch: 0, fov: 20 });
  assert.ok(span(tight.corners[0], tight.corners[1]) < span(wide.corners[0], wide.corners[1]) * 0.55, "zooming in narrows it");
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

test("tape marks that land on one spot are fanned out so every number reads", async () => {
  const { spreadStacked } = await import("../../openfield/web/js/lib/pathview.js");
  const a = { x: 50, y: 50 }, b = { x: 50.2, y: 49.9 }, c = { x: 70, y: 50 };
  const out = spreadStacked([a, b, c], 12);
  assert.deepEqual(out.map((p) => Math.round(p.x)), [44, 56, 70], "two stacked marks sit 12 units apart, the lone one stays");
  assert.deepEqual(out.map((p) => p.y), [50, 49.9, 50]);
  assert.deepEqual(spreadStacked([c], 12), [c], "a single mark is untouched");
  assert.deepEqual(spreadStacked([], 12), []);
});

test("the stage fit holds with no path at all", async () => {
  const { stageFit } = await import("../../openfield/web/js/lib/pathview.js");
  const fit = stageFit([]);
  const p = fit.to({ x: 0, y: 0, z: 0 });
  assert.ok(Number.isFinite(p.x) && Number.isFinite(p.y));
});

// -- an angle pivots the planned camera -------------------------------------------------------------------------------------

import { withAngle } from "../../openfield/web/js/lib/pathview.js";

test("an angle pivots the planned camera around the subject, lifts it and pushes it back", () => {
  const poses = [{ x: 0, y: 0, z: -1, yaw: 0, pitch: 0, fov: 40 }, { x: 0, y: 0, z: -0.45, yaw: 0, pitch: 0, fov: 40 }];
  const near = (a, b) => Math.abs(a - b) < 1e-9;
  assert.deepEqual(withAngle(poses, { azimuth: 0, elevation: 0, distance: 1 }), poses, "the default is the identity");
  const back = withAngle(poses, { azimuth: 180 })[0];
  assert.ok(near(back.z, 1) && near(back.x, 0) && back.yaw === -180, "turned to the back, still looking at the subject");
  const right = withAngle(poses, { azimuth: 90 })[0];
  assert.ok(near(right.x, 1) && near(right.z, 0) && right.yaw === -90, "a quarter turn to the camera's right, as the rig's orbit turns");
  const low = withAngle(poses, { elevation: -30 })[0];
  assert.ok(low.y < 0 && low.pitch > 0 && near(Math.hypot(low.x, low.y, low.z), 1), "a low angle: below eye level, looking up, same distance");
  const wide = withAngle(poses, { distance: 1.8 });
  assert.ok(near(wide[0].z, -1.8) && near(wide[1].z, -0.81), "the whole path is pushed back with the start");
  assert.deepEqual(withAngle([], { azimuth: 45 }), []);
});
