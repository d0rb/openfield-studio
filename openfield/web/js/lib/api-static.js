// Client-only API for the hosted Replay: same surface as `http`, no server behind it.
//
// Everything comes from static/manifest.json and the recorded take folders (showcase/takes/<id>/). The manifest lists its
// recorded takes by id, each one's fields being in `takes` already; the shelf the rooms read is joined from the two here.
// "Recreate" plays a recorded take's events back on a timer, the way the server's Replay does,
// and nothing can render: every write answers with the same plain explanation.

import { ApiError } from "./api.js";

const MANIFEST = "static/manifest.json";
const SITE = "static/site.json";
const PLAYBACK_SECONDS = 8; // a long render is compressed to at most this
const EVENTS_REPLAYED = new Set(["run", "stage", "identity", "approval"]);

export const LOCKED_MESSAGE =
  "Recorded takes only. Connect a backend to render.";

const locked = () => Promise.reject(new ApiError(409, "replay_unavailable", LOCKED_MESSAGE));

export const CHAT_HOSTED =
  "Chat runs on your own computer. Install OpenField to use it.";

const idOf = (take) => (typeof take === "string" ? take : take.id);

// The fields the server lists for a recorded take (`ReplayBackend.recorded`, /api/replay/recorded): these only, so a take's own
// status, stage and progress never reach the shelf. `SHELF_EXTRA` is listed only when the take has it.
const SHELF_BASE = ["id", "kind", "label", "recipe_hash", "recipe", "outputs"];
const SHELF_EXTRA = ["identity", "audit", "notes", "seconds", "shots", "board", "edit"];

/** One recorded take as the shelf lists it, picked from the take (its fields are shared, not copied: nothing writes to a take). */
export function shelfEntry(take) {
  const entry = {};
  for (const key of SHELF_BASE) if (take[key] !== undefined) entry[key] = take[key];
  entry.created_at = take.created_at ?? null;
  for (const key of SHELF_EXTRA) if (take[key] != null) entry[key] = take[key];
  if (take.media_base) entry.media_base = take.media_base;
  return entry;
}

/**
 * Load the manifest. Resolves to null when this page is not a static export (the live app answers
 * 404 there), so the caller can fall back to the HTTP api.
 */
