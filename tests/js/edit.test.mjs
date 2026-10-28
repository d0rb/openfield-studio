import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { dubIn, dubProblem, dubRequest, editPreset, editProblem, editRequest, heroStill, recordedDubs, recordedEdit } from "../../openfield/web/js/lib/edit.js";
import { stageStrip } from "../../openfield/web/js/lib/stages.js";
import { createController, initialState } from "../../openfield/web/js/controller.js";
import { createStore } from "../../openfield/web/js/lib/store.js";

const catalog = JSON.parse(readFileSync(new URL("./fixtures/catalog.json", import.meta.url), "utf8"));

// -- Edit with words ---------------------------------------------------------------------------------

test("edit presets come from the catalog, each saying whether a real render checked it", () => {
  assert.deepEqual(catalog.edits.presets.map((p) => p.id), ["face_swap", "character_swap", "remove", "outfit", "relight", "custom"]);
  assert.ok(catalog.edits.presets.every((p) => typeof p.tested === "boolean"));
  assert.equal(editPreset(catalog, "outfit").label, "Change the outfit");
  assert.equal(editPreset(catalog, "outfit").tested, true, "the outfit edit was rendered and checked on Oct 23");
  assert.equal(editPreset(catalog, "nonsense"), null);
  assert.equal(editPreset(null, "outfit"), null);
});

test("a swap needs a character from Cast; the other edits need words, and Relight a light or words", () => {
  const problem = (form) => editProblem(form, catalog);
  assert.equal(problem({ preset: "face_swap" }), "Pick a character from Cast.");
  assert.equal(problem({ preset: "character_swap", castId: "" }), "Pick a character from Cast.");
  assert.equal(problem({ preset: "face_swap", castId: "ca_1" }), null);
  assert.equal(problem({ preset: "remove", detail: "   " }), "Say what to change.");
  assert.equal(problem({ preset: "remove", detail: "the lamp post" }), null);
  assert.equal(problem({ preset: "relight", light: "golden" }), null, "a light from the picker is enough");
  assert.equal(problem({ preset: "relight", light: null, detail: "" }), "Say what to change.");
  assert.equal(problem({ preset: "relight", light: null, detail: "one candle" }), null);
  assert.equal(problem({ preset: "nonsense" }), "Pick an edit.");
});

test("the edit request carries only what its preset uses", () => {
  const body = (form) => editRequest(form, catalog);
  assert.deepEqual(body({ preset: "outfit", detail: "  a red   raincoat ", take: "tk_a", still: null, castId: "ca_1", seed: "" }),
    { preset: "outfit", detail: "a red raincoat", take: "tk_a" });
  assert.deepEqual(body({ preset: "face_swap", detail: "ignored", castId: "ca_1", take: "tk_a" }), { preset: "face_swap", take: "tk_a", cast_id: "ca_1" });
  assert.deepEqual(body({ preset: "relight", light: "golden", take: "tk_a" }), { preset: "relight", detail: "golden", take: "tk_a" },
    "the server turns a light's id into its phrase");
  assert.deepEqual(body({ preset: "relight", light: "golden", detail: "one candle", take: "tk_a" }), { preset: "relight", detail: "one candle", take: "tk_a" },
    "the person's own words win over the picker");
  assert.deepEqual(body({ preset: "custom", detail: "make it snow", take: "tk_b", still: "runs/03_shot_3/a.png", seed: "7" }),
    { preset: "custom", detail: "make it snow", take: "tk_b", still: "runs/03_shot_3/a.png", seed: 7 });
});

test("Replay plays a recorded edit only of the same still with the same preset", () => {
  const rec = (id, recipe, kind = "edit") => ({ id, kind, recipe });
  const shelf = [
    rec("tk_e1", { take: "tk_src", preset: "outfit" }),
    rec("tk_e2", { take: "tk_src", preset: "relight", still: "runs/02/a.png" }),
    rec("tk_d1", { take: "tk_src", preset: "outfit" }, "direct"),
  ];
  assert.equal(recordedEdit(shelf, { id: "tk_src" }, "outfit")?.id, "tk_e1");
  assert.equal(recordedEdit(shelf, { id: "tk_replay_1", replay_of: "tk_src" }, "outfit")?.id, "tk_e1", "a replay stands for its recording");
  assert.equal(recordedEdit(shelf, { id: "tk_src" }, "remove"), null, "that preset was never recorded");
  assert.equal(recordedEdit(shelf, { id: "tk_src" }, "relight"), null, "the take's own still was not relit");
  assert.equal(recordedEdit(shelf, { id: "tk_src" }, "relight", "runs/02/a.png")?.id, "tk_e2");
  assert.equal(recordedEdit(shelf, { id: "tk_src" }, "outfit", "runs/02/a.png"), null, "an edit of the first still is not an edit of a setup");
  assert.equal(recordedEdit(undefined, { id: "tk_src" }, "outfit"), null);
});

