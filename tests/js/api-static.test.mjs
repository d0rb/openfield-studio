import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { createStaticApi, LOCKED_MESSAGE, shelfEntry } from "../../openfield/web/js/lib/api-static.js";
import { ApiError } from "../../openfield/web/js/lib/api.js";
import { overall, perStage, ringState } from "../../openfield/web/js/lib/identity.js";

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
    () => api.plan({}), () => api.setBackend("sdk"), () => api.testBackend({}), () => api.connectBackend({}),
    () => api.forgetBackend(), () => api.fetchFaceModels(), () => api.startDirect({}), () => api.startDirectFromImage(new FormData()),
    () => api.startReshoot(new FormData()), () => api.startEdit(new FormData()), () => api.startExtend({ take: "x", seconds: 3 }),
    () => api.startTransition({ first: "a", second: "b", style: "dissolve", seconds: 2, idea: "Through the fire." }), () => api.approve("x"), () => api.exportVertical("x"),
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

test("the hosted copy answers an estimate with nothing measured, because it renders nothing", async () => {
  const { api } = await build();
  const estimate = await api.estimate({ quality: "draft", movement: "dolly_in", duration_seconds: 5 });
  assert.equal(estimate.seconds, null);
  assert.equal(estimate.basis, "Replay renders nothing");
});

test("the site says where the hosted copy lives, and the file is read once", async () => {
  const site = { site_url: "https://owner.github.io/studio/", repo_url: "https://github.com/owner/studio" };
  const { api, log } = await build({ "static/site.json": site });
  assert.deepEqual(await api.site(), site);
  assert.deepEqual(await api.site(), site, "the same answer the second time");
  assert.equal(log.filter((url) => url.endsWith("static/site.json")).length, 1, "the file is fetched once");
});

test("a site file that cannot be read leaves the addresses empty", async () => {
  const missing = await build(); // no static/site.json at all
  assert.deepEqual(await missing.api.site(), { site_url: null, repo_url: null });

  const timers = manualTimers();
  const offline = await createStaticApi({
    fetchImpl: async (url) => {
      if (url.endsWith("static/site.json")) throw new Error("offline");
      return fetchFor({ "static/manifest.json": MANIFEST })(url);
    },
    timers,
  });
  assert.deepEqual(await offline.site(), { site_url: null, repo_url: null });
});

test("the live app has no site of its own, and asks for nothing", async () => {
  const { http } = await import("../../openfield/web/js/lib/api.js");
  assert.deepEqual(await http.site(), { site_url: null, repo_url: null });
});

// -- the recorded shelf: an export lists its recorded takes by id, and the page joins them from the takes ---------------------------------------

/** A recorded take as the export lists it in `takes`: its own state as well as the fields the shelf shows. */
const FULL = {
  id: "tk_20261017_100000_dddd", kind: "direct", label: "full: A lighthouse", status: "succeeded", stage: "done", progress: 1, replay: false,
  created_at: "2026-10-17T10:00:00Z", updated_at: "2026-10-17T10:05:00Z", media_base: "showcase/takes/tk_20261017_100000_dddd",
  recipe_hash: "hash-dddd", recipe: { subject: "A lighthouse", rig: { movement: "static" } }, outputs: [{ role: "video", file: "take.mp4" }],
  identity: { hero: { status: "pass", score: 0.8, threshold: 0.363 } }, audit: { result: "pass" }, notes: ["a note"], seconds: 5,
  shots: [{ index: 1, file: "runs/03_shot_1/image.png" }], board: ["front"], edit: { before: "runs/01_hero/image.png" },
  anchors: [{ index: 0 }], size: [1280, 704], backend: { kind: "pod" }, parent: null, error: null, showcase_name: "x", showcase_sha: "y",
};
const LEAN = { id: "tk_20261016_110000_cccc", kind: "reshoot", label: "lean", status: "succeeded", created_at: "2026-10-16T11:00:00Z",
  media_base: "showcase/takes/tk_20261016_110000_cccc", recipe_hash: "hash-cccc", recipe: { prompt: "a dancer" }, outputs: [], identity: null, seconds: null };
const SHELF_KEYS = ["id", "kind", "label", "recipe_hash", "recipe", "outputs", "created_at", "identity", "audit", "notes", "seconds", "shots", "board", "edit", "media_base"];

test("a manifest that lists its recorded takes by id joins them from the takes, in the list's order", async () => {
  const manifest = { ...MANIFEST, takes: [FULL, SOURCE, LEAN], recorded: [LEAN.id, FULL.id, "tk_20261001_000000_gone"] };
  const { api } = await build({ "static/manifest.json": manifest });
  const shelf = await api.recorded();
  assert.deepEqual(shelf.map((r) => r.id), [LEAN.id, FULL.id], "the list's order; an id the manifest holds no take for is left out");
  assert.equal(await api.recorded(), shelf, "joined once, not on every ask");
  assert.deepEqual((await api.takes()).map((t) => t.id), [FULL.id, SOURCE.id, LEAN.id], "the takes themselves are all still there, newest first");
});

