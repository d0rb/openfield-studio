import test from "node:test";
import assert from "node:assert/strict";

import { createStaticApi, LOCKED_MESSAGE } from "../../openfield/web/js/lib/api-static.js";
import { ApiError } from "../../openfield/web/js/lib/api.js";

const SOURCE = {
  id: "tk_20261016_120000_aaaa",
  kind: "direct",
  label: "static: A lighthouse",
  status: "succeeded",
  created_at: "2026-10-16T12:00:00Z",
  media_base: "showcase/takes/tk_20261016_120000_aaaa",
  outputs: [{ role: "video", file: "take.mp4" }],
  identity: { hero: { status: "pass", score: 0.7 } },
  audit: { result: "pass" },
  anchors: [{ index: 0, file: "runs/01_hero/image.png" }],
  seconds: 5,
  size: [1280, 720],
  notes: ["note"],
};
const OLDER = { ...SOURCE, id: "tk_20261015_090000_bbbb", created_at: "2026-10-15T09:00:00Z", kind: "export",
  media_base: "showcase/takes/tk_20261015_090000_bbbb" };

const EVENTS = [
  { t: 0, type: "stage", stage: "hero", index: 1, total: 2, state: "start" },
  { t: 20, type: "run", stage: "hero", run: "01_hero", event: { kind: "progress", value: 0.5, step: 4, steps: 8 } },
  { t: 40, type: "approval", anchors: [{ index: 0, file: "runs/01_hero/image.png" }] },
  { t: 60, type: "take", take: { id: "ignored" } },
  { t: 80, type: "end", status: "succeeded" },
];

const MANIFEST = {
  static: true,
  status: { static: true, backend: { kind: "replay", locked: true } },
  moves: { moves: [] },
  takes: [SOURCE, OLDER],
  recorded: [{ id: SOURCE.id, label: SOURCE.label, media_base: SOURCE.media_base }],
  cast: [],
};

const jsonLines = (rows) => rows.map((row) => JSON.stringify(row)).join("\n") + "\n";

function fetchFor(files, log = []) {
  return async (url) => {
    log.push(url);
    if (!(url in files)) return { ok: false, status: 404, json: async () => ({}), text: async () => "" };
    const body = files[url];
    return { ok: true, status: 200, json: async () => body, text: async () => (typeof body === "string" ? body : JSON.stringify(body)) };
  };
}

/** A clock the test drives by hand: timers run in time order when `flush` is called. */
function manualTimers() {
  const pending = [];
  let now = 0;
  let id = 0;
  return {
    delays: [],
    set(fn, ms) {
      const entry = { id: ++id, at: now + ms, fn };
      pending.push(entry);
      this.delays.push(ms);
      return entry.id;
    },
    clear(handle) {
      const index = pending.findIndex((e) => e.id === handle);
      if (index >= 0) pending.splice(index, 1);
    },
    async flush() {
      for (;;) {
        await new Promise((r) => setImmediate(r)); // let promise callbacks (fetch, then) run
        if (!pending.length) return;
        pending.sort((a, b) => a.at - b.at);
        const next = pending.shift();
        now = next.at;
        next.fn();
      }
    },
  };
}

async function build(extraFiles = {}, options = {}) {
  const timers = manualTimers();
  const files = {
    "static/manifest.json": MANIFEST,
    [`${SOURCE.media_base}/events.jsonl`]: jsonLines(EVENTS),
    [`${SOURCE.media_base}/receipt.view.json`]: { receipt: { id: 1 }, verified: true, recipe_link: "x" },
    ...extraFiles,
  };
  const log = [];
  const api = await createStaticApi({ fetchImpl: fetchFor(files, log), timers, now: () => "2026-10-16T20:00:00Z", ...options });
  return { api, timers, log };
}

test("a page that is not a static export yields no api (the live app answers 404)", async () => {
  assert.equal(await createStaticApi({ fetchImpl: fetchFor({}) }), null);
  assert.equal(await createStaticApi({ fetchImpl: async () => { throw new Error("offline"); } }), null);
  assert.equal(await createStaticApi({ fetchImpl: fetchFor({ "static/manifest.json": { static: false } }) }), null);
});

