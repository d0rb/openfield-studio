import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { remix } from "../../openfield/web/js/lib/remix.js";
import { fromRecipe, matchesRecording, onePass } from "../../openfield/web/js/lib/direct.js";
import { boardFor, openingBoard } from "../../openfield/web/js/ui/shots.js";

const read = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));
const catalog = read("catalog.json");
const cases = read("remix_receipts.json"); // what the server's receipt import answers for each kind of Direct take, beside its recording
const byName = (name) => cases.find((c) => c.name === name);
// quick mode on a one-still move changes only the fingerprint, and the receipt's mode cannot show it: its recording can
const oneStillQuick = (recipe) => Boolean(recipe.prompt_only) && catalog.moves.find((m) => m.id === recipe.rig?.movement)?.mode !== "keyframed";
// the takes bundled for Replay, or another folder of them (a checkout with the media) named by OPENFIELD_BUNDLED_TAKES
const BUNDLED = process.env.OPENFIELD_BUNDLED_TAKES || fileURLToPath(new URL("../../openfield/web/showcase/takes/", import.meta.url));
const bundled = existsSync(BUNDLED)
  ? readdirSync(BUNDLED).filter((id) => existsSync(join(BUNDLED, id, "take.json")) && existsSync(join(BUNDLED, id, "receipt.json")))
  : [];

// -- Remix: a receipt or a recipe link back into the form ----------------------------------------------------------

test("a receipt or a recipe link of every kind of Direct take loads into a form that matches its recording", () => {
  assert.ok(cases.length >= 13);
  const recordings = cases.map((c) => c.recorded);
  for (const { name, imported, recorded } of cases) {
    const result = remix(imported, catalog, recordings);
    assert.equal(result.form, "direct", name);
    const castName = recorded.recipe.cast_name ?? null; // a Cast comes back by picking it again, then matches by name
    assert.equal(matchesRecording(result.state, recorded, castName, catalog), true, name);
    const alone = remix(imported, catalog).state; // a receipt of a take that is no recording here
    assert.equal(matchesRecording(alone, recorded, castName, catalog), !oneStillQuick(recorded.recipe), `${name}, with no recordings`);
  }
});

test("a remix turns quick mode on only for a keyframed move recorded quick, or as the recording it names says", () => {
  const quick = (name, cat = catalog, recorded = []) => remix(byName(name).imported, cat, recorded).state.quick;
  assert.equal(quick("static"), false, "a one-still move is prompt_only by nature, not quick");
  assert.equal(quick("orbit_90"), false);
  assert.equal(quick("experimental"), false);
  assert.equal(quick("transformation"), false);
  assert.equal(quick("dolly_in"), false);
  assert.equal(quick("dolly_in_quick"), true);
  assert.equal(quick("dolly_in_quick", null), false, "with no catalog yet the move is not known to be keyframed");
  assert.equal(quick("static_quick"), false);
  assert.equal(quick("static_quick", catalog, [byName("static_quick").recorded]), true);
  assert.equal(quick("dolly_in_quick", catalog, [byName("dolly_in").recorded]), true, "another recording says nothing about this one");
});

test("a remix brings back the spoken line, its delivery and language, and what happens", () => {
  const talking = remix(byName("spoken_line").imported, catalog).state;
  assert.deepEqual([talking.line, talking.delivery, talking.language], ["We leave at first light.", "whisper", "English"]);
  const calm = remix(byName("spoken_line_no_language").imported, catalog).state;
  assert.deepEqual([calm.line, calm.delivery, calm.language], ["Come home.", "calm", ""]);
  const acted = remix(byName("talking_acted_draft").imported, catalog).state;
  assert.deepEqual([acted.line, acted.action, acted.quality], ["Ready?", "She lifts the lantern", "draft"]);
  const silent = remix(byName("static").imported, catalog);
  assert.deepEqual([silent.state.line, silent.state.action], ["", ""]);
  assert.deepEqual(silent.needs, ['the character "Oskar" (pick it again in Cast)']);
});

// made by a construction the catalog has since replaced: r11-mv-arc-right was a one-still mirror before arc right became
// keyframed (Oct 26), so its receipt alone now reads as quick mode and only its recording matches it
const LEGACY = new Set(["tk_20261025_133624_8320"]);

