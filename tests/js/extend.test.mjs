import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { bridgeRequest, recordedBridge, recordedExtend } from "../../openfield/web/js/lib/edit.js";
import { stageList } from "../../openfield/web/js/lib/stages.js";
import { FILM_KINDS } from "../../openfield/web/js/lib/takes.js";
import { KIND } from "../../openfield/web/js/ui/wall.js";
import { createController, initialState } from "../../openfield/web/js/controller.js";
import { createStore } from "../../openfield/web/js/lib/store.js";

const catalog = JSON.parse(readFileSync(new URL("./fixtures/catalog.json", import.meta.url), "utf8"));

// -- Extend ------------------------------------------------------------------------------------------

test("an extension adds 3 or 5 seconds, says it is tested (two extensions held on Oct 23), and shows its own steps and kind", () => {
  assert.deepEqual(catalog.extend, { seconds: [3, 5], tested: true });
  const steps = stageList({ kind: "extend", recipe: { take: "tk_src", seconds: 3 } }, catalog);
  assert.deepEqual(steps.map((s) => [s.id, s.name]), [["prepare", "Last frame"], ["extend", "Extension"], ["finish", "Finish"]]);
  assert.ok(FILM_KINDS.has("extend"));
  assert.equal(KIND.extend, "Extend");
});

test("Replay plays a recorded extension only of this take (a replay: of its recording) by the same seconds", () => {
  const rec = (id, recipe, kind = "extend") => ({ id, kind, recipe });
  const shelf = [
    rec("tk_x3", { kind: "extend", take: "tk_src", seconds: 3, seed: 11 }),
    rec("tk_x5", { kind: "extend", take: "tk_src", seconds: 5, seed: 12 }),
    rec("tk_bridge", { take: "tk_src", seconds: 3 }, "transition"),
    rec("tk_xx", { kind: "extend", take: "tk_x3", seconds: 3, seed: 13 }),
  ];
  assert.equal(recordedExtend(shelf, { id: "tk_src" }, 3)?.id, "tk_x3");
  assert.equal(recordedExtend(shelf, { id: "tk_src" }, 5)?.id, "tk_x5");
  assert.equal(recordedExtend(shelf, { id: "tk_replay_1", replay_of: "tk_src" }, 3)?.id, "tk_x3", "a replay stands for its recording");
  assert.equal(recordedExtend(shelf, { id: "tk_x3", kind: "extend" }, 3)?.id, "tk_xx", "an extension extended again");
  assert.equal(recordedExtend(shelf, { id: "tk_x3", kind: "extend" }, 5), null, "not by that length");
  assert.equal(recordedExtend(shelf, { id: "tk_other" }, 3), null, "nothing recorded for that take");
  assert.equal(recordedExtend(undefined, { id: "tk_src" }, 3), null);
});

test("starting an extension sends the take and the seconds, follows it, and leaves the selection to the sheet", async () => {
  const store = createStore(initialState());
  const sent = [];
  const followed = [];
  const api = {
    startExtend: async (body) => { sent.push(body); return { id: "tk_ext", kind: "extend", status: "queued", created_at: "2026-10-23T03:00:00Z" }; },
    follow: (id) => { followed.push(id); return () => {}; },
  };
  const controller = createController({ api, store, setInterval: () => 1 });
  store.set({ selected: "tk_src" });
  assert.equal((await controller.startExtend("tk_src", 5)).id, "tk_ext");
  assert.deepEqual(sent, [{ take: "tk_src", seconds: 5 }], "the body POST /api/takes/extend takes; the server picks the seed");
  assert.deepEqual(followed, ["tk_ext"]);
  assert.equal(store.get().takes[0].id, "tk_ext");
  assert.equal(store.get().selected, "tk_src");
  const refusing = createController({ api: { startExtend: async () => { throw Object.assign(new Error("tk_x is not a finished take with a video"), { code: "http_422" }); } }, store, setInterval: () => 1 });
  assert.equal(await refusing.startExtend("tk_x", 3), null, "a 422 becomes a notice, not a crash");
  assert.match(store.get().notices.at(-1).message, /not a finished take/);
});

// -- Transition: how it gets there ---------------------------------------------------------------------

test("a transition sends how it gets there only when said, tidied as the server keeps it", () => {
  const pair = { first: "tk_a", second: "tk_b", style: "dissolve", seconds: 2 };
  assert.deepEqual(bridgeRequest({ ...pair, idea: "" }), pair);
  assert.deepEqual(bridgeRequest({ ...pair, idea: "  \n " }), pair, "blank is no idea");
  assert.deepEqual(bridgeRequest(pair), pair);
  assert.deepEqual(bridgeRequest({ ...pair, idea: "  The camera flies into\nthe dragon's fire  " }), { ...pair, idea: "The camera flies into the dragon's fire" });
  assert.deepEqual(bridgeRequest({ ...pair, idea: "The camera flies into the dragon's fire..." }), { ...pair, idea: "The camera flies into the dragon's fire" }, "no closing stops, as rig.transition_idea");
  assert.equal(bridgeRequest({ ...pair, idea: "ab." }).idea, "ab", "so the 3-character check sees what the server will");
  assert.deepEqual(bridgeRequest({ ...pair, idea: " . " }), pair);
});

test("Replay plays a recorded bridge only with the same idea; an empty field plays one recorded without an idea", () => {
  const pair = { first: "tk_a", second: "tk_b", style: "dissolve", seconds: 2 };
  const shelf = [
    { id: "tk_plain", kind: "transition", recipe: { kind: "transition", ...pair, seed: 5 } },
    { id: "tk_fire", kind: "transition", recipe: { kind: "transition", ...pair, idea: "The camera flies into the dragon's fire", seed: 6 } },
    { id: "tk_edit", kind: "edit", recipe: { ...pair } },
  ];
  assert.equal(recordedBridge(shelf, { ...pair, idea: "" })?.id, "tk_plain");
  assert.equal(recordedBridge(shelf, { ...pair, idea: "   " })?.id, "tk_plain");
  assert.equal(recordedBridge(shelf, { ...pair, idea: " The camera flies  into the dragon's fire. " })?.id, "tk_fire", "after the same tidying");
  assert.equal(recordedBridge(shelf, { ...pair, idea: "A lava wave." }), null, "an idea nobody recorded");
  assert.equal(recordedBridge(shelf.slice(1), { ...pair, idea: "" }), null, "an empty field never plays a bridge with an idea");
  assert.equal(recordedBridge(shelf, { ...pair, style: "whip", idea: "" }), null);
  assert.equal(recordedBridge(shelf, { ...pair, seconds: 3, idea: "" }), null);
  assert.equal(recordedBridge(null, pair), null);
});