test("reads come from the manifest and the take folders", async () => {
  const { api } = await build();
  assert.equal(api.kind, "static");
  assert.equal((await api.status()).backend.locked, true);
  assert.deepEqual(await api.moves(), { moves: [] });
  assert.deepEqual((await api.recorded()).map((r) => r.id), [SOURCE.id]);
  assert.deepEqual(await api.cast.list(), []);
  assert.deepEqual((await api.takes()).map((t) => t.id), [SOURCE.id, OLDER.id]);
  assert.deepEqual((await api.takes({ kind: "export" })).map((t) => t.id), [OLDER.id]);
  assert.equal((await api.takes({ limit: 1 })).length, 1);
  assert.equal((await api.take(SOURCE.id)).label, SOURCE.label);
  await assert.rejects(api.take("tk_missing"), (e) => e instanceof ApiError && e.status === 404);

  assert.equal(api.media(SOURCE, "take.mp4"), `${SOURCE.media_base}/take.mp4`);
  assert.equal(api.media(SOURCE.id, "poster.png"), `${SOURCE.media_base}/poster.png`);
  assert.equal(api.workflowsUrl(SOURCE), `${SOURCE.media_base}/workflows.zip`);
  assert.equal(api.snippetUrl(SOURCE.id), `${SOURCE.media_base}/sdk-snippet.py`);
  assert.equal((await api.receipt(SOURCE)).verified, true);
  await assert.rejects(api.receipt(OLDER), (e) => e.status === 404);
});

test("every write is refused with the same plain explanation", async () => {
  const { api } = await build();
  const writes = [
    () => api.plan({}), () => api.setBackend("sdk"), () => api.fetchFaceModels(), () => api.startDirect({}),
    () => api.startReshoot(new FormData()), () => api.approve("x"), () => api.exportVertical("x"),
    () => api.exportReel(["a", "b"]), () => api.importReceipt(null), () => api.cast.create(new FormData()),
    () => api.cast.remove("x"), () => api.cast.generate({ description: "a sailor" }),
    () => api.cast.fromTake("tk_x", 1, "Sailor"), () => api.remove(SOURCE.id), () => api.cancel(SOURCE.id),
  ];
  for (const write of writes) {
    await assert.rejects(write(), (e) => e instanceof ApiError && e.code === "replay_unavailable" && e.message === LOCKED_MESSAGE);
  }
});

test("recreate makes a replay take that holds back its results until playback ends", async () => {
  const { api, timers } = await build();
  const take = await api.recreate(SOURCE.id);
  assert.equal(take.replay, true);
  assert.equal(take.replay_of, SOURCE.id);
  assert.equal(take.status, "queued");
  assert.equal(take.label, `${SOURCE.label} (replay)`);
  assert.deepEqual(take.outputs, []);
  assert.deepEqual(take.anchors, []);
  assert.equal(take.media_base, SOURCE.media_base);
  assert.deepEqual((await api.takes())[0].id, take.id, "the new take is listed first");

  const events = [];
  let ended = null;
  api.follow(take.id, { onEvent: (e) => events.push(e), onEnd: (s) => (ended = s) });
  await timers.flush();

  assert.deepEqual(events.map((e) => e.type), ["take", "stage", "run", "approval", "take", "end"]);
  assert.equal(events[0].take.status, "running");
  assert.ok(events.slice(1, 4).every((e) => e.replayed === true), "replayed events are labelled");
  assert.ok(events.slice(1, 4).every((e) => !("t" in e)), "timestamps are not leaked to the UI");
  const final = events[4].take;
  assert.equal(final.status, "succeeded");
  assert.equal(final.progress, 1);
  assert.deepEqual(final.outputs, SOURCE.outputs);
  assert.deepEqual(final.anchors, SOURCE.anchors);
  assert.equal(final.seconds, 5);
  assert.deepEqual(events[5], { type: "end", status: "succeeded" });
  assert.equal(ended, "succeeded");
  assert.equal((await api.take(take.id)).status, "succeeded");
});

test("a long recording is compressed to the playback budget, a short one keeps its pace", async () => {
  const fast = await build({}, { playbackSeconds: 8 });
  const take = await fast.api.recreate(SOURCE.id);
  fast.api.follow(take.id, { onEvent() {} });
  await fast.timers.flush();
  // recorded span is 80 s; 8 s budget => factor 0.1 => gaps of 20 s become 2000 ms
  assert.deepEqual(fast.timers.delays, [0, 2000, 2000]);

  const slow = await build({}, { playbackSeconds: 1000 });
  const again = await slow.api.recreate(SOURCE.id);
  slow.api.follow(again.id, { onEvent() {} });
  await slow.timers.flush();
  assert.deepEqual(slow.timers.delays, [0, 20000, 20000], "never slower than the original");
});

