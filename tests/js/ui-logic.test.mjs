import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { estimatePlan, formRecipe, initialDirect, matchesRecording, optionLabel, planSummary, renderEstimate } from "../../openfield/web/js/lib/direct.js";
import { glyph } from "../../openfield/web/js/lib/pathview.js";
import { clock, focusTake, monitorMode, railStates, recordingIds, stageList, stepName, titleOf } from "../../openfield/web/js/lib/stages.js";

const load = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));
const catalog = load("catalog.json");
const table = load("plan_table.json");
const move = (id) => catalog.moves.find((m) => m.id === id);

test("the browser's plan estimate matches the server for every move, length and mode", () => {
  let checked = 0;
  for (const [key, expected] of Object.entries(table)) {
    const [id, seconds, mode] = key.split("|");
    const plan = estimatePlan(move(id), Number(seconds), mode === "quick");
    assert.equal(plan.mode, expected.mode, key);
    assert.deepEqual(plan.anchors.map((a) => a.role), expected.roles, key);
    assert.deepEqual(plan.segments.map((s) => s.seconds), expected.segments, key);
    assert.equal(plan.total_seconds, expected.total, key);
    checked += 1;
  }
  assert.equal(checked, catalog.moves.length * 10);
});

test("the plan line counts the stills and the shots that will be rendered", () => {
  assert.equal(planSummary(estimatePlan(move("dolly_in"), 5)), "2 stills, 1 shot, 5 s");
  assert.equal(planSummary(estimatePlan(move("dolly_in"), 5, true)), "1 still, 1 shot, 5 s");
  // a full orbit repeats the hero still instead of rendering it twice
  const orbit = renderEstimate(estimatePlan(move("orbit_360"), 8));
  assert.equal(orbit.stills, 4);
  assert.equal(orbit.videos, 4);
});

test("a length that does not divide into segments says what it became", () => {
  const plan = estimatePlan(move("orbit_360"), 5);
  assert.equal(plan.total_seconds, 8);
  assert.match(plan.notes[0], /4 shots of 2 s make 8 s, not 5 s/);
  assert.deepEqual(estimatePlan(move("dolly_in"), 5).notes, []);
});

test("option ids read as words", () => {
  assert.equal(optionLabel("modern_digital"), "Modern digital");
  assert.equal(optionLabel("35mm_film"), "35mm film");
  assert.equal(optionLabel("f1.4"), "f/1.4");
  assert.equal(optionLabel("contre_jour"), "Contre-jour");
  assert.equal(optionLabel("steady"), "Steady");
});

test("a form matches a recording only when every part of the shot is the same", () => {
  const state = initialDirect(catalog);
  state.subject = "  A lighthouse at dusk ";
  state.seed = "7";
  const recipe = { kind: "direct", subject: "A lighthouse at dusk", rig: { ...state.rig }, audio: null, seed: 7, orientation: "landscape", cast_refs: [], cast_name: null, auto_approve: false };
  const recorded = { kind: "direct", recipe };
  assert.equal(matchesRecording(state, recorded), true);
  assert.equal(matchesRecording({ ...state, seed: "8" }, recorded), false);
  assert.equal(matchesRecording({ ...state, seed: "" }, recorded), false, "a random seed can never match a recording");
  assert.equal(matchesRecording({ ...state, rig: { ...state.rig, movement: "dolly_out" } }, recorded), false);
  assert.equal(matchesRecording({ ...state, quick: true }, recorded), false);
  assert.equal(matchesRecording({ ...state, audio: "waves" }, recorded), false);
  assert.equal(matchesRecording(state, recorded, "Mara"), false, "a recording made with a character needs that character");
  assert.equal(matchesRecording(state, { kind: "reshoot", recipe }), false);
  assert.equal(formRecipe(state).seed, 7);
});

test("glyphs: travelling cameras draw a path, zooms and stills are symbols", () => {
  assert.equal(glyph(move("static")).kind, "still");
  assert.deepEqual(glyph(move("optical_zoom_in")), { kind: "zoom", direction: "in" });
  const dolly = glyph(move("dolly_in"));
  assert.equal(dolly.kind, "path");
  assert.equal(dolly.view, "top");
  const crane = glyph(move("crane_up"));
  assert.equal(crane.kind, "path");
  assert.equal(crane.view, "side", "a crane moves in height, which only the side view shows");
  assert.ok(glyph(move("orbit_180")).d.length > 40, "an arc keeps its curve");
  for (const m of catalog.moves) assert.ok(["path", "zoom", "turn", "still"].includes(glyph(m).kind), m.id);
});

const direct = (extra = {}) => ({
  kind: "direct", status: "running",
  recipe: { rig: { movement: "dolly_in", duration_seconds: 5 }, prompt_only: false, auto_approve: false, ...extra },
});

