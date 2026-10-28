import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { POSTERS, cardTitle, onWall, proofFor } from "../../openfield/web/js/ui/lobby.js";
import { billing, takeCount } from "../../openfield/web/js/lib/billing.js";

const catalog = JSON.parse(readFileSync(new URL("./fixtures/catalog.json", import.meta.url), "utf8"));
const take = (id, kind, recipe = {}, extra = {}) => ({ id, kind, status: "succeeded", recipe, created_at: id, ...extra });

test("the wall hangs nineteen distinct posters, each with words, models and a proof rule", () => {
  assert.equal(POSTERS.length, 19);
  assert.equal(new Set(POSTERS.map((p) => p.id)).size, 19);
  for (const p of POSTERS) assert.ok(p.title && p.tagline && p.models.length && typeof p.proof === "function", p.id);
  const edits = POSTERS.filter((p) => ["face-swap", "relight", "outfit", "person-swap", "remove", "own-words"].includes(p.id));
  assert.ok(edits.every((p) => p.models.join() === "Qwen-Image 2.1"), "an edit is one Qwen-Image 2.1 run, as its receipts show");
});

test("a poster hangs when its feature's render held; a room's own poster (no flag) always hangs", () => {
  const reshoot = POSTERS.find((p) => p.id === "reshoot");
  assert.equal(onWall(reshoot, { moves: catalog, recorded: [] }), true, "Re-shoot leads into its room, recorded or not");
  const state = { moves: catalog, recorded: [take("tk_1", "reshoot", { face_only: false })] };
  assert.equal(onWall(reshoot, state), true);
  const bullet = POSTERS.find((p) => p.id === "bullet-time");
  assert.equal(onWall(bullet, state), Boolean(catalog.moves.find((m) => m.id === "bullet_time").validated),
    "a poster whose render has not held waits off the wall, with no words about it");
});

test("a poster's proof is the showcase reel's choice first, then the newest", () => {
  const relight = POSTERS.find((p) => p.id === "relight");
  const a = take("tk_a", "edit", { preset: "relight" });
  const b = take("tk_b", "edit", { preset: "relight" });
  assert.equal(proofFor(relight, { recorded: [a, b] }).id, "tk_b", "newest without a reel");
  assert.equal(proofFor(relight, { recorded: [a, b], status: { hero_reel: ["tk_a"] } }).id, "tk_a", "the reel wins");
  assert.equal(proofFor(relight, { recorded: [take("tk_c", "edit", { preset: "outfit" })] }), null);
});

test("every stub keeps one order, and shows only what the take recorded", () => {
  const shot = take("tk_1", "direct", { seed: 7, quality: "draft" }, { seconds: 5, recipe_hash: "abcdef0123456789", audit: { result: "pass" } });
  assert.deepEqual(billing(shot, catalog).map(([label]) => label), ["Seed", "Steps", "Length", "Recipe", "Audit"]);
  assert.equal(billing(shot, catalog)[1][1], String(catalog.quality.find((q) => q.id === "draft").steps));
  assert.equal(billing(shot, catalog)[3][1], "abcdef01");
  const photo = take("tk_2", "direct", { seed: 7, source_sha256: "x".repeat(64) }, { seconds: 5 });
  assert.ok(!billing(photo, catalog).some(([label]) => label === "Steps"), "a take from a person's photo may have rendered no still");
  const bridge = take("tk_3", "transition", { seed: 3 }, { seconds: 3 });
  assert.ok(!billing(bridge, catalog).some(([label]) => label === "Steps"), "a bridge renders no stills");
  assert.deepEqual(billing(take("tk_4", "reshoot"), catalog), [], "nothing recorded, nothing shown");
});

test("the take count counts each finished take once and leaves out cast portraits and replays", () => {
  const rec = [take("tk_1", "direct"), take("tk_2", "edit"), take("tk_p", "portrait")];
  const own = [take("tk_1", "direct"), take("tk_9", "direct"), take("tk_r", "direct", {}, { replay_of: "tk_1" }), take("tk_f", "direct", {}, { status: "failed" })];
  assert.equal(takeCount({ recorded: rec, takes: own }), 3, "tk_1 and tk_2 recorded, tk_9 the backend's own");
  assert.equal(takeCount({ recorded: [], takes: [] }), 0);
});

test("a lobby card's title is the move or the edit and who is in it", () => {
  const state = { moves: catalog };
  assert.equal(cardTitle(take("tk_1", "direct", { rig: { movement: "dolly_in" }, cast_name: "Tomas" }), state), "Dolly in · Tomas");
  assert.equal(cardTitle(take("tk_2", "edit", { preset: "relight" }), state), "Relight");
  assert.equal(cardTitle(take("tk_3", "transition", {}), state), "Transition");
});

test("held motion stills the Lobby with one list, and the reveal never waits on a timer", () => {
  const css = readFileSync(new URL("../../openfield/web/css/lobby.css", import.meta.url), "utf8");
  const tokens = readFileSync(new URL("../../openfield/web/css/tokens.css", import.meta.url), "utf8");
  const reveal = readFileSync(new URL("../../openfield/web/js/ui/reveal.js", import.meta.url), "utf8");
  assert.ok(tokens.includes(":root.hold-still *,"), "Save-Data (no media query) collapses every animation and transition, as reduced motion does");
  assert.ok(!css.includes("prefers-reduced-motion"), "one list under :root.hold-still, which main.js sets for reduced motion and Save-Data alike");
  const held = css.slice(css.indexOf(":root.hold-still"));
  for (const stops of [".armed > *", ".armed-self", ".lobby-headline", ".marquee-row .letter", ".card-row.drifting"]) assert.ok(held.includes(stops), stops);
  assert.ok(!reveal.includes("setTimeout"), "an item rises when it comes into view, never because time ran out");
});
