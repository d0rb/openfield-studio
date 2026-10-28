import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { describeMove, locate, organise, step } from "../../openfield/web/js/lib/movepad.js";
import {
  defaultRig, describeDialogue, fromRecipe, initialDirect, matchesRecording, planSummary, renderEstimate, requestBody, validate,
} from "../../openfield/web/js/lib/direct.js";
import { formFor, children, ledgerTakes, lineage, portraitTakes, reelable, statusLabel } from "../../openfield/web/js/lib/takes.js";
import { formatScore, overall, perStage, ringState } from "../../openfield/web/js/lib/identity.js";

const read = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));
const catalog = read("catalog.json");
const plans = read("plans.json");

// -- the Move Pad -----------------------------------------------------------------------------------

test("all 49 moves land in the 7 groups, with twelve promoted and the rest under More", () => {
  const pad = organise(catalog);
  assert.equal(pad.groups.length, 7);
  assert.equal(pad.moves.size, 49);
  assert.equal(pad.featured.length, 12);
  const counted = pad.groups.reduce((n, g) => n + g.featured.length + g.more.length, 0);
  assert.equal(counted, 49);
  assert.ok(pad.groups.every((g) => g.featured.every((m) => m.featured) && g.more.every((m) => !m.featured)));
  assert.deepEqual(locate(pad, "dolly_in"), { group: "dolly", hidden: false });
  assert.deepEqual(locate(pad, "vertigo"), { group: "dolly", hidden: true });
  assert.equal(locate(pad, "nonsense"), null);
});

