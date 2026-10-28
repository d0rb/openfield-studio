import test from "node:test";
import assert from "node:assert/strict";

import { createController, initialState } from "../../openfield/web/js/controller.js";
import { createStore } from "../../openfield/web/js/lib/store.js";
import { describe, emptyLive, label, reduceLive } from "../../openfield/web/js/lib/live.js";

const take = (id, status, created = "2026-10-16T10:00:00Z", extra = {}) => ({ id, status, created_at: created, kind: "direct", ...extra });

function fakeApi(overrides = {}) {
  const calls = [];
  const followed = [];
  const api = {
    calls,
    followed,
    follow: (id, handlers) => {
      followed.push({ id, handlers });
      return () => followed.push({ stopped: id });
    },
    recorded: async () => [{ id: "tk_rec", label: "A recorded take" }],
    recreate: async (id) => take("tk_replay", "queued", "2026-10-16T11:30:00Z", { replay_of: id }),
    eventsUrl: (id) => `/e/${id}`,
    status: async () => ({ backend: { kind: "pod" } }),
    moves: async () => ({ moves: [] }),
    takes: async () => [take("tk_old", "succeeded", "2026-10-15T10:00:00Z")],
    take: async (id) => take(id, "succeeded"),
    cast: {
      list: async () => [{ id: "ca_1" }],
      create: async () => ({ id: "ca_2" }),
      remove: async () => null,
      generate: async (body) => { calls.push(["generate", body]); return take("tk_portrait", "queued", "2026-10-16T11:10:00Z", { kind: "portrait" }); },
      fromTake: async (takeId, candidate, name) => { calls.push(["fromTake", takeId, candidate, name]); return { id: "ca_3", name }; },
    },
    startDirect: async (body) => { calls.push(["startDirect", body]); return take("tk_new", "queued", "2026-10-16T11:00:00Z"); },
    startReshoot: async () => take("tk_re", "queued"),
    approve: async (id, reroll) => { calls.push(["approve", id, reroll]); return {}; },
    cancel: async (id) => take(id, "canceled"),
    remove: async (id) => { calls.push(["remove", id]); return null; },
    setBackend: async (mode) => ({ backend: { kind: mode } }),
    testBackend: async (body) => { calls.push(["testBackend", body]); return { health: { ok: true }, target: { kind: "pod", host: "127.0.0.1:9189" }, warnings: [], preflight: null }; },
    connectBackend: async (body) => { calls.push(["connectBackend", body]); return { backend: { kind: "pod", source: body.remember ? "saved" : "session" } }; },
    forgetBackend: async () => { calls.push(["forgetBackend"]); return { backend: { kind: "replay", source: null } }; },
    exportVertical: async (id) => take("tk_ex", "succeeded", "2026-10-16T12:00:00Z", { kind: "export" }),
    exportReel: async () => take("tk_reel", "succeeded", "2026-10-16T12:30:00Z", { kind: "export" }),
    ...overrides,
  };
  return api;
}

function setup(apiOverrides) {
  const store = createStore(initialState());
  const api = fakeApi(apiOverrides);
  const controller = createController({ api, store, setInterval: () => 1 });
  return { api, store, controller, followed: api.followed };
}

test("a take started somewhere else appears on refresh and is followed while it runs", async () => {
  let listed = [take("tk_old", "succeeded", "2026-10-15T10:00:00Z")];
  const { store, controller, followed } = setup({ takes: async () => listed });
  await controller.load();
  assert.deepEqual(store.get().takes.map((t) => t.id), ["tk_old"]);
  listed = [take("tk_elsewhere", "running", "2026-10-16T12:00:00Z"), ...listed]; // started by another tab
  await controller.refreshTakes();
  assert.deepEqual(store.get().takes.map((t) => t.id), ["tk_elsewhere", "tk_old"], "newest first");
  assert.equal(followed.filter((f) => f.id === "tk_elsewhere").length, 1, "its events are followed");
  await controller.refreshTakes();
  assert.equal(followed.filter((f) => f.id === "tk_elsewhere").length, 1, "and only once");
  assert.equal(store.get().selected, null, "what you were looking at does not move");
});

test("load fills the store and follows only unfinished takes", async () => {
  const { store, controller, followed } = setup({
    takes: async () => [take("tk_run", "running", "2026-10-16T09:00:00Z"), take("tk_done", "succeeded", "2026-10-15T09:00:00Z")],
  });
  await controller.load();
  const s = store.get();
  assert.equal(s.loaded, true);
  assert.deepEqual(s.takes.map((t) => t.id), ["tk_run", "tk_done"]);
  assert.deepEqual(s.cast, [{ id: "ca_1" }]);
  assert.deepEqual(followed.map((f) => f.id), ["tk_run"]);
});

