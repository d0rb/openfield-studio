import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

import { actionMax, actionNote, formRecipe, fromRecipe, initialDirect, matchesRecording, onePass, requestBody, validate } from "../../openfield/web/js/lib/direct.js";
import { dubRequest } from "../../openfield/web/js/lib/edit.js";

const catalog = JSON.parse(readFileSync(new URL("./fixtures/catalog.json", import.meta.url), "utf8"));
const BUNDLED = fileURLToPath(new URL("../../openfield/web/showcase/takes/", import.meta.url));
const base = { ...initialDirect(catalog), subject: "A samurai in a bamboo grove at dawn", seed: "7" };
const KATANA = "He draws the katana and raises the blade.";

test("what happens is sent only when said, tidied as the server keeps it", () => {
  assert.equal(initialDirect(catalog).action, "");
  assert.ok(!("action" in requestBody(base)), "an empty field sends no key");
  assert.ok(!("action" in requestBody({ ...base, action: "  \n " })), "blank is no action");
  assert.equal(requestBody({ ...base, action: "  He draws   the katana\nand raises the blade. " }).action, KATANA);
});

test("what happens takes 3 to the catalog's limit of characters, or nothing", () => {
  const fields = (action, cat = catalog) => validate({ ...base, action }, cat).map((p) => p.field);
  assert.deepEqual(fields(""), []);
  assert.deepEqual(fields("   "), []);
  assert.deepEqual(fields("go"), ["action"]);
  assert.deepEqual(fields(" g  o "), [], "three characters once tidied");
  assert.deepEqual(fields("x".repeat(300)), []);
  assert.deepEqual(fields("x".repeat(301)), ["action"]);
  assert.deepEqual(fields("x".repeat(301), { ...catalog, action_max: 400 }), [], "the catalog's limit wins");
  assert.match(validate({ ...base, action: "go" }, catalog)[0].message, /3 to 300 characters, or leave it empty/);
  assert.equal(actionMax(null), 300);
  assert.equal(actionMax({ action_max: 280 }), 280);
  assert.equal(actionMax({ direct: { action_max: 250 }, action_max: 280 }), 250);
});

test("a recipe carries what happens only when set: older recordings match an empty field, and an action is part of the match", () => {
  const silent = { kind: "direct", recipe: { subject: base.subject, rig: base.rig, seed: 7, orientation: "landscape", cast_refs: [] } };
  assert.ok(!("action" in formRecipe(base)), "an empty field adds nothing to the recipe");
  assert.equal(matchesRecording(base, silent), true, "a recording made before actions existed still matches");
  assert.equal(matchesRecording({ ...base, action: " \n" }, silent), true);
  assert.equal(matchesRecording({ ...base, action: KATANA }, silent), false, "an action makes a different shot");
  const acted = { kind: "direct", recipe: { ...silent.recipe, action: KATANA } };
  assert.equal(formRecipe({ ...base, action: " He draws the katana\n  and raises the blade. " }).action, KATANA);
  assert.equal(matchesRecording({ ...base, action: " He draws the katana\n  and raises the blade. " }, acted), true, "after the same tidying");
  assert.equal(matchesRecording(base, acted), false, "an empty field never plays a recording with an action");
  assert.equal(matchesRecording({ ...base, action: "He sheathes the katana." }, acted), false);
});

test("a recording's action comes back into the form (so Recreate is offered), and a dub of it keeps the action", () => {
  const acted = { kind: "direct", recipe: { subject: base.subject, rig: base.rig, seed: 7, orientation: "landscape", cast_refs: [], action: KATANA } };
  const back = fromRecipe(acted.recipe, catalog);
  assert.equal(back.action, KATANA);
  assert.equal(matchesRecording(back, acted, null, catalog), true);
  assert.equal(fromRecipe({ subject: "A harbour", rig: {} }, catalog).action, "");
  const dub = (recipe) => dubRequest({ ...recipe, line: "We ride at dawn." }, { line: "Partimos al alba.", language: "Spanish" });
  assert.equal(dub(acted.recipe).action, KATANA);
  assert.ok(!("action" in dub({ ...acted.recipe, action: undefined })));
});

test("the plan warns quietly when an action meets a keyframed move with quick mode off", () => {
  const two = catalog.moves.find((m) => m.mode === "keyframed" && m.anchors === 2);
  const more = catalog.moves.find((m) => m.mode === "keyframed" && m.anchors > 2);
  const one = catalog.moves.find((m) => m.mode !== "keyframed");
  const form = (move, patch = {}) => ({ ...base, action: KATANA, rig: { ...base.rig, movement: move.id }, ...patch });
  assert.equal(actionNote(form(two), catalog), "The stills share one moment. The action may barely move.");
  assert.equal(actionNote(form(more), catalog), "The stills share one moment. The action may barely move.");
  assert.equal(actionNote(form(two, { quick: true }), catalog), null, "quick mode gives the action room");
  assert.equal(actionNote(form(one), catalog), null, "so does a one-still move");
  assert.equal(actionNote(form(two, { action: "  " }), catalog), null, "no action, no note");
  assert.equal(actionNote(form(two), null), null, "no catalog yet");
});

test("every bundled recording still loads into a form that matches it, What happens empty", { skip: !existsSync(BUNDLED) && "no bundled takes in this checkout" }, () => {
  const takes = readdirSync(BUNDLED).map((id) => join(BUNDLED, id, "take.json")).filter(existsSync).map((file) => JSON.parse(readFileSync(file, "utf8")));
  const direct = takes.filter((t) => t.kind === "direct" && t.status === "succeeded");
  assert.ok(direct.length > 0);
  let matched = 0;
  for (const take of direct) {
    const form = fromRecipe(take.recipe, catalog);
    assert.equal(form.action, take.recipe.action ?? "", take.id);
    // never matched by design: a sourced hero needs the image again; a segmented take is not its one-pass twin
    if (take.recipe.source_sha256 || Boolean(take.recipe.single_pass) !== onePass(form, catalog)) continue;
    assert.equal(matchesRecording(form, take, take.recipe.cast_name ?? null, catalog), true, take.id);
    matched += 1;
  }
  assert.ok(matched > 0);
});