test("a keyframed Direct take lists hero, anchor, approval, shot and finish", () => {
  const ids = stageList(direct(), catalog).map((s) => s.id);
  assert.deepEqual(ids, ["hero", "anchor_1", "review", "shoot_1", "finish"]);
  assert.deepEqual(stageList(direct({ prompt_only: true }), catalog).map((s) => s.id), ["hero", "review", "shoot_1", "finish"]);
  assert.deepEqual(stageList(direct({ auto_approve: true }), catalog).map((s) => s.id), ["hero", "anchor_1", "shoot_1", "finish"]);
  assert.equal(stageList(direct(), catalog).find((s) => s.id === "shoot_1").name, "Shoot");
});

test("other kinds have their own steps", () => {
  assert.deepEqual(stageList({ kind: "reshoot" }, catalog).map((s) => s.id), ["prepare", "motion", "finish"]);
  assert.deepEqual(stageList({ kind: "portrait", recipe: { count: 2 } }, catalog).map((s) => s.id), ["candidate_1", "candidate_2", "finish"]);
  assert.equal(stepName("anchor_2"), "Anchor 2");
  assert.equal(stepName("shoot_3"), "Shot 3");
});

test("the rail marks what is done, what is running and what is waiting", () => {
  const list = stageList(direct(), catalog);
  const at = (stage, stageState, status = "running") => railStates(list, { status }, { stage, stageState });
  assert.deepEqual(at(null, null, "queued"), ["pending", "pending", "pending", "pending", "pending"]);
  assert.deepEqual(at("hero", "start"), ["active", "pending", "pending", "pending", "pending"]);
  assert.deepEqual(at("hero", "done"), ["done", "active", "pending", "pending", "pending"]);
  assert.deepEqual(at("anchor_1", "done", "awaiting_approval"), ["done", "done", "active", "pending", "pending"]);
  assert.deepEqual(at("shoot_1", "start"), ["done", "done", "done", "active", "pending"]);
  assert.deepEqual(at("finish", "done", "succeeded"), ["done", "done", "done", "done", "done"]);
  assert.deepEqual(at("shoot_1", "start", "failed"), ["done", "done", "done", "failed", "pending"]);
  assert.deepEqual(at("hero", "start", "canceled"), ["canceled", "pending", "pending", "pending", "pending"]);
  assert.deepEqual(at("not_a_stage", "start"), ["active", "pending", "pending", "pending", "pending"], "an unknown stage never breaks the rail");
});

test("the monitor mode follows the take's status", () => {
  assert.equal(monitorMode(null), "empty");
  for (const [status, mode] of Object.entries({ queued: "running", running: "running", awaiting_approval: "approval", failed: "failed", canceled: "canceled", succeeded: "ready" })) {
    assert.equal(monitorMode({ status }), mode, status);
  }
  assert.equal(clock(65), "1:05");
  assert.equal(clock(-3), "0:00");
});

test("the promoted moves' glyphs fill their tile, so each is readable at a glance", () => {
  for (const m of catalog.moves.filter((x) => x.featured)) {
    const g = glyph(m);
    if (g.kind !== "path") continue;
    const nums = g.d.match(/-?\d+\.?\d*/g).map(Number);
    const xs = nums.filter((_, i) => i % 2 === 0);
    const ys = nums.filter((_, i) => i % 2 === 1);
    assert.ok(Math.min(...xs, ...ys) >= 12 && Math.max(...xs, ...ys) <= 88, `${m.id} stays inside the tile`);
    const extent = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
    assert.ok(extent >= 55, `${m.id} travels most of the tile (${extent.toFixed(1)} of 100)`);
  }
});

test("in Replay every replayable take is a recording; with a real backend takes are just takes", () => {
  const rec = (id, kind = "direct") => ({ id, kind, label: id, recipe: {}, outputs: [], created_at: "2026-10-16T10:00:00Z" });
  const base = { takes: [{ ...rec("tk_a"), status: "succeeded", created_at: "2026-10-16T10:00:00Z" }], recorded: [rec("tk_a")], selected: null };
  const locked = { ...base, status: { backend: { locked: true } } };
  const live = { ...base, status: { backend: { locked: false } } };
  assert.deepEqual([...recordingIds(locked)], ["tk_a"]);
  assert.equal(recordingIds(live).size, 0);
  assert.equal(focusTake(locked, ["direct"]).recorded, true, "the hosted copy lists its recordings among its takes");
  assert.equal(focusTake(live, ["direct"]).recorded, false);
  // a take made by playing a recording back has its own id, so it is not a recording
  const played = { ...locked, takes: [{ ...rec("tk_replay_1"), status: "succeeded", replay: true, created_at: "2026-10-17T10:00:00Z" }, ...locked.takes] };
  assert.equal(focusTake(played, ["direct"]).recorded, false);
  assert.equal(focusTake({ ...locked, takes: [] }, ["direct"]).recorded, true, "with no takes, the recording is the thing to watch");
});