test("a joined entry has exactly the fields the server lists, and nothing of the take's own state", async () => {
  const { api } = await build({ "static/manifest.json": { ...MANIFEST, takes: [FULL, LEAN], recorded: [FULL.id, LEAN.id] } });
  const [full, lean] = await api.recorded();
  assert.deepEqual(Object.keys(full), SHELF_KEYS, "the server's order");
  assert.deepEqual(full, {
    id: FULL.id, kind: "direct", label: FULL.label, recipe_hash: "hash-dddd", recipe: FULL.recipe, outputs: FULL.outputs, created_at: FULL.created_at,
    identity: FULL.identity, audit: FULL.audit, notes: FULL.notes, seconds: 5, shots: FULL.shots, board: FULL.board, edit: FULL.edit, media_base: FULL.media_base,
  });
  for (const own of ["status", "stage", "progress", "replay", "updated_at", "anchors", "size", "backend", "parent", "error", "showcase_name", "showcase_sha"]) {
    assert.ok(!(own in full), `${own} is the take's, not the shelf's`);
  }
  // what a take does not have is not listed (the server lists a field only when the take has it), and no key holds undefined
  assert.deepEqual(Object.keys(lean), ["id", "kind", "label", "recipe_hash", "recipe", "outputs", "created_at", "media_base"]);
  assert.ok(Object.values(lean).every((v) => v !== undefined));
});

test("a take that has no creation time, or no media folder, is listed the way the server lists it", () => {
  assert.deepEqual(shelfEntry({ id: "a", kind: "direct", label: "x", recipe_hash: "h", recipe: {}, outputs: [] }),
    { id: "a", kind: "direct", label: "x", recipe_hash: "h", recipe: {}, outputs: [], created_at: null });
  assert.equal(shelfEntry({ id: "a", seconds: 0 }).seconds, 0, "a length of zero is a length");
});

test("a manifest that lists its recorded takes as objects still works, and a list may mix the two", async () => {
  const { api } = await build();
  assert.deepEqual(await api.recorded(), MANIFEST.recorded, "an older export: the entries are the shelf");
  const take = await api.recreate(SOURCE.id);
  assert.equal(take.replay_of, SOURCE.id);

  const mixed = { ...MANIFEST, takes: [FULL, SOURCE, LEAN], recorded: [{ id: SOURCE.id, label: SOURCE.label, media_base: SOURCE.media_base }, FULL.id] };
  const both = await build({ "static/manifest.json": mixed });
  assert.deepEqual((await both.api.recorded()).map((r) => r.id), [SOURCE.id, FULL.id]);
  assert.equal((await both.api.recorded())[0], mixed.recorded[0], "an entry that is an object is used as it is");
});

test("only takes on the shelf can be recreated, by id or by entry, and the replay carries the take's own fields", async () => {
  const manifest = { ...MANIFEST, takes: [FULL, SOURCE, LEAN], recorded: [FULL.id] };
  const { api } = await build({ "static/manifest.json": manifest });
  const replay = await api.recreate(FULL.id);
  assert.equal(replay.replay_of, FULL.id);
  assert.equal(replay.recipe_hash, "hash-dddd");
  assert.equal(replay.media_base, FULL.media_base);
  await assert.rejects(api.recreate(LEAN.id), (e) => e.code === "replay_unavailable", "a take that is listed but not on the shelf");
  await assert.rejects(api.recreate("tk_nope"), (e) => e.code === "replay_unavailable");
});

test("an empty or missing shelf is an empty shelf", async () => {
  assert.deepEqual(await (await build({ "static/manifest.json": { ...MANIFEST, recorded: [] } })).api.recorded(), []);
  const without = { ...MANIFEST };
  delete without.recorded;
  assert.deepEqual(await (await build({ "static/manifest.json": without })).api.recorded(), []);
});

test("the face check reads the same from the slimmed identity the export lists as from the whole report", () => {
  // the keys the export keeps (static_export.py IDENTITY_KEYS), read from the file so the two sides stay one list
  const keys = [...readFileSync(new URL("../../openfield/static_export.py", import.meta.url), "utf8").match(/IDENTITY_KEYS = \(([^)]*)\)/)[1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
  assert.deepEqual(keys, ["status", "score", "threshold", "retried"]);
  const whole = { best_ref: 0, per_ref: [0.8], faces_in_candidate: 1, candidate_box: [1, 2, 3, 4], refs_used: 1, reason: "cosine 0.8", face_px: 155, enlarged: null, frame: "first", frames_checked: 3 };
  const reports = {
    hero: { status: "pass", score: 0.9, threshold: 0.363, ...whole },
    shoot_1: { status: "drift", score: 0.2, threshold: 0.363, retried: true, ...whole },
    face: { status: "n/a", score: null, threshold: 0.363, ...whole },
    edit: { status: "unavailable", threshold: 0.363, ...whole },
  };
  const slim = Object.fromEntries(Object.entries(reports).map(([stage, r]) => [stage, Object.fromEntries(keys.filter((k) => k in r).map((k) => [k, r[k]]))]));
  assert.deepEqual(overall(slim), overall(reports));
  assert.deepEqual(perStage(slim), perStage(reports));
  for (const stage of Object.keys(reports)) assert.deepEqual(ringState(slim[stage]), ringState(reports[stage]), stage);
});