test("a move is described by how it is made; the server's flag still says whether its recorded loop plays at rest", () => {
  const pad = organise(catalog);
  const dolly = describeMove(pad.moves.get("dolly_in"));
  assert.equal(dolly.modeLabel, "Keyframed");
  assert.equal(dolly.stills, 2);
  assert.equal(dolly.stillsLabel, "2 stills");
  assert.equal(dolly.tested, true, "dolly in was validated by the keyframing experiment of 2026-10-20");
  assert.ok(!("testedLabel" in dolly), "the interface no longer prints tested or untested");
  assert.equal(describeMove(pad.moves.get("through_object")).tested, true, "Oct 26: made as its reverse, the push through the hut door held");
  assert.equal(describeMove(pad.moves.get("pedestal_down")).tested, false, "the flag stays false until a render holds (the reversed descent pulled back)");
  assert.equal(describeMove(pad.moves.get("orbit_90")).modeLabel, "Quick", "a move the experiment settled as prompt-only renders from one still");
  const arc = describeMove(pad.moves.get("arc_left"));
  assert.equal(arc.modeLabel, "Keyframed", "an arc is two stills since Oct 26: the end still, 45 degrees round, sets the direction");
  assert.equal(arc.stillsLabel, "2 stills");
  assert.equal(arc.tested, false, "unflagged until a render of the two-still arc holds");
  const quick = describeMove(pad.moves.get("dolly_in"), { quick: true });
  assert.equal(quick.modeLabel, "Quick");
  assert.equal(quick.stillsLabel, "1 still");
  assert.equal(describeMove(pad.moves.get("static")).modeLabel, "Quick");
  assert.equal(describeMove(pad.moves.get("rack_focus")).modeLabel, "Quick", "an experimental move reads as what it is: one still and a camera instruction");
  assert.equal(describeMove(pad.moves.get("vertigo")).stillsLabel, "2 stills", "the dolly zoom is made from a dolly-out's two stills");
  const bullet = describeMove(pad.moves.get("bullet_time"), { quick: true });
  assert.equal(bullet.modeLabel, "Quick", "bullet time is one still of the frozen moment, circled by the camera");
  assert.equal(bullet.stillsLabel, "1 still");
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
  assert.deepEqual(fields({}, { effect: "snow" }), ["effect"]);
  assert.deepEqual(fields({}, { effect: "rain" }), []);
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

import { anchorsAlong, frustum, poseAt, sideView, stageFit, topView } from "../../openfield/web/js/lib/pathview.js";

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

test("every move fits the stage view, and its camera lands on each numbered mark when the shot reaches that still", () => {
  for (const move of catalog.moves) {
    const fit = stageFit(move.path, { width: 100, height: 62 });
    const inside = (p, what) => assert.ok(p.x >= -0.5 && p.x <= 100.5 && p.y >= -0.5 && p.y <= 62.5 && Number.isFinite(p.x + p.y), `${move.id}: ${what} at ${p.x},${p.y}`);
    for (const p of move.path) inside(fit.to(p), "path");
    for (const p of move.path) inside(fit.to({ ...p, y: fit.floor }), "the floor under the path");
    inside(fit.to({ x: 0, y: fit.floor, z: 0 }), "the subject's mark");
    for (let i = 0; i <= 20; i += 1) for (const c of frustum(poseAt(move.path, i / 20)).corners) inside(fit.to(c), "frame");
    const view = { points: move.path.map(fit.to) };
    const count = Math.max(2, move.anchors);
    anchorsAlong(view, count).forEach((mark, k) => {
      const camera = fit.to(poseAt(move.path, k / (count - 1)));
      assert.ok(Math.hypot(mark.x - camera.x, mark.y - camera.y) < 1e-9, `${move.id}: mark ${k + 1} is where the camera is`);
    });
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

test("a form that starts from an image sends a multipart body and never matches a recording", async () => {
  const d = await import("../../openfield/web/js/lib/direct.js");
  const catalog = JSON.parse(readFileSync(new URL("./fixtures/catalog.json", import.meta.url), "utf8"));
  const state = { ...d.initialDirect(catalog), subject: "Me on a pier at dusk", seed: "3" };
  assert.equal(d.fromImage(state), false);
  const withImage = { ...state, heroMode: "image", sourceFile: null };
  assert.ok(d.validate(withImage, catalog).some((p) => p.field === "source"), "an image is required in image mode");
  const file = { name: "me.png", size: 1024 };
  const ready = { ...withImage, sourceFile: file };
  assert.ok(!d.validate(ready, catalog).some((p) => p.field === "source"));
  assert.ok(d.validate({ ...ready, sourceFile: { name: "me.gif", size: 10 } }, catalog).some((p) => p.field === "source"));
  assert.ok(d.validate({ ...ready, sourceFile: { name: "me.png", size: 21 * 1024 * 1024 } }, catalog).some((p) => p.field === "source"));
  const parts = [];
  class FD { append(k, v) { parts.push([k, v]); } }
  d.toImageForm(ready, FD);
  assert.deepEqual(parts.map(([k]) => k), ["request", "source"]);
  assert.equal(JSON.parse(parts[0][1]).subject, "Me on a pier at dusk");
  assert.equal(parts[1][1], file);
  assert.equal(JSON.stringify(d.requestBody(ready)), JSON.stringify(d.requestBody(state)), "the JSON body is unchanged by the image");
  const recorded = { kind: "direct", recipe: { ...d.formRecipe(state), source_sha256: undefined, cast_name: null } };
  delete recorded.recipe.source_sha256;
  assert.equal(d.matchesRecording(state, recorded), true);
  assert.equal(d.matchesRecording(ready, recorded), false, "a form with an image never matches a recording");
  const sourcedRecording = { kind: "direct", recipe: { ...recorded.recipe, source_sha256: "abc" } };
  assert.equal(d.matchesRecording(state, sourcedRecording), false, "a form without one never matches a sourced recording");
  const back = d.fromRecipe(sourcedRecording.recipe, catalog);
  assert.equal(back.heroMode, "image");
  assert.equal(back.sourceFile, null, "the image itself must be added again");
  assert.equal(d.fromRecipe(recorded.recipe, catalog).heroMode, "prompt");
});

test("quality is sent only when it is not standard, and a tier changes what matches", async () => {
  const d = await import("../../openfield/web/js/lib/direct.js");
  const catalog = JSON.parse(readFileSync(new URL("./fixtures/catalog.json", import.meta.url), "utf8"));
  assert.deepEqual(catalog.quality.map((q) => q.id), ["draft", "standard", "fine"]);
  const state = { ...d.initialDirect(catalog), subject: "A lighthouse at dusk", seed: "5" };
  assert.equal(state.quality, "standard");
  assert.ok(!("quality" in d.requestBody(state)), "standard is the server's default and stays out of the body");
  assert.equal(d.requestBody({ ...state, quality: "draft" }).quality, "draft");
  assert.ok(d.validate({ ...state, quality: "ultra" }, catalog).some((p) => p.field === "quality"));
  const recorded = { kind: "direct", recipe: { ...d.formRecipe(state), cast_name: null } };
  delete recorded.recipe.quality;
  delete recorded.recipe.source_sha256;
  assert.equal(d.matchesRecording(state, recorded), true, "a recording made before tiers existed is a standard take");
  assert.equal(d.matchesRecording({ ...state, quality: "draft" }, recorded), false);
  assert.equal(d.matchesRecording(state, { kind: "direct", recipe: { ...recorded.recipe, quality: "fine" } }), false);
  assert.equal(d.fromRecipe({ ...recorded.recipe, quality: "fine" }, catalog).quality, "fine");
  assert.equal(d.fromRecipe(recorded.recipe, catalog).quality, "standard");
  const fine = d.describeQuality(catalog, "fine");
  assert.equal(fine.tested, true, "checked by eye on the Oct 22 render");
  assert.ok(!("testedLabel" in fine));
  assert.equal(d.describeQuality(catalog, "standard").tested, true);
  assert.equal(d.describeQuality(catalog, "nope"), null);
  assert.equal(d.estimateLine(null), null);
  assert.equal(d.estimateLine({ samples: 0, seconds: null, basis: "render time, approvals not counted" }), "No time measured yet on this backend");
  assert.equal(d.estimateLine({ samples: 0, seconds: null, basis: "Replay renders nothing" }), null);
  assert.equal(d.estimateLine({ samples: 3, seconds: 135.4 }), "≈ 2 min 15 s, about 2.7¢, measured here (3 takes)");
  assert.equal(d.estimateLine({ samples: 1, seconds: 48 }), "≈ 48 s, about 0.9¢, measured here (1 take)");
});

test("a spoken line travels with its delivery, is validated, and is part of what a recording must match", () => {
  const base = { ...initialDirect(catalog), subject: "Mara at the pier" };
  assert.ok(!("line" in requestBody(base)) && !("delivery" in requestBody(base)), "a silent form sends no dialogue keys");
  const spoken = { ...base, line: "  We leave at first light.  ", delivery: "calm", language: " English " };
  assert.deepEqual(validate(spoken, catalog), []);
  const body = requestBody(spoken);
  assert.equal(body.line, "We leave at first light.");
  assert.equal(body.delivery, "calm");
  assert.equal(body.language, "English");
  assert.ok(!("language" in requestBody({ ...spoken, language: "" })), "the language is named only when given");
  const fields = (patch) => validate({ ...base, ...patch }, catalog).map((p) => p.field);
  assert.deepEqual(fields({ line: "x".repeat(201) }), ["line"]);
  assert.deepEqual(fields({ line: "hi", delivery: "sing" }), ["delivery"]);
  assert.deepEqual(fields({ language: "y".repeat(41) }), ["language"]);
  assert.deepEqual(fields({ delivery: "sing" }), [], "a delivery without a line is ignored");
  const d = describeDialogue(catalog);
  assert.ok(d.deliveries.some((x) => x.id === "whisper") && d.tested === true && !("testedLabel" in d));
  const back = fromRecipe({ subject: "Mara", line: "Come home.", delivery: "whisper", language: "English", rig: {} }, catalog);
  assert.equal(back.line, "Come home.");
  assert.equal(back.delivery, "whisper");
  assert.equal(back.language, "English");
  const silentBack = fromRecipe({ subject: "Mara", delivery: "shout", rig: {} }, catalog);
  assert.equal(silentBack.delivery, "natural", "a delivery without a line is not kept");
  const recorded = { kind: "direct", recipe: { subject: "Mara at the pier", rig: base.rig, seed: 7, orientation: "landscape", cast_refs: [] } };
  const form = { ...base, seed: "7" };
  assert.equal(matchesRecording(form, recorded), true);
  assert.equal(matchesRecording({ ...form, line: "Come home." }, recorded), false, "a line makes a different shot");
  const spokenRecording = { kind: "direct", recipe: { ...recorded.recipe, line: "Come home.", delivery: "whisper" } };
  assert.equal(matchesRecording({ ...form, line: "Come home.", delivery: "whisper" }, spokenRecording), true);
  assert.equal(matchesRecording({ ...form, line: "Come home.", delivery: "calm" }, spokenRecording), false, "the delivery is part of the recipe");
});