test("stopping or cancelling a replay ends it cleanly and keeps results back", async () => {
  const { api, timers } = await build();
  const take = await api.recreate(SOURCE.id);
  const events = [];
  let ended = null;
  api.follow(take.id, { onEvent: (e) => events.push(e), onEnd: (s) => (ended = s) });
  await new Promise((r) => setImmediate(r));
  const canceled = await api.cancel(take.id);
  assert.equal(canceled.status, "canceled");
  assert.equal(ended, "canceled");
  assert.deepEqual(canceled.outputs, []);
  await timers.flush();
  assert.equal(events.at(-1).type, "end");
  assert.equal(events.filter((e) => e.type === "end").length, 1);

  const second = await api.recreate(SOURCE.id);
  let late = 0;
  const stop = api.follow(second.id, { onEvent: () => late++ });
  stop();
  const seen = late;
  await timers.flush();
  assert.equal(late, seen, "a stopped follower hears nothing more");

  await api.remove(second.id);
  assert.ok(!(await api.takes()).some((t) => t.id === second.id));
});

test("a recording that cannot be loaded fails the replay with a reason", async () => {
  const timers = manualTimers();
  // the manifest loads, but the take folder has no events.jsonl (a 404)
  const api = await createStaticApi({ fetchImpl: fetchFor({ "static/manifest.json": MANIFEST }), timers });
  const take = await api.recreate(SOURCE.id);
  const events = [];
  api.follow(take.id, { onEvent: (e) => events.push(e) });
  await timers.flush();
  assert.deepEqual(events.map((e) => e.type), ["take", "take", "error", "end"]);
  assert.equal(events[1].take.status, "failed");
  assert.equal(events[2].error.code, "replay_unavailable");
  assert.equal(events.at(-1).status, "failed");
});

test("only takes on the recorded shelf can be recreated", async () => {
  const { api } = await build();
  await assert.rejects(api.recreate(OLDER.id), (e) => e.code === "replay_unavailable");
  await assert.rejects(api.recreate("nope"), (e) => e.code === "replay_unavailable");
});

test("following a recorded take reports where it ended without playing anything", async () => {
  const { api } = await build();
  const events = [];
  let ended = null;
  api.follow(SOURCE.id, { onEvent: (e) => events.push(e), onEnd: (s) => (ended = s) });
  assert.equal(events.length, 1);
  assert.equal(events[0].take.id, SOURCE.id);
  assert.equal(ended, "succeeded");
});

test("a base URL applies to every fetch and every returned link", async () => {
  const base = "https://example.test/site/";
  const timers = manualTimers();
  const log = [];
  const folder = `${base}${SOURCE.media_base}`;
  const files = {
    [`${base}static/manifest.json`]: MANIFEST,
    [`${folder}/events.jsonl`]: jsonLines(EVENTS),
    [`${folder}/receipt.view.json`]: { verified: true },
  };
  const api = await createStaticApi({ fetchImpl: fetchFor(files, log), base, timers });
  assert.equal((await api.receipt(SOURCE)).verified, true);
  const take = await api.recreate(SOURCE.id);
  api.follow(take.id, { onEvent() {} });
  await timers.flush();
  assert.equal((await api.take(take.id)).status, "succeeded");
  assert.ok(log.length >= 3 && log.every((url) => url.startsWith(base)), log.join(", "));
  assert.equal(api.media(SOURCE, "take.mp4"), `${folder}/take.mp4`);
  assert.equal(api.workflowsUrl(SOURCE), `${folder}/workflows.zip`);
});

test("pickApi prefers the static export and falls back to the live api", async () => {
  const { pickApi } = await import("../../openfield/web/js/lib/boot.js");
  const live = { kind: "http" };
  assert.equal(await pickApi({ createStatic: async () => null, live }), live);
  const fake = { kind: "static" };
  assert.equal(await pickApi({ createStatic: async () => fake, live }), fake);
});

test("a recording without optional fields still ends with the same defaults the server uses", async () => {
  const bare = { id: "tk_20261016_110000_cccc", kind: "direct", label: "bare", status: "succeeded",
    created_at: "2026-10-16T11:00:00Z", media_base: "showcase/takes/tk_20261016_110000_cccc",
    outputs: [{ role: "video", file: "take.mp4" }] };
  const manifest = { ...MANIFEST, takes: [bare], recorded: [{ id: bare.id, label: bare.label, media_base: bare.media_base }] };
  const timers = manualTimers();
  const api = await createStaticApi({
    fetchImpl: fetchFor({ "static/manifest.json": manifest, [`${bare.media_base}/events.jsonl`]: jsonLines([{ t: 0, type: "end", status: "succeeded" }]) }),
    timers,
  });
  const take = await api.recreate(bare.id);
  api.follow(take.id, { onEvent() {} });
  await timers.flush();
  const done = await api.take(take.id);
  assert.equal(done.status, "succeeded");
  assert.deepEqual(done.anchors, []);
  assert.deepEqual(done.identity, {});
  assert.deepEqual(done.notes, []);
  assert.equal(done.audit, null);
  assert.deepEqual(done.outputs, bare.outputs);
});
