import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { recordedExtend, recordedUpscale, upscalable } from "../../openfield/web/js/lib/edit.js";
import { stageList } from "../../openfield/web/js/lib/stages.js";
import { FILM_KINDS } from "../../openfield/web/js/lib/takes.js";
import { KIND } from "../../openfield/web/js/ui/wall.js";
import { createController, initialState } from "../../openfield/web/js/controller.js";
import { createStore } from "../../openfield/web/js/lib/store.js";
import { createStaticApi, LOCKED_MESSAGE } from "../../openfield/web/js/lib/api-static.js";
import { ApiError } from "../../openfield/web/js/lib/api.js";

const catalog = JSON.parse(readFileSync(new URL("./fixtures/catalog.json", import.meta.url), "utf8"));

test("an upscale goes to 2K or 4K, shows its own steps and kind, and lands on the film ledger", () => {
  assert.deepEqual(catalog.upscale.targets.map((t) => [t.id, t.label]), [["2k", "2K"], ["4k", "4K"]]);
  assert.equal(catalog.upscale.tested, true, "the 2K upscale of a Draft take was checked by eye on Oct 23");
  const steps = stageList({ kind: "upscale", recipe: { take: "tk_src", target: "2k" } }, catalog);
  assert.deepEqual(steps.map((s) => [s.id, s.name]), [["upscale", "Upscale"], ["finish", "Finish"]]);
  assert.ok(FILM_KINDS.has("upscale"));
  assert.equal(KIND.upscale, "Upscale");
});

test("Replay plays a recorded upscale only of this take (a replay: of its recording) to the same target", () => {
  const rec = (id, kind, recipe) => ({ id, kind, recipe: { kind, ...recipe } });
  const shelf = [
    rec("tk_u2", "upscale", { take: "tk_src", target: "2k" }),
    rec("tk_x3", "extend", { take: "tk_src", seconds: 3, seed: 11 }),
    rec("tk_u4", "upscale", { take: "tk_x3", target: "4k" }),
    rec("tk_odd", "transition", { take: "tk_src", target: "4k" }),
  ];
  assert.equal(recordedUpscale(shelf, { id: "tk_src" }, "2k")?.id, "tk_u2");
  assert.equal(recordedUpscale(shelf, { id: "tk_replay_2", replay_of: "tk_src" }, "2k")?.id, "tk_u2", "a replay stands for its recording");
  assert.equal(recordedUpscale(shelf, { id: "tk_src" }, "4k"), null, "not to that size, and never another kind");
  assert.equal(recordedUpscale(shelf, { id: "tk_x3", kind: "extend" }, "4k")?.id, "tk_u4", "an extension upscaled");
  assert.equal(recordedUpscale(shelf, { id: "tk_other" }, "2k"), null, "nothing recorded for that take");
  assert.equal(recordedUpscale(undefined, { id: "tk_src" }, "2k"), null);
  // the extension matcher shares the rule and keeps its own kind and key
  assert.equal(recordedExtend(shelf, { id: "tk_src" }, 3)?.id, "tk_x3");
  assert.equal(recordedExtend(shelf, { id: "tk_src" }, "2k"), null);
});

test("the dock offers Upscale for a shot, a re-shoot, a bridge and an extension, never for an upscale", () => {
  for (const kind of ["direct", "reshoot", "transition", "extend"]) assert.equal(upscalable({ kind }), true, kind);
  for (const kind of ["upscale", "export", "shots", "edit", "portrait"]) assert.equal(upscalable({ kind }), false, kind);
  assert.equal(upscalable(null), false);
});

test("starting an upscale sends the take and the target, follows it, and leaves the selection to the sheet", async () => {
  const store = createStore(initialState());
  const sent = [];
  const followed = [];
  const api = {
    startUpscale: async (body) => { sent.push(body); return { id: "tk_up", kind: "upscale", status: "queued", created_at: "2026-10-23T12:00:00Z" }; },
    follow: (id) => { followed.push(id); return () => {}; },
  };
  const controller = createController({ api, store, setInterval: () => 1 });
  store.set({ selected: "tk_src" });
  assert.equal((await controller.startUpscale("tk_src", "2k")).id, "tk_up");
  assert.deepEqual(sent, [{ take: "tk_src", target: "2k" }], "the body POST /api/takes/upscale takes");
  assert.deepEqual(followed, ["tk_up"]);
  assert.equal(store.get().takes[0].id, "tk_up");
  assert.equal(store.get().selected, "tk_src");
  const refusing = createController({ api: { startUpscale: async () => { throw Object.assign(new Error("that take is already 3840x2160: pick a size larger than it"), { code: "http_422" }); } }, store, setInterval: () => 1 });
  assert.equal(await refusing.startUpscale("tk_big", "4k"), null, "a 422 becomes a notice, not a crash");
  assert.match(store.get().notices.at(-1).message, /already 3840x2160/);
});

test("the hosted copy refuses an upscale with the same plain explanation as every other write", async () => {
  const manifest = { static: true, status: { static: true, backend: { kind: "replay", locked: true } }, moves: catalog, takes: [], recorded: [], cast: [] };
  const fetchImpl = async (url) => (url === "static/manifest.json" ? { ok: true, status: 200, json: async () => manifest } : { ok: false, status: 404 });
  const api = await createStaticApi({ fetchImpl });
  await assert.rejects(api.startUpscale({ take: "tk_src", target: "2k" }), (e) => e instanceof ApiError && e.code === "replay_unavailable" && e.message === LOCKED_MESSAGE);
});
