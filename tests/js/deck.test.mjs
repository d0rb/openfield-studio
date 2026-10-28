import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { deckFilters, effectDeck, inFilter, marqueeCounts, moveDeck, reelAt, scrubTime, stepIn, trailerReel } from "../../openfield/web/js/lib/deck.js";
import { movePageUrl } from "../../openfield/web/js/lib/shareurls.js";

const catalog = JSON.parse(readFileSync(new URL("./fixtures/catalog.json", import.meta.url), "utf8"));
const validated = catalog.moves.filter((m) => m.validated);
// a preview list where every validated move but the last has a take with a loop
const previews = {
  takes: Object.fromEntries(validated.slice(0, -1).map((m) => [`tk_${m.id}`, { video: `v/${m.id}.mp4`, poster: `p/${m.id}.jpg` }])),
  moves: Object.fromEntries(validated.map((m) => [m.id, `tk_${m.id}`])),
  effects: {},
};

test("the move gallery shows only flagged moves whose take has a loop, in the rig's order", () => {
  const deck = moveDeck(catalog, previews);
  assert.deepEqual(deck.map((m) => m.id), validated.slice(0, -1).map((m) => m.id));
  assert.ok(deck.every((m) => m.takeId === `tk_${m.id}` && m.label && m.groupLabel));
  const unflagged = catalog.moves.find((m) => !m.validated);
  if (unflagged) {
    const forced = { ...previews, takes: { ...previews.takes, tk_x: { video: "x", poster: "x" } }, moves: { ...previews.moves, [unflagged.id]: "tk_x" } };
    assert.ok(!moveDeck(catalog, forced).some((m) => m.id === unflagged.id), "a move whose render has not held never plays, even with a take");
  }
  assert.deepEqual(moveDeck(catalog, null), []);
});

test("the filters count what they show: featured first, then all, then each group with a move", () => {
  const deck = moveDeck(catalog, previews);
  const filters = deckFilters(deck, catalog.groups);
  const all = filters.find((f) => f.id === "all");
  assert.equal(all.count, deck.length);
  const featured = filters.find((f) => f.id === "featured");
  if (featured) assert.equal(filters[0].id, "featured");
  for (const f of filters.filter((x) => !["all", "featured"].includes(x.id))) {
    assert.ok(f.count > 0, `${f.id} is listed only when it has a move`);
    assert.equal(deck.filter((m) => inFilter(m, f.id)).length, f.count);
  }
  assert.equal(filters.filter((x) => !["all", "featured"].includes(x.id)).reduce((n, f) => n + f.count, 0), deck.length, "every move sits in one group");
});

test("the effects rail shows only flagged effects with a loop, never the empty choice", () => {
  const tested = catalog.effects.filter((e) => e.tested && e.id !== "none");
  const loops = { takes: { tk_e: { video: "e.mp4", poster: "e.jpg" } }, effects: Object.fromEntries(tested.map((e) => [e.id, "tk_e"])), moves: {} };
  const deck = effectDeck(catalog, loops);
  assert.deepEqual(deck.map((e) => e.id), tested.map((e) => e.id));
  assert.ok(deck.every((e) => ["Weather and light", "Time", "Transformation"].includes(e.kindLabel)));
  const timed = deck.filter((e) => ["time_freeze", "slow_motion"].includes(e.id));
  assert.ok(timed.every((e) => e.kindLabel === "Time"), "time is not weather");
  assert.ok(!effectDeck(catalog, { ...loops, effects: { none: "tk_e" } }).length);
});

test("the trailer's reel gives each segment its share of the running time and knows where the trailer is", () => {
  const reel = trailerReel([{ start: 0, end: 2, label: "a", take: "t1" }, { start: 2, end: 6, label: "b", take: "t2" }]);
  assert.deepEqual(reel.map((s) => s.share), [1 / 3, 2 / 3]);
  assert.deepEqual(reelAt(reel, 1), { index: 0, through: 0.5 });
  assert.deepEqual(reelAt(reel, 5), { index: 1, through: 0.75 });
  assert.equal(reelAt(reel, 9).index, -1);
  assert.deepEqual(trailerReel([]), []);
});

test("the marquee counts only what the data holds and never mentions testing", () => {
  assert.deepEqual(marqueeCounts({ moves: 49, effects: 21, takes: 135 }), ["49 CAMERA MOVES", "21 EFFECTS", "135 RECORDED TAKES"]);
  assert.deepEqual(marqueeCounts({ moves: 49 }), ["49 CAMERA MOVES"]);
  assert.ok(!marqueeCounts({ moves: 49, effects: 21, takes: 3 }).some((line) => /TEST/.test(line)));
});

test("the mouse scrubs from the first frame at the left edge to near the last at the right", () => {
  assert.equal(scrubTime(0, 200, 5), 0);
  assert.equal(scrubTime(100, 200, 5), 2.5);
  assert.equal(scrubTime(400, 200, 5), 4.96, "kept inside the clip");
  assert.equal(scrubTime(-10, 200, 5), 0);
  assert.equal(scrubTime(50, 0, 5), 0);
});

test("the move sheet's arrows wrap around the gallery", () => {
  assert.equal(stepIn(["a", "b", "c"], "c", 1), "a");
  assert.equal(stepIn(["a", "b", "c"], "a", -1), "c");
  assert.equal(stepIn(["a", "b", "c"], "zz", 1), "a");
  assert.equal(stepIn([], "a", 1), null);
});

test("a move is shared at its own page on the hosted copy and at the Lobby's address on a live studio", () => {
  assert.equal(movePageUrl("dolly_in", { isStatic: true, href: "https://x.github.io/openfield-studio/#/lobby" }), "https://x.github.io/openfield-studio/m/dolly_in.html");
  assert.equal(movePageUrl("dolly_in", { isStatic: false, href: "http://127.0.0.1:8890/#/takes" }), "http://127.0.0.1:8890/#/lobby/dolly_in");
  assert.equal(movePageUrl("dolly_in", { isStatic: true }), "m/dolly_in.html");
});

test("with no move on the page yet, either arrow starts at the first of the gallery", () => {
  for (const none of [null, undefined, "not_in_the_gallery"]) {
    assert.equal(stepIn(["a", "b", "c"], none, 1), "a");
    assert.equal(stepIn(["a", "b", "c"], none, -1), "a", "backward from nowhere is the first as well");
  }
  assert.equal(stepIn([], null, -1), null);
});

test("the arrows meet at both ends: a full turn either way comes back to the move it began on", () => {
  const ids = moveDeck(catalog, previews).map((m) => m.id);
  assert.ok(ids.length > 2);
  assert.equal(stepIn(ids, ids.at(-1), 1), ids[0], "past the last is the first");
  assert.equal(stepIn(ids, ids[0], -1), ids.at(-1), "before the first is the last");
  for (const delta of [1, -1]) {
    let id = ids[0];
    const walked = [];
    for (let i = 0; i < ids.length; i += 1) { walked.push(id); id = stepIn(ids, id, delta); }
    assert.equal(id, ids[0], `${ids.length} steps ${delta > 0 ? "forward" : "back"} are a full turn`);
    assert.deepEqual([...walked].sort(), [...ids].sort(), "every move is visited once on the way round");
  }
});

test("a gallery of one stays where it is, and two swap places both ways", () => {
  assert.equal(stepIn(["a"], "a", 1), "a");
  assert.equal(stepIn(["a"], "a", -1), "a");
  assert.equal(stepIn(["a", "b"], "a", 1), "b");
  assert.equal(stepIn(["a", "b"], "a", -1), "b");
  assert.equal(stepIn(["a", "b"], "b", 1), "a");
});
