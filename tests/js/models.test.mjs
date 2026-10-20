import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { describeMove, locate, organise, step } from "../../openfield/web/js/lib/movepad.js";
import {
  defaultRig, fromRecipe, initialDirect, planSummary, renderEstimate, requestBody, validate,
} from "../../openfield/web/js/lib/direct.js";
import { formFor, children, ledgerTakes, lineage, portraitTakes, reelable, statusLabel } from "../../openfield/web/js/lib/takes.js";
import { formatScore, overall, perStage, ringState } from "../../openfield/web/js/lib/identity.js";

const read = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));
const catalog = read("catalog.json");
const plans = read("plans.json");

// -- the Move Pad -----------------------------------------------------------------------------------

test("all 35 moves land in the 7 groups, with twelve promoted and the rest under More", () => {
  const pad = organise(catalog);
  assert.equal(pad.groups.length, 7);
  assert.equal(pad.moves.size, 35);
  assert.equal(pad.featured.length, 12);
  const counted = pad.groups.reduce((n, g) => n + g.featured.length + g.more.length, 0);
  assert.equal(counted, 35);
  assert.ok(pad.groups.every((g) => g.featured.every((m) => m.featured) && g.more.every((m) => !m.featured)));
  assert.deepEqual(locate(pad, "dolly_in"), { group: "dolly", hidden: false });
  assert.deepEqual(locate(pad, "vertigo"), { group: "dolly", hidden: true });
  assert.equal(locate(pad, "nonsense"), null);
});

test("moves are described honestly: a move is tested only once a real render exists", () => {
  const pad = organise(catalog);
  const dolly = describeMove(pad.moves.get("dolly_in"));
  assert.equal(dolly.modeLabel, "Keyframed");
  assert.equal(dolly.stills, 2);
  assert.equal(dolly.stillsLabel, "2 stills");
  assert.equal(dolly.tested, false, "nothing is validated before the first real render");
  assert.equal(dolly.testedLabel, "Not yet tested with a real render");
  const quick = describeMove(pad.moves.get("dolly_in"), { quick: true });
  assert.equal(quick.modeLabel, "Quick");
  assert.equal(quick.stillsLabel, "1 still");
  assert.equal(describeMove(pad.moves.get("static")).modeLabel, "Quick");
  assert.equal(describeMove(pad.moves.get("vertigo")).modeLabel, "Experimental");
  assert.equal(describeMove({ ...pad.moves.get("static"), validated: true }).testedLabel, "Tested with a real render");
});

test("arrow-key stepping wraps around the promoted set", () => {
  const { featured } = organise(catalog);
  const first = featured[0].id;
  const last = featured.at(-1).id;
  assert.equal(step(featured, first, -1), last);
  assert.equal(step(featured, last, 1), first);
  assert.equal(step(featured, first, 1), featured[1].id);
  assert.equal(step(featured, "not-in-the-set", 1), first, "an unknown current move starts from the beginning");
  assert.equal(step([], "x", 1), null);
});

// -- the Direct form --------------------------------------------------------------------------------

test("the form starts valid-looking but empty, and the request body is exactly what the API takes", () => {
  const state = initialDirect(catalog);
  assert.deepEqual(state.rig, defaultRig(catalog));
  assert.equal(state.rig.movement, "dolly_in");
  assert.deepEqual(validate(state, catalog).map((p) => p.field), ["subject"]);

  state.subject = "  A lighthouse at dusk ";
  state.seed = "42";
  state.castId = "ca_1234abcd";
  state.audio = "waves";
  state.quick = true;
  assert.deepEqual(validate(state, catalog), []);
  assert.deepEqual(requestBody(state), {
    subject: "A lighthouse at dusk", rig: state.rig, orientation: "landscape", auto_approve: false,
    prompt_only: true, audio: "waves", seed: 42, cast_id: "ca_1234abcd",
  });
  const bare = requestBody({ ...initialDirect(catalog), subject: "A calm sea" });
  assert.ok(!("seed" in bare) && !("audio" in bare) && !("cast_id" in bare), "empty optional fields are left out");
});

