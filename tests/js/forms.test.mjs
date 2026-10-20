import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import * as reshoot from "../../openfield/web/js/lib/reshoot.js";
import * as cast from "../../openfield/web/js/lib/cast.js";
import { decodeRecipeLink, linkFromHash, remix } from "../../openfield/web/js/lib/remix.js";
import { validate as validateDirect } from "../../openfield/web/js/lib/direct.js";

const read = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));
const catalog = read("catalog.json");
const link = read("recipe_link.json");
const file = (name, megabytes = 1) => ({ name, size: Math.round(megabytes * 1024 * 1024) });

// -- Re-shoot ------------------------------------------------------------------------------------

test("a re-shoot needs a clip, a reference or character, and a description", () => {
  const fields = (patch) => reshoot.validate({ ...reshoot.initialReshoot(), ...patch }).map((p) => p.field);
  assert.deepEqual(fields({}), ["clip", "reference", "prompt"]);
  const ready = { clip: file("walk.mp4", 20), referenceFile: file("mara.png"), prompt: "a woman with short dark hair" };
  assert.deepEqual(fields(ready), []);
  assert.deepEqual(fields({ ...ready, referenceFile: null, castId: "ca_12345678" }), []);
  assert.deepEqual(fields({ ...ready, clip: file("walk.gif") }), ["clip"]);
  assert.deepEqual(fields({ ...ready, clip: file("walk.mp4", 201) }), ["clip"]);
  assert.deepEqual(fields({ ...ready, referenceFile: file("mara.bmp") }), ["reference"]);
  assert.deepEqual(fields({ ...ready, referenceFile: file("mara.png", 21) }), ["reference"]);
  assert.deepEqual(fields({ ...ready, prompt: "ab" }), ["prompt"]);
  assert.deepEqual(fields({ ...ready, prompt: "x".repeat(401) }), ["prompt"]);
  assert.deepEqual(fields({ ...ready, background: "x".repeat(401), motion: "y".repeat(401) }), ["background", "motion"]);
  assert.deepEqual(fields({ ...ready, seed: "-3" }), ["seed"]);
  assert.deepEqual(fields({ ...ready, clip: file("WALK.MOV") }), [], "extensions are case-insensitive");
});

class FakeForm {
  constructor() { this.entries = []; }
  append(key, value) { this.entries.push([key, value]); }
  get(key) { return this.entries.find(([k]) => k === key)?.[1]; }
  keys() { return this.entries.map(([k]) => k); }
}

test("the re-shoot form carries exactly what was filled in", () => {
  const clip = file("walk.mp4");
  const full = reshoot.toForm(
    { ...reshoot.initialReshoot(), clip, referenceFile: file("m.png"), prompt: " a courier ", background: " a street ", motion: "walks", seed: "9" },
    FakeForm,
  );
  assert.deepEqual(full.keys().sort(), ["background", "motion", "prompt", "reference", "seed", "source"]);
  assert.equal(full.get("prompt"), "a courier");
  assert.equal(full.get("source"), clip);
  const viaCast = reshoot.toForm({ ...reshoot.initialReshoot(), clip, castId: "ca_1", refIndex: 2, prompt: "a courier" }, FakeForm);
  assert.deepEqual(viaCast.keys().sort(), ["cast_id", "prompt", "ref_index", "source"]);
  assert.equal(viaCast.get("ref_index"), "2");
});

// -- Cast ----------------------------------------------------------------------------------------

test("saving references makes the person choose a consent option", () => {
  const fields = (patch) => cast.validate({ ...cast.initialCast(), ...patch }).map((p) => p.field);
  assert.equal(cast.initialCast().consent, null, "no default consent");
  assert.deepEqual(fields({}), ["name", "consent", "files"]);
  const ready = { name: "Mara", consent: "fictional", files: [file("a.png")] };
  assert.deepEqual(fields(ready), []);
  assert.deepEqual(fields({ ...ready, consent: "whatever" }), ["consent"]);
  assert.deepEqual(fields({ ...ready, name: "x".repeat(41) }), ["name"]);
  assert.deepEqual(fields({ ...ready, kind: "pet" }), ["kind"]);
  assert.deepEqual(fields({ ...ready, files: Array.from({ length: 9 }, (_, i) => file(`${i}.png`)) }), ["files"]);
  assert.deepEqual(fields({ ...ready, files: [file("a.tiff")] }), ["files"]);
  assert.deepEqual(fields({ ...ready, files: [file("a.png", 13)] }), ["files"]);
  assert.deepEqual(Object.keys(cast.CONSENT), ["mine", "consented", "fictional"]);
  const form = cast.toForm(ready, FakeForm);
  assert.deepEqual(form.keys(), ["name", "kind", "consent", "files"]);
});

