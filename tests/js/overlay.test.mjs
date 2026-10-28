import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { drawStage, overlayLayout, overlayName, recordingType, recordingTypes, travelled } from "../../openfield/web/js/lib/overlay.js";

const catalog = JSON.parse(readFileSync(new URL("./fixtures/catalog.json", import.meta.url), "utf8"));
const move = (id) => catalog.moves.find((m) => m.id === id);

test("the travelled part of a path ends on the exact point reached", () => {
  const line = [{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 10 }];
  assert.deepEqual(travelled(line, 0), [{ x: 0, y: 0 }]);
  assert.deepEqual(travelled(line, 0.25), [{ x: 0, y: 0 }, { x: 5, y: 0 }]);
  assert.deepEqual(travelled(line, 0.75), [{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 5 }]);
  assert.deepEqual(travelled(line, 1), line);
  assert.deepEqual(travelled(line, Number.NaN), [{ x: 0, y: 0 }]);
});

test("a saved frame keeps the stage at the lower left, larger on a portrait frame", () => {
  const wide = overlayLayout(1280, 704);
  assert.equal(wide.stage.x, wide.margin);
  assert.equal(wide.stage.y + wide.stage.h, 704 - wide.margin);
  assert.ok(Math.abs(wide.stage.w / wide.stage.h - 100 / 62) < 0.02, "the stage keeps its plan's shape");
  const tall = overlayLayout(704, 1280);
  assert.ok(tall.stage.w / 704 > wide.stage.w / 1280, "a portrait frame gives the stage more of its width");
  assert.equal(tall.title.size, wide.title.size, "type follows the short side");
});

test("the recording format: MP4 with AAC first, then MP4 with Opus, then WebM", () => {
  const all = recordingTypes(() => true);
  assert.match(all[0], /^video\/mp4;codecs=avc1,mp4a/);
  assert.ok(all.indexOf("video/mp4;codecs=avc1,opus") < all.indexOf("video/webm"));
  assert.equal(recordingType((t) => t.startsWith("video/webm")), "video/webm;codecs=vp9,opus");
  assert.equal(recordingType(() => false), null);
  assert.equal(recordingType(() => { throw new Error("old browser"); }), null);
  assert.equal(overlayName("bullet_time", "tk_1", "video/mp4;codecs=avc1,opus"), "bullet-time-tk_1.mp4");
  assert.equal(overlayName("dolly_in", "tk_2", "video/webm"), "dolly-in-tk_2.webm");
});

/** A canvas context that only counts what it is asked to draw. */
function fakeCanvas() {
  const calls = { arc: 0, fillText: [], stroke: 0, fill: 0, lineTo: 0 };
  const ctx = new Proxy({}, {
    get(target, name) {
      if (name === "calls") return calls;
      if (name in target) return target[name];
      return (...args) => {
        if (name === "arc") calls.arc++;
        if (name === "fillText") calls.fillText.push(args[0]);
        if (name === "stroke") calls.stroke++;
        if (name === "fill") calls.fill++;
        if (name === "lineTo") calls.lineTo++;
      };
    },
    set(target, name, value) { target[name] = value; return true; },
  });
  return ctx;
}
const colors = { screen: "#000", grid: "#111", lineStrong: "#222", text2: "#aaa", text3: "#888", ground: "#050505", accent: "#f70", accentSoft: "rgba(255,120,0,.2)", accentFill: "#f70", accentText: "#fa5", onAccent: "#000" };

test("the stage draws one mark for a one-still shot and one per still for a keyframed move", () => {
  const box = { x: 10, y: 400, w: 384, h: 238 };
  const hollow = fakeCanvas();
  drawStage(hollow, { poses: move("bullet_time").path, anchors: 1, t: 0.5, hollow: true, box, colors });
  assert.deepEqual(hollow.calls.fillText, ["1"]);
  const keyed = fakeCanvas();
  drawStage(keyed, { poses: move("dolly_in").path, anchors: move("dolly_in").anchors, t: 1, box, colors });
  assert.deepEqual(keyed.calls.fillText, ["1", "2"]);
  assert.ok(keyed.calls.lineTo > 20, "the floor, the path and the camera's frame are drawn");
});