test("validation catches what the server would refuse, before the request", () => {
  const base = { ...initialDirect(catalog), subject: "A calm sea" };
  const fields = (patch, rigPatch = {}) =>
    validate({ ...base, ...patch, rig: { ...base.rig, ...rigPatch } }, catalog).map((p) => p.field);
  assert.deepEqual(fields({ subject: "ab" }), ["subject"]);
  assert.deepEqual(fields({ subject: "x".repeat(801) }), ["subject"]);
  assert.deepEqual(fields({ audio: "x".repeat(401) }), ["audio"]);
  assert.deepEqual(fields({ seed: "-1" }), ["seed"]);
  assert.deepEqual(fields({ seed: "1.5" }), ["seed"]);
  assert.deepEqual(fields({ seed: String(2 ** 31) }), ["seed"]);
  assert.deepEqual(fields({ seed: "0" }), []);
  assert.deepEqual(fields({}, { lens: "fisheye" }), ["lens"]);
  assert.deepEqual(fields({}, { movement: "teleport" }), ["movement"]);
  assert.deepEqual(fields({}, { focal_length_mm: 5 }), ["focal_length_mm"]);
  assert.deepEqual(fields({}, { duration_seconds: 30 }), ["duration_seconds"]);
});

test("the render estimate matches what the pipeline will really run", () => {
  assert.deepEqual(renderEstimate(plans.dolly_in), { stills: 2, videos: 1, total: 3, seconds: 5 });
  assert.deepEqual(renderEstimate(plans.static), { stills: 1, videos: 1, total: 2, seconds: 5 });
  assert.deepEqual(renderEstimate(plans.dolly_in_quick), { stills: 1, videos: 1, total: 2, seconds: 5 });
  // a full orbit returns to the hero: that anchor is reused, not rendered
  const orbit = renderEstimate(plans.orbit_360);
  assert.equal(plans.orbit_360.anchors.length, 5);
  assert.equal(orbit.stills, 4);
  assert.equal(orbit.videos, plans.orbit_360.segments.length);
  assert.equal(planSummary(plans.dolly_in), "2 stills, 1 shot, 5 s");
  assert.equal(planSummary(plans.static), "1 still, 1 shot, 5 s");
});

test("a recipe loads back into the form (Remix)", () => {
  const state = fromRecipe(
    { subject: "A lighthouse", audio: "waves", seed: 7, orientation: "portrait", prompt_only: true,
      rig: { movement: "orbit_90", lens: "anamorphic" } },
    catalog,
  );
  assert.equal(state.subject, "A lighthouse");
  assert.equal(state.seed, 7);
  assert.equal(state.orientation, "portrait");
  assert.equal(state.quick, true);
  assert.equal(state.rig.movement, "orbit_90");
  assert.equal(state.rig.lens, "anamorphic");
  assert.equal(state.rig.sensor, "modern_digital", "fields the recipe lacks keep their defaults");
  assert.deepEqual(validate(state, catalog), []);
});

// -- the Takes list ---------------------------------------------------------------------------------

const T = (id, kind, created, extra = {}) => ({ id, kind, created_at: created, status: "succeeded", outputs: [{ role: "video" }], ...extra });

test("the ledger shows films and exports newest first and keeps generated characters out", () => {
  const takes = [
    T("a", "direct", "2026-10-16T10:00:00Z"),
    T("b", "reshoot", "2026-10-16T12:00:00Z"),
    T("c", "portrait", "2026-10-16T13:00:00Z", { outputs: [] }),
    T("d", "export", "2026-10-16T11:00:00Z", { parent: "a" }),
    T("e", "direct", "2026-10-16T09:00:00Z", { status: "failed" }),
  ];
  assert.deepEqual(ledgerTakes(takes).map((t) => t.id), ["b", "d", "a", "e"]);
  assert.deepEqual(ledgerTakes(takes, { kind: "direct" }).map((t) => t.id), ["a", "e"]);
  assert.deepEqual(ledgerTakes(takes, { status: "failed" }).map((t) => t.id), ["e"]);
  assert.deepEqual(portraitTakes(takes).map((t) => t.id), ["c"]);
  assert.deepEqual(reelable(takes).map((t) => t.id).sort(), ["a", "b", "d"]);
});

test("exports hang under the take they came from, and lineage walks back safely", () => {
  const takes = [
    T("root", "direct", "2026-10-16T09:00:00Z"),
    T("crop", "export", "2026-10-16T10:00:00Z", { parent: "root" }),
    T("reel", "export", "2026-10-16T11:00:00Z", { parent: "crop" }),
    T("loop1", "export", "2026-10-16T12:00:00Z", { parent: "loop2" }),
    T("loop2", "export", "2026-10-16T12:30:00Z", { parent: "loop1" }),
  ];
  assert.deepEqual(Object.keys(children(takes)).sort(), ["crop", "loop1", "loop2", "root"]);
  assert.deepEqual(children(takes).root.map((t) => t.id), ["crop"]);
  assert.deepEqual(lineage(takes, "reel").map((t) => t.id), ["crop", "root"]);
  assert.deepEqual(lineage(takes, "root"), []);
  assert.ok(lineage(takes, "loop1").length <= 2, "a corrupt cycle cannot hang the interface");
});

