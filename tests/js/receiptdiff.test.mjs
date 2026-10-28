import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { compareCandidates, receiptRows, wordDiff } from "../../openfield/web/js/lib/receiptdiff.js";

const RECEIPT_FIXTURE = {
  tk_20261024_182654_5553: "receipt-truck-right.json",
  tk_20261024_182749_b6a5: "receipt-pedestal-up.json",
};
const receipt = (id) => JSON.parse(readFileSync(new URL(`./fixtures/${RECEIPT_FIXTURE[id]}`, import.meta.url), "utf8"));
const catalog = JSON.parse(readFileSync(new URL("./fixtures/catalog.json", import.meta.url), "utf8"));

test("two takes of one subject differ in the move and keep the rest", () => {
  const rows = receiptRows(receipt("tk_20261024_182654_5553"), receipt("tk_20261024_182749_b6a5"), catalog);
  const row = (key) => rows.find((r) => r.key === key);
  assert.equal(row("move").same, false);
  assert.match(row("move").a, /truck/i);
  assert.match(row("move").b, /pedestal/i);
  for (const key of ["subject", "seed", "quality", "cast"]) assert.equal(row(key).same, true, key);
  assert.equal(row("models").same, true, "the same model files");
  assert.ok(row("models").shared > 0);
  assert.equal(row("seed").a, "620");
  assert.ok(rows.every((r) => r.label && "a" in r && "b" in r), "every row names itself and both sides");
});

test("a row neither receipt has is left out, and one side missing shows as a difference", () => {
  const a = { take: { kind: "direct" }, inputs: { seed: 7, rig: { movement: "static", effect: "rain" } } };
  const b = { take: { kind: "direct" }, inputs: { seed: 7, rig: { movement: "static", effect: "none" } } };
  const rows = receiptRows(a, b, catalog);
  assert.equal(rows.find((r) => r.key === "line"), undefined);
  const effect = rows.find((r) => r.key === "effect");
  assert.equal(effect.same, false);
  assert.equal(effect.b, null, "no effect is shown as none");
  assert.equal(rows.find((r) => r.key === "seed").same, true);
});

test("GPU time and cost: a receipt with no timings reads as nothing on its side, and two such add no rows", () => {
  const timed = { take: { kind: "direct" }, backend: { kind: "pod", timings: { total_s: 217 } } };
  for (const bare of [{ take: { kind: "direct" } }, { take: { kind: "direct" }, backend: { kind: "pod" } }, { take: { kind: "direct" }, backend: { timings: { total_s: 0 } } }]) {
    const rows = receiptRows(timed, bare);
    const gpu = rows.find((r) => r.key === "gpu");
    const cost = rows.find((r) => r.key === "cost");
    assert.deepEqual([gpu.a, gpu.b, gpu.same], ["217 s", null, false], JSON.stringify(bare));
    assert.match(cost.a, /¢$/);
    assert.equal(cost.b, null, "the Compare table writes – for it");
    assert.equal(receiptRows(bare, timed).find((r) => r.key === "gpu").a, null, "either side");
    assert.deepEqual(receiptRows(bare, bare).filter((r) => ["gpu", "cost"].includes(r.key)), [], "neither side has one: no row");
  }
});

test("model files compare as sets and name what only one side used", () => {
  const a = { models: [{ file: "ltx.safetensors" }, { file: "qwen.safetensors" }] };
  const b = { models: [{ file: "qwen.safetensors" }, { file: "wan.safetensors" }] };
  const row = receiptRows(a, b).find((r) => r.key === "models");
  assert.deepEqual([row.same, row.onlyA, row.onlyB, row.shared], [false, ["ltx.safetensors"], ["wan.safetensors"], 1]);
});

test("words: what changed is marked on each side, case and trailing commas aside", () => {
  const d = wordDiff("Mara stands on the pier, rain falling", "mara stands on the roof, snow falling");
  assert.deepEqual(d.a, [{ text: "Mara stands on the", op: "same" }, { text: "pier, rain", op: "gone" }, { text: "falling", op: "same" }]);
  assert.deepEqual(d.b, [{ text: "mara stands on the", op: "same" }, { text: "roof, snow", op: "new" }, { text: "falling", op: "same" }]);
  assert.deepEqual(wordDiff("", "new words"), { a: [], b: [{ text: "new words", op: "new" }] });
  const long = Array.from({ length: 500 }, (_, i) => `w${i}`).join(" ");
  assert.equal(wordDiff(long, `${long} more`).b.length, 1, "a very long text is compared whole");
});

test("the takes worth comparing come first: same subject, then cast, then move", () => {
  const take = { id: "a", status: "succeeded", recipe: { subject: "Mara on the pier", cast_name: "Mara", rig: { movement: "static" } } };
  const takes = [
    take,
    { id: "far", status: "succeeded", created_at: "2026-10-25", recipe: { subject: "A cat", rig: { movement: "dolly_in" } } },
    { id: "move", status: "succeeded", created_at: "2026-10-24", recipe: { subject: "A dog", rig: { movement: "static" } } },
    { id: "cast", status: "succeeded", created_at: "2026-10-20", recipe: { subject: "Mara in a cafe", cast_name: "Mara", rig: { movement: "dolly_in" } } },
    { id: "same", status: "succeeded", created_at: "2026-10-19", recipe: { subject: " mara on the pier", cast_name: "Mara", rig: { movement: "orbit_90" } } },
    { id: "replay", replay_of: "same", status: "succeeded", recipe: {} },
    { id: "failed", status: "failed", recipe: { subject: "Mara on the pier" } },
  ];
  assert.deepEqual(compareCandidates(take, takes).map((t) => t.id), ["same", "cast", "move", "far"]);
});