test("an edit take's strip is its still before and after, the after with its identity check", () => {
  const take = { kind: "edit", edit: { preset: "outfit", before: "inputs/source.png", after: "runs/01_edit/a.png" },
    identity: { edit: { status: "pass", score: 0.61 } }, outputs: [{ role: "poster", file: "poster.png" }] };
  assert.deepEqual(stageStrip(take, null).map((s) => [s.name, s.file, s.report?.status ?? null]),
    [["Before", "inputs/source.png", null], ["After", "runs/01_edit/a.png", "pass"]]);
});

test("starting an edit follows its take and leaves the selection to the sheet that opens it", async () => {
  const store = createStore(initialState());
  const followed = [];
  const api = {
    startEdit: async () => ({ id: "tk_edit", kind: "edit", status: "queued", created_at: "2026-10-23T01:00:00Z" }),
    follow: (id) => { followed.push(id); return () => {}; },
  };
  const controller = createController({ api, store, setInterval: () => 1 });
  store.set({ selected: "tk_other" });
  assert.equal((await controller.startEdit(new FormData())).id, "tk_edit");
  assert.deepEqual(followed, ["tk_edit"]);
  assert.equal(store.get().takes[0].id, "tk_edit");
  assert.equal(store.get().selected, "tk_other");
});

// -- Dub ---------------------------------------------------------------------------------------------

test("a dub starts from the take's hero: before any angle, else the first approved still, else the poster", () => {
  const take = { outputs: [{ role: "poster", file: "poster.png" }] };
  const anchors = [{ index: 0, file: "runs/00_hero/a.png" }, { index: 1, file: "runs/01_anchor_1/b.png" }];
  assert.equal(heroStill(take, { inputs: { anchors } }), "runs/00_hero/a.png");
  assert.equal(heroStill(take, { inputs: { angle: { id: "left/eye/medium", source_file: "runs/00_hero/a.png" }, anchors: [{ index: 0, file: "runs/01_angle/c.png" }] } }),
    "runs/00_hero/a.png", "the same rig re-shoots the angle");
  assert.equal(heroStill(take, null), "poster.png");
});

test("a dub needs a language and a line in it", () => {
  assert.equal(dubProblem({ line: "Hola", language: " " }), "Name the language of the new line.");
  assert.equal(dubProblem({ line: "  ", language: "Spanish" }), "Write the line in that language.");
  assert.equal(dubProblem({ line: "Hola", language: "Spanish" }), null);
});

test("a dub's request is the take's own recipe speaking the new line, its stills approved", () => {
  const recipe = { kind: "direct", subject: "a lighthouse keeper on the pier", rig: { movement: "dolly_in", duration_seconds: 5 }, seed: 42, orientation: "portrait",
    audio: "gulls", line: "We leave at first light.", delivery: "calm", quality: "fine", cast_refs: ["abc"], cast_name: "Oskar" };
  assert.deepEqual(dubRequest(recipe, { line: "  Partimos   al amanecer. ", language: " Spanish " }), {
    subject: recipe.subject, rig: recipe.rig, orientation: "portrait", auto_approve: true, line: "Partimos al amanecer.", delivery: "calm",
    language: "Spanish", seed: 42, audio: "gulls", quality: "fine",
  });
  const quick = dubRequest({ subject: "a harbour at dawn", rig: { movement: "static" }, seed: 0, audio: null, line: "Hello", prompt_only: true }, { line: "Bonjour", language: "French" });
  assert.equal(quick.orientation, "landscape");
  assert.equal(quick.delivery, "natural");
  assert.equal(quick.seed, 0, "seed 0 is a seed");
  assert.equal(quick.prompt_only, true, "a quick take stays quick");
  assert.ok(!("audio" in quick) && !("quality" in quick) && !("cast_id" in quick));
});

test("Replay offers a recorded take of the same subject and rig in the chosen language, never the take itself", () => {
  const rig = { movement: "dolly_in", duration_seconds: 5, sensor: "modern_digital" };
  const take = { id: "tk_en", kind: "direct", recipe: { subject: "a lighthouse keeper", rig, line: "We leave at first light." } };
  const rec = (id, recipe) => ({ id, kind: "direct", recipe: { subject: "a lighthouse keeper", rig, line: "x", ...recipe } });
  const shelf = [
    rec("tk_en", { language: "English" }),
    rec("tk_es", { language: "Spanish", line: "Partimos al amanecer." }),
    rec("tk_fr", { language: "French", rig: { ...rig, movement: "orbit_360" } }),
    rec("tk_de", { language: "German", line: undefined }),
    rec("tk_plain", {}),
    { id: "tk_it", kind: "edit", recipe: { subject: "a lighthouse keeper", rig, line: "x", language: "Italian" } },
  ];
  const dubs = recordedDubs(shelf, take);
  assert.deepEqual(dubs.map((r) => r.id), ["tk_es"], "the same subject and rig, a line, a named language, not this take");
  assert.equal(dubIn(dubs, " spanish ")?.id, "tk_es", "case and spacing aside");
  assert.equal(dubIn(dubs, "French"), null);
  assert.deepEqual(recordedDubs(shelf, { ...take, id: "tk_replay_9", replay_of: "tk_es" }).map((r) => r.id), ["tk_en"], "a replay of a dub stands for that dub");
});