test("starting a take selects it, follows it, and keeps newest first", async () => {
  const { store, controller, followed, api } = setup();
  await controller.load();
  const started = await controller.startDirect({ subject: "A lighthouse" });
  assert.equal(started.id, "tk_new");
  assert.equal(store.get().selected, "tk_new");
  assert.equal(store.get().takes[0].id, "tk_new");
  assert.deepEqual(api.calls[0], ["startDirect", { subject: "A lighthouse" }]);
  // events flow into the live state and the take list
  const handlers = followed.at(-1).handlers;
  handlers.onEvent({ type: "stage", stage: "hero", index: 1, total: 3, state: "start" });
  handlers.onEvent({ type: "take", take: take("tk_new", "running", "2026-10-16T11:00:00Z", { progress: 0.3 }) });
  assert.equal(store.get().live.tk_new.stage, "hero");
  assert.equal(store.get().takes[0].status, "running");
  handlers.onEnd("succeeded");
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(store.get().takes[0].status, "succeeded");
});

test("recreating a recorded take starts and follows a replay and loads the shelf", async () => {
  const { store, controller, followed } = setup();
  await controller.load();
  assert.deepEqual(store.get().recorded.map((r) => r.id), ["tk_rec"]);
  const made = await controller.recreate("tk_rec");
  assert.equal(made.replay_of, "tk_rec");
  assert.equal(store.get().selected, "tk_replay");
  assert.deepEqual(followed.map((f) => f.id), ["tk_replay"]);
});

test("generating a character follows its take without stealing the selection, and keeping one refreshes the cast", async () => {
  const { store, controller, followed, api } = setup();
  await controller.load();
  store.set({ selected: "tk_old" });
  const made = await controller.generateCharacter({ description: "a courier in a yellow raincoat", count: 3 });
  assert.equal(made.kind, "portrait");
  assert.deepEqual(followed.map((f) => f.id), ["tk_portrait"]);
  assert.equal(store.get().selected, "tk_old", "the Cast station shows candidates itself");
  assert.ok(store.get().takes.some((t) => t.id === "tk_portrait"));
  assert.deepEqual(api.calls.at(-1), ["generate", { description: "a courier in a yellow raincoat", count: 3 }]);

  const cast = await controller.keepCandidate("tk_portrait", 2, "Courier");
  assert.equal(cast.name, "Courier");
  assert.deepEqual(api.calls.at(-1), ["fromTake", "tk_portrait", 2, "Courier"]);
});

test("a failed call becomes a dismissible notice, not a crash", async () => {
  const { store, controller } = setup({
    startDirect: async () => { const e = new Error("Pick a smaller move"); e.code = "invalid_request"; throw e; },
  });
  await controller.load();
  assert.equal(await controller.startDirect({}), null);
  const [notice] = store.get().notices;
  assert.equal(notice.code, "invalid_request");
  controller.dismiss(notice.id);
  assert.deepEqual(store.get().notices, []);
});

test("remove stops following and clears the selection", async () => {
  const { store, controller, followed, api } = setup();
  await controller.load();
  await controller.startDirect({});
  await controller.remove("tk_new");
  assert.ok(followed.some((f) => f.stopped === "tk_new"));
  assert.ok(!store.get().takes.some((t) => t.id === "tk_new"));
  assert.equal(store.get().selected, null);
  assert.deepEqual(api.calls.at(-1), ["remove", "tk_new"]);
});

test("cast, exports and backend switching update the store", async () => {
  const { api, store, controller } = setup();
  await controller.load();
  await controller.createCast(new FormData());
  assert.deepEqual(store.get().cast, [{ id: "ca_1" }]);
  assert.equal((await controller.exportVertical("tk_old", 0.4)).id, "tk_ex");
  assert.equal((await controller.exportReel(["a", "b"], 0.5)).id, "tk_reel");
  assert.ok(store.get().takes.some((t) => t.id === "tk_ex"));
  await controller.setBackend("replay");
  assert.equal(store.get().status.backend.kind, "replay");
  const probe = await controller.testBackend({ base_url: "http://127.0.0.1:9189" });
  assert.equal(probe.health.ok, true);
  assert.equal(store.get().status.backend.kind, "replay", "a test never switches");
  await controller.connectBackend({ base_url: "http://127.0.0.1:9189", api_key: "t", remember: true });
  assert.deepEqual(store.get().status.backend, { kind: "pod", source: "saved" });
  await controller.forgetBackend();
  assert.equal(store.get().status.backend.kind, "replay");
  assert.deepEqual(api.calls.filter((c) => /Backend$/.test(c[0])).map((c) => c[0]), ["testBackend", "connectBackend", "forgetBackend"]);
});