export async function createStaticApi({
  fetchImpl = globalThis.fetch.bind(globalThis),
  base = "",
  timers = { set: (fn, ms) => globalThis.setTimeout(fn, ms), clear: (h) => globalThis.clearTimeout(h) },
  now = () => new Date().toISOString(),
  playbackSeconds = PLAYBACK_SECONDS,
} = {}) {
  let manifest;
  try {
    const res = await fetchImpl(`${base}${MANIFEST}`);
    if (!res.ok) return null;
    manifest = await res.json();
  } catch {
    return null;
  }
  if (!manifest?.static) return null;

  const session = new Map(); // takes made in this browser tab by "recreate"
  const results = new Map(); // take id -> what the recording produced; applied when playback ends
  const playbacks = new Map(); // take id -> cancel() for a playback in flight
  let counter = 0;
  let sitePromise = null; // the site's own address, fetched once and kept

  const at = (relative) => `${base}${relative}`; // base is empty in a browser page and a full URL in tests

  const byId = new Map(manifest.takes.map((t) => [t.id, t]));
  // an export lists the recorded takes by id (older ones list the entries themselves); an id the manifest holds no take for is left out
  const shelf = (manifest.recorded ?? []).map((r) => (typeof r === "string" ? (byId.has(r) ? shelfEntry(byId.get(r)) : null) : r)).filter(Boolean);
  const shelved = new Set(shelf.map((r) => r.id));

  const known = (id) => session.get(id) ?? byId.get(id);
  const need = (take) => {
    const found = known(idOf(take));
    if (!found) throw new ApiError(404, "not_found", `no such take: ${idOf(take)}`);
    return found;
  };
  const folder = (take) => {
    const t = typeof take === "object" && take.media_base ? take : need(take);
    return t.media_base;
  };
  const getJson = async (url) => {
    const res = await fetchImpl(url);
    if (!res.ok) throw new ApiError(res.status, "not_found", `could not load ${url}`);
    return res.json();
  };
  const getText = async (url) => {
    const res = await fetchImpl(url);
    if (!res.ok) throw new ApiError(res.status, "not_found", `could not load ${url}`);
    return res.text();
  };

  const patch = (id, changes) => {
    const next = { ...session.get(id), ...changes, updated_at: now() };
    session.set(id, next);
    return next;
  };

  function follow(id, { onEvent, onEnd } = {}) {
    const take = session.get(id);
    if (!take) {
      // a recorded take: nothing is running, report where it ended
      const done = need(id);
      onEvent?.({ type: "take", take: done });
      onEnd?.(done.status);
      return () => {};
    }
    let closed = false;
    let handle = null;
    const stop = () => {
      closed = true;
      timers.clear(handle);
      playbacks.delete(id);
    };
    const emit = (event) => !closed && onEvent?.(event);
    const finish = (status, error) => {
      if (closed) return;
      const changes =
        status === "succeeded" ? { status, stage: "done", progress: 1, ...results.get(id) } : error ? { status, error } : { status };
      const last = patch(id, changes);
      emit({ type: "take", take: last });
      if (error) emit({ type: "error", error });
      emit({ type: "end", status });
      stop();
      onEnd?.(status);
    };
    playbacks.set(id, () => finish("canceled"));

    patch(id, { status: "running", stage: "replay" });
    emit({ type: "take", take: session.get(id) });
    getText(at(`${folder(take)}/events.jsonl`))
      .then((text) => {
        const events = text.split("\n").filter((line) => line.trim()).map((line) => JSON.parse(line));
        const total = events.at(-1)?.t ?? 0;
        const factor = total > 0 ? Math.min(1, playbackSeconds / total) : 0;
        const queue = events.filter((e) => EVENTS_REPLAYED.has(e.type));
        let previous = 0;
        const step = () => {
          if (closed) return;
          const event = queue.shift();
          if (!event) return finish("succeeded");
          const wait = Math.max(0, (event.t - previous) * factor * 1000);
          previous = event.t;
          handle = timers.set(() => {
            if (closed) return;
            const shown = { ...event, replayed: true };
            delete shown.t;
            emit(shown);
            step();
          }, wait);
        };
        step();
      })
      .catch((error) => finish("failed", { code: "replay_unavailable", message: error.message, retryable: false }));
    return stop;
  }

  return {
    kind: "static",
    manifest,
    /** Where this hosted copy lives and which repository it was built from; nothing when the file is not there. */
    site: () => (sitePromise ??= fetchImpl(`${base}${SITE}`).then((res) => (res.ok ? res.json() : null)).catch(() => null)
      .then((data) => ({ site_url: data?.site_url ?? null, repo_url: data?.repo_url ?? null }))),
    status: async () => manifest.status,
    moves: async () => manifest.moves,
    recorded: async () => shelf,
    // an agent runs on the person's own computer: the hosted copy can only say how to get one
    chat: {
      info: async () => ({ enabled: false, code: "hosted", message: CHAT_HOSTED }),
      send: locked,
      stop: locked,
      reset: locked,
      settings: locked,
      eventsUrl: () => null,
    },
    cast: {
      list: async () => manifest.cast,
      create: locked,
      remove: locked,
      generate: locked,
      fromTake: locked,
      refUrl: (id, file) => `${base}showcase/cast/${id}/${file}`,
    },

    async takes({ kind, limit = 100 } = {}) {
      const all = [...session.values(), ...manifest.takes].sort((a, b) => b.created_at.localeCompare(a.created_at));
      return all.filter((t) => !kind || t.kind === kind).slice(0, limit);
    },
    take: async (id) => need(id),

    async recreate(recordedId) {
      const source = byId.get(recordedId);
      if (!source || !shelved.has(recordedId)) {
        throw new ApiError(409, "replay_unavailable", "That recorded take is not available.");
      }
      counter += 1;
      const stamp = now();
      const { outputs, identity, audit, seconds, size, anchors, notes } = source;
      const take = {
        ...source, id: `tk_replay_${counter}_${source.id.slice(-4)}`, label: `${source.label} (replay)`,
        status: "queued", stage: null, progress: 0, created_at: stamp, updated_at: stamp,
        replay: true, replay_of: source.id, media_base: source.media_base,
        outputs: [], identity: {}, audit: null, seconds: null, size: null, anchors: [], notes: [],
      };
      session.set(take.id, take);
      // the same defaults the server's replay applies to a recording that lacks a field
      results.set(take.id, {
        outputs: outputs ?? [], identity: identity ?? {}, audit: audit ?? null, seconds: seconds ?? null,
        size: size ?? null, anchors: anchors ?? [], notes: notes ?? [],
      });
      return take;
    },
    follow,
    eventsUrl: () => "",

    async cancel(id) {
      if (!session.has(id)) return locked();
      playbacks.get(id)?.();
      return session.get(id);
    },
    async remove(id) {
      if (!session.has(id)) return locked();
      playbacks.get(id)?.();
      session.delete(id);
      results.delete(id);
      return null;
    },

    receipt: (take) => getJson(at(`${folder(take)}/receipt.view.json`)),
    previews: () => (manifest.previews ? fetch(at("showcase/previews.json")).then((r) => (r.ok ? r.json() : null)).catch(() => null) : Promise.resolve(null)),
    asset: (path) => at(path),
    media: (take, path) => at(`${folder(take)}/${path}`),
    workflowsUrl: (take) => at(`${folder(take)}/workflows.zip`),
    snippetUrl: (take) => at(`${folder(take)}/sdk-snippet.py`),

    plan: locked,
    estimate: async () => ({ seconds: null, low: null, high: null, samples: 0, backend: "Replay (hosted)", basis: "Replay renders nothing" }),
    setBackend: locked,
    testBackend: locked,
    connectBackend: locked,
    forgetBackend: locked,
    fetchFaceModels: locked,
    startDirect: locked,
    startDirectFromImage: locked,
    startReshoot: locked,
    startShots: locked,
    startTransition: locked,
    startExtend: locked,
    startUpscale: locked,
    startEdit: locked,
    approve: locked,
    exportVertical: locked,
    exportReel: locked,
    importReceipt: locked,
  };
}
