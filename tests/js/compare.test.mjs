import test from "node:test";
import assert from "node:assert/strict";

import { MODES, clampSplit, compareLayout, nextMode } from "../../openfield/web/js/lib/compare.js";
import { driftAction } from "../../openfield/web/js/lib/receiptdiff.js";

test("the Compare sheet's second take keeps step: in step, nudged, or sought", () => {
  for (const behind of [0, 0.01, -0.039, Number.NaN]) assert.equal(driftAction(behind), "none", String(behind));
  assert.equal(driftAction(0.04), "nudge-up", "behind by 0.04 s: runs 5% faster");
  assert.equal(driftAction(0.25), "nudge-up");
  assert.equal(driftAction(-0.1), "nudge-down", "ahead: runs 5% slower");
  assert.equal(driftAction(-0.25), "nudge-down");
  assert.equal(driftAction(0.26), "seek", "more than a quarter second: it seeks");
  assert.equal(driftAction(-3), "seek");
  assert.equal(driftAction(Number.POSITIVE_INFINITY), "seek");
});

test("compare modes cycle wipe -> side -> flip -> wipe", () => {
  assert.deepEqual(MODES, ["wipe", "side", "flip"]);
  assert.equal(nextMode("wipe"), "side");
  assert.equal(nextMode("side"), "flip");
  assert.equal(nextMode("flip"), "wipe");
  assert.equal(nextMode("unknown"), "wipe");
});

test("wipe clips the before player at the split and keeps the handle", () => {
  assert.deepEqual(compareLayout("wipe"), {
    beforeClip: "inset(0 50% 0 0)",
    beforeVisible: true,
    afterVisible: true,
    handle: true,
    sideBySide: false,
  });
  assert.equal(compareLayout("wipe", { split: 30 }).beforeClip, "inset(0 70% 0 0)");
});

test("the wipe split is clamped to 2..98", () => {
  assert.equal(clampSplit(0), 2);
  assert.equal(clampSplit(100), 98);
  assert.equal(clampSplit(-5), 2);
  assert.equal(clampSplit(undefined), 50);
  assert.equal(compareLayout("wipe", { split: 0 }).beforeClip, "inset(0 98% 0 0)");
  assert.equal(compareLayout("wipe", { split: 100 }).beforeClip, "inset(0 2% 0 0)");
});

test("side shows both players without a handle", () => {
  assert.deepEqual(compareLayout("side"), {
    beforeClip: "none",
    beforeVisible: true,
    afterVisible: true,
    handle: false,
    sideBySide: true,
  });
});

test("flip shows one player at a time", () => {
  assert.deepEqual(compareLayout("flip"), {
    beforeClip: "none",
    beforeVisible: false,
    afterVisible: true,
    handle: false,
    sideBySide: false,
  });
  assert.deepEqual(compareLayout("flip", { showing: "before" }), {
    beforeClip: "none",
    beforeVisible: true,
    afterVisible: false,
    handle: false,
    sideBySide: false,
  });
});