test("recording falls back past a format the encoder cannot do, and stops at once for anything else", async () => {
  const { firstThatRecords } = await import("../../openfield/web/js/lib/overlay.js");
  const types = ["mp4-aac", "mp4-opus", "webm"];
  const failed = new Set();
  const retried = [];
  const warned = [];
  const warn = (...parts) => warned.push(parts.join(" "));
  const answers = { "mp4-aac": { broke: "encoder configuration is not supported", format: true }, "mp4-opus": { blob: "FILE" } };
  const got = await firstThatRecords(types, async (t) => answers[t], { failed, onRetry: (t) => retried.push(t), warn });
  assert.deepEqual(got, { blob: "FILE", type: "mp4-opus" });
  assert.deepEqual([...failed], ["mp4-aac"]);
  assert.deepEqual(retried, ["mp4-aac"]);
  assert.deepEqual(warned, ["Recording as mp4-aac failed: encoder configuration is not supported"], "the console names the format tried");
  // the next save skips the format that failed
  const asked = [];
  await firstThatRecords(types, async (t) => { asked.push(t); return { blob: "FILE" }; }, { failed, warn });
  assert.deepEqual(asked, ["mp4-opus"]);
  // a blocked play is not the format's fault: it stops at once and marks nothing
  const strict = new Set();
  await assert.rejects(firstThatRecords(types, async () => ({ broke: "Press the button again.", format: false }), { failed: strict, warn }), /Press the button again/);
  assert.equal(strict.size, 0);
  // every format failing: the person reads one plain line, the console keeps the encoder's own words
  warned.length = 0;
  await assert.rejects(firstThatRecords(types, async () => ({ broke: "no encoder", format: true }), { failed: new Set(), warn }),
    { message: "This browser could not record the video." });
  assert.deepEqual(warned, types.map((t) => `Recording as ${t} failed: no encoder`));
  await assert.rejects(firstThatRecords([], async () => ({ blob: "x" })), /could not record the video/, "no format left to try");
});

test("a recorder pass that throws comes back as a plain failure, and marks no format", async () => {
  const { firstThatRecords } = await import("../../openfield/web/js/lib/overlay.js");
  const failed = new Set();
  const warned = [];
  const warn = (...parts) => warned.push(parts);
  const asked = [];
  const broken = async (t) => { asked.push(t); throw new TypeError("Cannot read properties of undefined (reading 'getTracks')"); };
  await assert.rejects(firstThatRecords(["mp4", "webm"], broken, { failed, warn }), { message: "This browser could not record the video." });
  assert.deepEqual(asked, ["mp4"], "it stops at once: the next format would only break the same way");
  assert.equal(failed.size, 0);
  assert.equal(warned[0][0], "Recording as mp4 failed:");
  assert.ok(warned[0][1] instanceof TypeError, "the console gets the browser's own error");
  // a pass that throws before it returns a promise is caught the same way
  await assert.rejects(firstThatRecords(["webm"], () => { throw new Error("sync"); }, { warn }), { message: "This browser could not record the video." });
});

test("a take's plan comes from its receipt, then from the catalog", async () => {
  const { planOf } = await import("../../openfield/web/js/lib/overlay.js");
  const keyframed = { mode: "keyframed", anchors: 2 };
  assert.deepEqual(planOf(keyframed, { inputs: { mode: "keyframed", anchors: [{}, {}, {}] } }), { hollow: false, anchors: 3 });
  assert.deepEqual(planOf(keyframed, { inputs: { mode: "prompt_only", anchors: [{}] } }), { hollow: true, anchors: 1 }, "a quick take of a keyframed move");
  assert.deepEqual(planOf(keyframed, null, { prompt_only: true }).hollow, true);
  assert.deepEqual(planOf(keyframed, null, {}), { hollow: false, anchors: 2 });
  assert.deepEqual(planOf({ mode: "prompt_only" }, null, {}).hollow, true);
});