test("every bundled Direct receipt loads into a form that matches its recording", { skip: !bundled.length && "no bundled takes in this checkout" }, () => {
  const takes = bundled.map((id) => ({ id, take: JSON.parse(readFileSync(join(BUNDLED, id, "take.json"), "utf8")) }))
    .filter(({ take }) => take.kind === "direct" && take.status === "succeeded");
  const recordings = takes.map(({ take }) => take); // as Replay lists them: id, kind, recipe and recipe_hash
  let matched = 0;
  for (const { id, take } of takes) {
    const receipt = JSON.parse(readFileSync(join(BUNDLED, id, "receipt.json"), "utf8"));
    const imported = { verified: true, recipe: { kind: receipt.take?.kind, inputs: receipt.inputs } };
    const { state } = remix(imported, catalog, recordings);
    // never matched by design: a sourced hero needs the image again; a segmented take is not its one-pass twin
    if (take.recipe.source_sha256 || Boolean(take.recipe.single_pass) !== onePass(state, catalog)) continue;
    const castName = take.recipe.cast_name ?? null;
    assert.equal(matchesRecording(state, take, castName, catalog), true, id);
    if (!oneStillQuick(take.recipe) && !LEGACY.has(id)) assert.equal(matchesRecording(remix(imported, catalog).state, take, castName, catalog), true, `${id}, with no recordings`);
    matched += 1;
  }
  assert.ok(matched > 0);
});

// -- A spoken line, tidied as the server keeps it ------------------------------------------------------------------

test("a spoken line typed with quotes or extra spaces matches its recording", () => {
  const { recorded } = byName("spoken_line"); // sent as '  "We leave at   first light."  '
  const form = fromRecipe(recorded.recipe, catalog);
  for (const line of ['"We leave at first light."', "  We leave at\n first light.  ", "“We leave at first light.”", '"“We leave at first light.”"']) {
    assert.equal(matchesRecording({ ...form, line }, recorded, null, catalog), true, line);
  }
  assert.equal(matchesRecording({ ...form, line: "We leave at first light" }, recorded, null, catalog), false, "the words themselves still count");
  assert.equal(matchesRecording({ ...form, language: "  English " }, recorded, null, catalog), true);
});

// -- Shots: a bundled board --------------------------------------------------------------------------------------------

test("a bundled board is a recorded one, in the hosted copy and in Replay, and so is a replay of it", () => {
  const take = { id: "tk_20261023_100000_aaaa", kind: "direct", status: "succeeded", recipe: { subject: "Noor on Mars" } };
  const board = { id: "tk_20261023_110000_bbbb", kind: "shots", status: "succeeded", recipe: { kind: "shots", take: take.id }, outputs: [] };
  const hosted = boardFor({ takes: [board, take], recorded: [board, take] }, take.id); // the hosted copy lists recordings as takes too
  assert.equal(hosted.id, board.id);
  assert.equal(hosted.recording, true, "so Show the recorded board is offered");
  const replayed = { ...board, id: "tk_replay_1_bbbb", replay: true, replay_of: board.id };
  const again = boardFor({ takes: [replayed, board, take], recorded: [board, take] }, take.id);
  assert.equal(again.recording, true);
  assert.equal(again.replay_of ?? again.id, board.id, "showing it again replays the recording");
  const mine = boardFor({ takes: [{ ...board, id: "tk_20261023_120000_cccc" }, take], recorded: [] }, take.id);
  assert.ok(mine && !mine.recording, "a board made here is not a recording");
  assert.equal(boardFor({ takes: [take], recorded: [] }, take.id), null);
});

test("the Shots room opens on a real board even when the board's start take is not in this copy", () => {
  const start = { id: "tk_20261023_100000_aaaa", kind: "direct", status: "succeeded", recipe: {} };
  const owned = { id: "tk_20261023_110000_bbbb", kind: "shots", status: "succeeded", recipe: { take: start.id }, shots: [{ index: 1 }] };
  assert.deepEqual(openingBoard({ takes: [owned, start], recorded: [] }, [start]), { source: start.id, pinned: null }, "a start take that owns a board");
  // the showcase's boards were made from takes it does not bundle: open the reel's board, else the newest
  const older = { id: "tk_20261022_230000_cccc", kind: "shots", status: "succeeded", recipe: { take: "tk_missing_1" }, shots: [{ index: 1 }], created_at: "2026-10-22T23:00:00Z" };
  const newer = { id: "tk_20261022_235000_dddd", kind: "shots", status: "succeeded", recipe: { take: "tk_missing_2" }, shots: [{ index: 1 }], created_at: "2026-10-22T23:50:00Z" };
  const state = { takes: [start], recorded: [older, newer] };
  assert.deepEqual(openingBoard(state, [start]), { source: "tk_missing_2", pinned: newer.id }, "the newest board");
  assert.deepEqual(openingBoard({ ...state, status: { hero_reel: [older.id] } }, [start]), { source: "tk_missing_1", pinned: older.id }, "the reel's choice first");
  assert.deepEqual(openingBoard({ takes: [start], recorded: [] }, [start]), { source: start.id, pinned: null }, "no board anywhere: the first start take");
  assert.equal(openingBoard({ takes: [], recorded: [] }, []), null);
});