test("live reducer follows a whole Direct run, including approval and identity", () => {
  let live = emptyLive();
  const feed = (e) => (live = reduceLive(live, e));
  feed({ type: "stage", stage: "hero", index: 1, total: 4, state: "start" });
  assert.equal(describe(live), "Hero still");
  feed({ type: "run", stage: "hero", run: "01_hero", event: { kind: "uploading", files: 2, bytes: 10 } });
  assert.equal(describe(live), "Uploading 2 files");
  feed({ type: "run", stage: "hero", run: "01_hero", event: { kind: "status", status: "queued", queue_position: 3 } });
  assert.equal(describe(live), "Queued (position 3)");
  feed({ type: "run", stage: "hero", run: "01_hero", event: { kind: "progress", value: 0.5, step: 4, steps: 8 } });
  assert.equal(describe(live), "Hero still: step 4/8");
  feed({ type: "run", stage: "hero", run: "01_hero", event: { kind: "preview", node: "7", bytes: 10 } });
  assert.deepEqual(live.preview, { run: "01_hero", node: "7" });
  feed({ type: "identity", stage: "hero", report: { status: "pass", score: 0.7 } });
  assert.equal(live.identity.hero.status, "pass");
  feed({ type: "approval", anchors: [{ index: 0, file: "runs/01_hero/image.png" }] });
  assert.equal(describe(live), "Waiting for your approval");
  feed({ type: "take", take: take("tk", "running") });
  assert.equal(live.approval, null, "approval clears when the take is no longer waiting");
  feed({ type: "error", error: { code: "job_failed", message: "CUDA out of memory" } });
  assert.equal(describe(live), "CUDA out of memory");
  const done = reduceLive(emptyLive(), { type: "end", status: "succeeded" });
  assert.equal(describe(done), "Done");
});

test("a new stage clears the previous run, and status or progress end a stale upload", () => {
  let live = emptyLive();
  const feed = (e) => (live = reduceLive(live, e));
  feed({ type: "stage", stage: "hero", index: 1, total: 3, state: "start" });
  feed({ type: "run", stage: "hero", run: "01_hero", event: { kind: "uploading", files: 1, bytes: 5 } });
  // `submitted` was lost: a status event must still end the upload
  feed({ type: "run", stage: "hero", run: "01_hero", event: { kind: "status", status: "running" } });
  assert.equal(live.uploading, null);
  feed({ type: "run", stage: "hero", run: "01_hero", event: { kind: "progress", value: 1, step: 8, steps: 8 } });
  feed({ type: "run", stage: "hero", run: "01_hero", event: { kind: "preview", node: "9", bytes: 4 } });
  assert.ok(live.preview);
  // finishing a stage keeps its last preview on screen; starting the next one wipes it
  feed({ type: "stage", stage: "hero", index: 1, total: 3, state: "done" });
  assert.ok(live.preview);
  feed({ type: "stage", stage: "anchor_1", index: 2, total: 3, state: "start" });
  assert.equal(live.preview, null);
  assert.equal(live.step, null);
  assert.equal(live.runStatus, null);
  assert.equal(describe(live), "Anchor 1");
});

test("a replayed approval shows its stills but never waits for approval", () => {
  let live = emptyLive();
  live = reduceLive(live, { type: "stage", stage: "anchor_1", index: 2, total: 4, state: "start" });
  live = reduceLive(live, { type: "approval", anchors: [{ index: 0, file: "runs/01_hero/image.png" }], replayed: true });
  assert.equal(live.approval, null);
  assert.equal(live.anchorsShown.length, 1);
  assert.equal(describe(live), "Anchor 1");
});

test("duplicate events are harmless and unknown ones are ignored", () => {
  const a = reduceLive(emptyLive(), { type: "stage", stage: "hero", index: 1, total: 2, state: "start" });
  const b = reduceLive(a, { type: "stage", stage: "hero", index: 1, total: 2, state: "start" });
  assert.deepEqual(a, b);
  assert.equal(reduceLive(a, { type: "mystery" }), a);
});

test("stage labels read like words", () => {
  assert.equal(label("anchor_2_retry"), "Anchor 2 (re-roll)");
  assert.equal(label("shoot_3"), "Shot 3");
  assert.equal(label("motion"), "Motion transfer");
  assert.equal(label("some_new_stage"), "some new stage");
  assert.equal(label(null), "");
});

test("a shot from the person's image starts over multipart and is followed like any take", async () => {
  const { store, controller, followed } = setup({ startDirectFromImage: async (form) => take(`tk_img_${form instanceof FormData}`, "queued", "2026-10-22T09:00:00Z") });
  await controller.load();
  const started = await controller.startDirectFromImage(new FormData());
  assert.equal(started.id, "tk_img_true");
  assert.equal(store.get().selected, "tk_img_true");
  assert.ok(followed.some((f) => f.id === "tk_img_true"));
});
