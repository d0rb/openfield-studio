import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { effectKind, estimatePlan, formRecipe, initialDirect, matchesRecording, optionLabel, planSummary, renderEstimate } from "../../openfield/web/js/lib/direct.js";
import { glyph } from "../../openfield/web/js/lib/pathview.js";
import { clock, focusTake, monitorMode, railStates, recordingIds, stageList, stageStrip, stepName, titleOf } from "../../openfield/web/js/lib/stages.js";

const load = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));
const catalog = load("catalog.json");
const table = load("plan_table.json");
const move = (id) => catalog.moves.find((m) => m.id === id);

test("the browser's plan estimate matches the server for every move, length, mode, transformation and pass", () => {
  let checked = 0;
  for (const [key, expected] of Object.entries(table)) {
    const [id, seconds, mode, effect, pass] = key.split("|");
    const plan = estimatePlan(move(id), Number(seconds), mode === "quick", { effectKind: effectKind(catalog, effect), singlePass: pass === "one" });
    assert.equal(plan.mode, expected.mode, key);
    assert.deepEqual(plan.anchors.map((a) => a.role), expected.roles, key);
    assert.deepEqual(plan.segments.map((s) => s.seconds), expected.segments, key);
    assert.equal(plan.total_seconds, expected.total, key);
    checked += 1;
  }
  // every move at 3 lengths, full and quick, 3 effects, 2 passes; a move played backwards takes no effect, so only its plain rows exist
  assert.equal(checked, catalog.moves.reduce((n, m) => n + 3 * 2 * (m.reversed ? 1 : 3) * 2, 0));
  assert.ok(catalog.moves.some((m) => m.reversed), "the catalog names the moves played backwards");
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
  // effects: "none" is no effect at all (old recordings have no such key), a set effect must match
  const { effect: _none, ...bare } = state.rig;
  assert.equal(matchesRecording(state, { kind: "direct", recipe: { ...recipe, rig: bare } }), true, "a recording made before effects existed still matches");
  assert.equal("effect" in formRecipe(state).rig, false);
  assert.equal(matchesRecording({ ...state, rig: { ...state.rig, effect: "rain" } }, recorded), false);
  assert.equal(matchesRecording({ ...state, rig: { ...state.rig, effect: "rain" } }, { kind: "direct", recipe: { ...recipe, rig: { ...bare, effect: "rain" } } }), true);
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
  assert.equal(stepName("hero_retry"), "Hero still, re-rolled");
  assert.equal(stepName("anchor_1_retry"), "Anchor 1, re-rolled");
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

import { parseHash, takeLink } from "../../openfield/web/js/lib/route.js";
import { fromRecorded, sampleTake, sheetSubject } from "../../openfield/web/js/lib/stages.js";

test("a take link names its station and the take; anything else is a station, or the Lobby", () => {
  const routes = new Set(["cast", "direct", "reshoot", "takes"]);
  assert.deepEqual(parseHash("#/takes/tk_20261017_082943_c079", routes), { route: "takes", id: "tk_20261017_082943_c079" });
  assert.deepEqual(parseHash("#/reshoot", routes), { route: "reshoot", id: null });
  assert.deepEqual(parseHash("#/nowhere/x", routes), { route: "lobby", id: null });
  assert.deepEqual(parseHash("#recipe=abc", routes), { route: "lobby", id: null });
  assert.deepEqual(parseHash("", routes), { route: "lobby", id: null });
  assert.equal(takeLink("tk_1", { origin: "https://example.test", pathname: "/studio/" }), "https://example.test/studio/#/takes/tk_1");
});

test("a move's sample is the newest finished Direct take that shows it, recordings included", () => {
  const take = (id, movement, extra = {}) => ({ id, kind: "direct", status: "succeeded", recipe: { rig: { movement } }, outputs: [{ role: "video", file: "take.mp4" }], created_at: id, ...extra });
  const state = {
    takes: [take("t2", "dolly_in"), take("t1", "dolly_in"), take("x", "orbit_90", { status: "failed" }), take("y", "crane_up", { outputs: [] })],
    recorded: [{ id: "r1", kind: "direct", label: "r", recipe: { rig: { movement: "orbit_90" } }, outputs: [{ role: "video", file: "take.mp4" }], media_base: "", created_at: "r1" }],
  };
  assert.equal(sampleTake(state, "dolly_in").id, "t2");
  assert.equal(sampleTake(state, "orbit_90").id, "r1");
  assert.equal(sampleTake(state, "crane_up"), null);
  assert.equal(sampleTake({}, "dolly_in"), null);
});

test("the sheet is built from the subject most moves share, so a newer take of another shot does not break the set", () => {
  const take = (id, movement, subject) => ({ id, kind: "direct", status: "succeeded", recipe: { subject, rig: { movement } }, outputs: [{ role: "video", file: "take.mp4" }], created_at: id });
  const state = { takes: [take("t9", "dolly_in", "Mara pushes a bicycle"), take("t3", "crane_up", "Mara on the pier"), take("t2", "dolly_in", "Mara on the pier"), take("t1", "static", "Mara on the pier")] };
  const moves = ["static", "dolly_in", "crane_up", "orbit_90"];
  assert.equal(sheetSubject(state, moves), "Mara on the pier");
  assert.equal(sampleTake(state, "dolly_in", { subject: "Mara on the pier" }).id, "t2");
  assert.equal(sampleTake(state, "dolly_in").id, "t9", "without a subject the newest take still wins");
  assert.equal(sampleTake(state, "orbit_90", { subject: "Mara on the pier" }), null);
  assert.equal(sheetSubject({ takes: [] }, moves), null);
});

test("a take built from a recording keeps the recording's identity and audit when it has them", () => {
  const rec = { id: "tk_b", kind: "direct", label: "b", recipe: {}, outputs: [], created_at: "2026-10-20T10:00:00Z" };
  assert.equal(fromRecorded(rec).identity, undefined);
  const proven = fromRecorded({ ...rec, identity: { hero: { score: 0.81 } }, audit: { result: "pass" } });
  assert.equal(proven.identity.hero.score, 0.81);
  assert.equal(proven.audit.result, "pass");
});

test("the stage strip reads the approved stills off the receipt, names a re-roll, and ends on the shot", () => {
  const take = {
    kind: "direct", status: "succeeded",
    outputs: [{ role: "video", file: "take.mp4" }, { role: "poster", file: "poster.png" }],
    identity: {
      hero: { status: "drift", score: 0.2, retried: true },
      hero_retry: { status: "pass", score: 0.81 },
      anchor_1: { status: "pass", score: 0.7 },
      shoot_1: { status: "pass", score: 0.69 },
    },
  };
  const receipt = { inputs: { anchors: [{ index: 0, file: "runs/02_hero_retry/image.png" }, { index: 1, file: "runs/03_anchor_1/image.png" }] } };
  const strip = stageStrip(take, receipt);
  assert.deepEqual(strip.map((s) => [s.id, s.name, s.file, s.approved, s.report?.score ?? null]), [
    ["hero_retry", "Hero still, re-rolled", "runs/02_hero_retry/image.png", true, 0.81],
    ["anchor_1", "Anchor 1", "runs/03_anchor_1/image.png", true, 0.7],
    ["shot", "Shot", "poster.png", false, 0.69],
  ]);
  assert.deepEqual(stageStrip(take, null), [], "no receipt, no strip");
  assert.deepEqual(stageStrip({ ...take, outputs: [] }, receipt).map((s) => s.id), ["hero_retry", "anchor_1"], "no poster, no shot");
});

test("a take that started from the person's image calls its hero 'Your photo'", async () => {
  const { stageList, stageStrip } = await import("../../openfield/web/js/lib/stages.js");
  const catalog = JSON.parse(readFileSync(new URL("./fixtures/catalog.json", import.meta.url), "utf8"));
  const take = { kind: "direct", recipe: { rig: { movement: "dolly_in", duration_seconds: 5 }, source_sha256: "abc" }, identity: {}, outputs: [{ role: "poster", file: "poster.png" }] };
  assert.deepEqual(stageList(take, catalog).map((s) => s.name).slice(0, 2), ["Your photo", "Anchor 1"]);
  const plain = { ...take, recipe: { rig: { movement: "dolly_in", duration_seconds: 5 } } };
  assert.equal(stageList(plain, catalog)[0].name, "Hero still");
  const strip = stageStrip(take, { inputs: { anchors: [{ index: 0, file: "inputs/hero.png" }, { index: 1, file: "runs/01_anchor_1/image.png" }] } });
  assert.deepEqual(strip.map((s) => s.name), ["Your photo", "Anchor 1", "Shot"]);
});

// -- the 9:16 crop focus --------------------------------------------------------------------------------------------------

import { cropFocus } from "../../openfield/web/js/lib/takes.js";

test("a take's 9:16 crop focus is remembered, and defaults to the centre", () => {
  const remembered = new Map([["tk_a", 0.2], ["tk_left", 0]]);
  assert.equal(cropFocus(remembered, "tk_a"), 0.2);
  assert.equal(cropFocus(remembered, "tk_left"), 0, "the left edge is a real choice, not a missing one");
  assert.equal(cropFocus(remembered, "tk_b"), 0.5);
  assert.equal(cropFocus(new Map(), "tk_a"), 0.5);
});

// -- the filmstrip's order ----------------------------------------------------------------------------------------------

import { stripItems } from "../../openfield/web/js/ui/filmstrip.js";

test("the filmstrip shows recordings in the showcase's reel order, after the takes made here", () => {
  const rec = (id, kind = "direct") => ({ id, kind, label: id, status: "succeeded", outputs: [] });
  const state = {
    takes: [{ id: "mine", kind: "direct", status: "succeeded", outputs: [] }],
    recorded: [rec("newest"), rec("middle"), rec("oldest"), rec("dance", "reshoot")],
    status: { hero_reel: ["oldest", "newest"] },
  };
  assert.deepEqual(stripItems(state, ["direct"]).map((t) => t.id), ["mine", "oldest", "newest", "middle"]);
  assert.deepEqual(stripItems({ ...state, status: {} }, ["direct"]).map((t) => t.id), ["mine", "newest", "middle", "oldest"], "no reel: newest first, as served");
  assert.deepEqual(stripItems(state, ["reshoot"]).map((t) => t.id), ["dance"]);
});

// -- angles ----------------------------------------------------------------------------------------------------------------------

import { angleSheet } from "../../openfield/web/js/lib/stages.js";
import { ANGLE_DEFAULT, angleGeometry, describeAngle, recipeRig, validate } from "../../openfield/web/js/lib/direct.js";

test("the default angle is left out of a recipe, exactly as the server leaves it out", () => {
  const state = initialDirect(catalog);
  assert.equal(state.rig.angle, ANGLE_DEFAULT, "the catalog's default rig carries the angle");
  assert.equal("angle" in formRecipe(state).rig, false);
  assert.equal(recipeRig({ ...state.rig, angle: "back/low/wide" }).angle, "back/low/wide");
  assert.deepEqual(validate({ ...state, subject: "A bottle", rig: { ...state.rig, angle: "nowhere" } }, catalog).map((p) => p.field), ["angle"]);
  assert.deepEqual(validate({ ...state, subject: "A bottle", rig: { ...state.rig, angle: "back/low/wide" } }, catalog), []);
});

test("score and soundscape are left out of a recipe at none and kept when set", () => {
  const state = initialDirect(catalog);
  assert.equal("score" in formRecipe(state).rig, false);
  assert.equal("soundscape" in formRecipe(state).rig, false);
  assert.equal(recipeRig({ ...state.rig, score: "strings" }).score, "strings");
  assert.equal(recipeRig({ ...state.rig, soundscape: "harbour" }).soundscape, "harbour");
  assert.deepEqual(validate({ ...state, subject: "A bottle", rig: { ...state.rig, soundscape: "space_station" } }, catalog).map((p) => p.field), ["soundscape"]);
  assert.deepEqual(validate({ ...state, subject: "A bottle", rig: { ...state.rig, score: "orchestra" } }, catalog).map((p) => p.field), ["score"]);
  assert.deepEqual(validate({ ...state, subject: "A bottle", rig: { ...state.rig, score: "strings", soundscape: "harbour" } }, catalog), []);
});

test("an angle is described from the catalog and gives the stage its pivot", () => {
  assert.equal(describeAngle(catalog, "back_left/low/wide"), "Back-left quarter · Low angle · Wide");
  assert.equal(describeAngle(catalog, ANGLE_DEFAULT), null);
  assert.deepEqual(angleGeometry(catalog, "right/high/close"), { azimuth: 90, elevation: 60, distance: 0.6 });
  assert.equal(angleGeometry(catalog, "right/high"), null);
});

test("the rail shows the angled still after the hero, and the angles sheet picks the subject with the most positions", () => {
  const take = { kind: "direct", recipe: { rig: { movement: "dolly_in", duration_seconds: 5, angle: "back/low/wide" } } };
  assert.deepEqual(stageList(take, catalog).map((s) => s.name), ["Hero still", "Angled still", "Anchor 1", "Approve", "Shoot", "Finish"]);
  const rec = (id, subject, angle, created) => ({ id, kind: "direct", status: "succeeded", created_at: created, recipe: { subject, rig: { movement: "static", angle } }, outputs: [{ role: "video", file: "take.mp4" }] });
  const state = { takes: [rec("t1", "Oskar", "left/eye/medium", "2026-10-25")], recorded: [rec("r1", "Oskar", "front_right/eye/medium", "2026-10-24"), rec("r2", "Oskar", "left/eye/medium", "2026-10-23"), rec("r3", "Mara", "back/eye/medium", "2026-10-24")], status: { backend: { locked: true } } };
  const sheet = angleSheet(state, catalog);
  assert.deepEqual(sheet.map((s) => [s.angle, s.take.id]), [["front_right/eye/medium", "r1"], ["left/eye/medium", "t1"]], "the newest take per position, in dial order");
  assert.deepEqual(angleSheet({ takes: [], recorded: [], status: {} }, catalog), []);
});

// -- the Shots board keeps its tiles ------------------------------------------------------------------------------------------

import { tileKey } from "../../openfield/web/js/ui/shots.js";
import { renderList } from "../../openfield/web/js/ui/dom.js";

/** Just enough of a parent for renderList: ordered children that carry a dataset and can be placed and removed. */
function boardParent() {
  return {
    children: [],
    insertBefore(el, ref) {
      const at = this.children.indexOf(el);
      if (at >= 0) this.children.splice(at, 1);
      this.children.splice(ref ? this.children.indexOf(ref) : this.children.length, 0, el);
      el.parent = this;
    },
  };
}
const tileEl = () => ({ dataset: {}, remove() { this.parent.children.splice(this.parent.children.indexOf(this), 1); } });

test("a tile's key is its board, its setup and its still: pending until the still lands", () => {
  const take = { id: "tk_board" };
  assert.equal(tileKey({ take, i: 3, shot: { file: "shots/3.png" } }), "tk_board:3:shots/3.png");
  assert.equal(tileKey({ take, i: 3 }), "tk_board:3:pending");
  assert.equal(tileKey({ take: null, i: 0 }), "undefined:0:pending", "a source with no board yet: nine tiles, each its own key");
  assert.notEqual(tileKey({ take: { id: "other" }, i: 3, shot: { file: "shots/3.png" } }), tileKey({ take, i: 3, shot: { file: "shots/3.png" } }));
});

test("pressing a setup rebuilds no tile; a new still replaces only its own", () => {
  const board = boardParent();
  const take = { id: "tk_board" };
  const stills = (n) => Array.from({ length: n }, (_, i) => ({ index: i + 1, file: `shots/${i}.png` }));
  const items = (n) => Array.from({ length: 9 }, (_, i) => ({ take, i, shot: stills(n)[i] }));
  let created = 0;
  const updated = [];
  const render = (n) => renderList(board, items(n), tileKey, () => { created += 1; return tileEl(); }, (el, item) => updated.push(item.i));

  render(3);
  const first = [...board.children];
  assert.deepEqual([first.length, created], [9, 9]);

  render(3); // a click, or a poll that brings the same takes again
  assert.deepEqual(board.children, first, "the same elements, in the same places");
  assert.deepEqual([created, updated.length], [9, 9], "nothing is built again; every tile is only asked to refresh");

  render(4); // the fourth still lands
  assert.equal(created, 10);
  assert.deepEqual(board.children.map((el, i) => el === first[i]), [true, true, true, false, true, true, true, true, true], "only the fourth tile is new");

  const other = Array.from({ length: 9 }, (_, i) => ({ take: { id: "tk_other" }, i, shot: stills(9)[i] }));
  renderList(board, other, tileKey, () => { created += 1; return tileEl(); }, () => {});
  assert.equal(created, 19, "another board is nine new tiles");
  assert.equal(board.children.length, 9);
});