test("generating a character validates the description and builds a small body", () => {
  const fields = (patch) => cast.validateCharacter({ ...cast.initialCharacter(), ...patch }).map((p) => p.field);
  assert.deepEqual(fields({}), ["description"]);
  assert.deepEqual(fields({ description: "a courier in a yellow raincoat" }), []);
  assert.deepEqual(fields({ description: "a courier", count: 0 }), ["count"]);
  assert.deepEqual(fields({ description: "a courier", count: 5 }), ["count"]);
  assert.deepEqual(fields({ description: "x".repeat(401) }), ["description"]);
  assert.deepEqual(fields({ description: "a courier", seed: "abc" }), ["seed"]);
  assert.deepEqual(cast.characterBody({ description: " a courier ", count: 2, seed: "" }), { description: "a courier", count: 2 });
  assert.deepEqual(cast.characterBody({ description: "a courier", count: 2, seed: "11" }), { description: "a courier", count: 2, seed: 11 });
});

test("candidates are only offered for a finished generated-character take", () => {
  const done = { status: "succeeded", candidates: ["candidates/01.png", "candidates/02.png"] };
  assert.deepEqual(cast.candidatesOf(done), [
    { number: 1, file: "candidates/01.png" }, { number: 2, file: "candidates/02.png" }]);
  assert.deepEqual(cast.candidatesOf({ ...done, status: "running" }), []);
  assert.deepEqual(cast.candidatesOf(null), []);
  assert.deepEqual(cast.candidatesOf({ status: "succeeded" }), []);
  assert.equal(cast.suggestName("a woman in her late twenties"), "Woman");
  assert.equal(cast.suggestName("An elderly man with a beard"), "Elderly");
  assert.equal(cast.suggestName("   "), "Character");
});

// -- Remix ---------------------------------------------------------------------------------------

test("a recipe link made by the server decodes in the browser", async () => {
  const recipe = await decodeRecipeLink(link.link);
  assert.deepEqual(recipe, link.recipe);
  await assert.rejects(decodeRecipeLink("not-a-link"));
  const arrayLink = Buffer.from(JSON.stringify([1, 2])).toString("base64url");
  await assert.rejects(decodeRecipeLink(arrayLink));
  assert.equal(linkFromHash("#recipe=abc_DEF-123"), "abc_DEF-123");
  assert.equal(linkFromHash("recipe=abc"), "abc");
  assert.equal(linkFromHash("#other=abc"), null);
  assert.equal(linkFromHash("#recipe=a b"), null);
  assert.equal(linkFromHash(undefined), null);
});

test("remixing a direct take fills the form and says what must be supplied again", async () => {
  const recipe = await decodeRecipeLink(link.link);
  const result = remix({ verified: null, recipe }, catalog);
  assert.equal(result.form, "direct");
  assert.equal(result.state.subject, "A lighthouse at dusk");
  assert.equal(result.state.quick, true);
  assert.equal(result.state.orientation, "portrait");
  assert.equal(result.state.rig.movement, "orbit_90");
  assert.deepEqual(validateDirect(result.state, catalog), []);
  assert.deepEqual(result.needs, ['the character "Mara" (pick it again in Cast)']);
  assert.match(result.notice, /nothing here is checked or signed/);
  assert.match(remix({ verified: true, recipe }, catalog).notice, /checksum matches/);
  assert.match(remix({ verified: false, recipe }, catalog).notice, /checksum does not match/);
});

test("remixing other kinds of receipt, and the ones that cannot be remixed", () => {
  const reshootResult = remix({ verified: true, recipe: { kind: "reshoot", inputs: {
    prompt: "a courier", background: "a street", motion: "walks", seed: 5, reference_name: "Mara" } } }, catalog);
  assert.equal(reshootResult.form, "reshoot");
  assert.deepEqual(reshootResult.state, { prompt: "a courier", background: "a street", motion: "walks", seed: 5 });
  assert.deepEqual(reshootResult.needs, ["your source clip", 'a reference image (it was "Mara")']);

  const portrait = remix({ verified: true, recipe: { kind: "portrait", inputs: { description: "a sailor", count: 2, seed: 9 } } }, catalog);
  assert.deepEqual([portrait.form, portrait.state, portrait.needs], ["portrait", { description: "a sailor", count: 2, seed: 9 }, []]);

  const exported = remix({ verified: true, recipe: { kind: "export", inputs: {} } }, catalog);
  assert.equal(exported.form, null);
  assert.match(exported.notice, /made from its source take/);
  assert.match(remix({ verified: true, recipe: { kind: "mystery" } }, catalog).notice, /not one OpenField can rebuild/);
  assert.equal(remix({}, catalog).form, null);
});