test("a replayed take is labelled as a replay, never as a render", () => {
  assert.equal(statusLabel(T("a", "direct", "x")), "Done");
  assert.equal(statusLabel(T("a", "direct", "x", { replay: true })), "Replay");
  assert.equal(statusLabel(T("a", "direct", "x", { status: "awaiting_approval" })), "Needs your approval");
  assert.equal(statusLabel(T("a", "direct", "x", { status: "failed" })), "Failed");
  assert.equal(formFor({ kind: "reshoot" }), "reshoot");
  assert.equal(formFor({ kind: "direct" }), "direct");
  assert.equal(formFor({ kind: "export" }), null);
});

// -- the Identity Ring ------------------------------------------------------------------------------

test("the ring maps a report to what to draw, with the threshold as a tick", () => {
  const pass = ringState({ status: "pass", score: 0.71, threshold: 0.363 });
  assert.equal(pass.status, "pass");
  assert.equal(pass.label, "Same person");
  assert.ok(Math.abs(pass.fraction - 0.71) < 1e-9 && Math.abs(pass.tick - 0.363) < 1e-9);
  const drift = ringState({ status: "drift", score: 0.12, threshold: 0.363, retried: true });
  assert.equal(drift.status, "drift");
  assert.equal(drift.retried, true);
  assert.ok(drift.fraction < drift.tick, "a drifted score sits short of the tick");
  assert.equal(ringState({ status: "n/a", score: null }).label, "No real face to compare");
  assert.equal(ringState({ status: "n/a" }).score, null);
  assert.equal(ringState({ status: "unavailable" }).status, "unavailable");
  assert.equal(ringState(null).status, "none");
  assert.equal(ringState({ status: "pass", score: 1.7 }).fraction, 1, "scores are clamped for drawing");
  assert.equal(ringState({ status: "pass", score: -0.2 }).fraction, 0);
});

test("a take's overall identity is its worst stage, and unavailable never reads as a match", () => {
  const identity = { hero: { status: "pass", score: 0.8 }, anchor_1: { status: "drift", score: 0.1 }, shoot_1: { status: "n/a" } };
  assert.equal(overall(identity).status, "drift");
  assert.equal(overall({ hero: { status: "pass", score: 0.8 }, shoot_1: { status: "n/a" } }).status, "pass");
  assert.equal(overall({ hero: { status: "n/a" } }).status, "na");
  assert.equal(overall({}).status, "none");
  assert.equal(overall(undefined).status, "none");
  assert.deepEqual(perStage(identity).map((s) => [s.stage, s.status]), [["hero", "pass"], ["anchor_1", "drift"], ["shoot_1", "na"]]);
  assert.equal(formatScore(0.7134), "0.71");
  assert.equal(formatScore(null), "—");
});

// -- Move Pad glyphs --------------------------------------------------------------------------------

import { anchorsAlong, sideView, topView } from "../../openfield/web/js/lib/pathview.js";

test("every move path projects to finite, in-bounds glyph coordinates in both views", () => {
  for (const move of catalog.moves) {
    assert.ok(move.path.length >= 2, `${move.id} has a path`);
    for (const [name, view] of [["top", topView(move.path)], ["side", sideView(move.path)]]) {
      assert.equal(view.points.length, move.path.length, `${move.id} ${name}`);
      for (const p of [...view.points, view.origin]) {
        assert.ok(Number.isFinite(p.x) && Number.isFinite(p.y), `${move.id} ${name} is finite`);
        assert.ok(p.x >= 0 && p.x <= 100 && p.y >= 0 && p.y <= 100, `${move.id} ${name} stays inside the glyph box`);
      }
      assert.match(view.d, /^M[\d.]+ [\d.]+( L[\d.]+ [\d.]+)+$/, `${move.id} ${name} is a valid path`);
    }
    const anchors = anchorsAlong(topView(move.path), move.anchors);
    assert.equal(anchors.length, move.anchors, `${move.id} gets one marker per anchor`);
  }
});

test("a moving camera draws a path with length, a locked one barely moves", () => {
  const length = (view) => view.points.slice(1).reduce((sum, p, i) => sum + Math.hypot(p.x - view.points[i].x, p.y - view.points[i].y), 0);
  const pad = organise(catalog);
  assert.ok(length(topView(pad.moves.get("dolly_in").path)) > 5);
  assert.ok(length(topView(pad.moves.get("orbit_180").path)) > length(topView(pad.moves.get("orbit_90").path)));
  assert.ok(length(sideView(pad.moves.get("crane_up").path)) > 5);
  assert.ok(length(topView(pad.moves.get("static").path)) < 0.001);
});
