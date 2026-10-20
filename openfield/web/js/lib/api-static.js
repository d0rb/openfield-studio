// Client-only API for the hosted Replay: same surface as `http`, no server behind it.
//
// Everything comes from static/manifest.json and the recorded take folders (showcase/takes/<id>/).
// "Recreate" plays a recorded take's events back on a timer, the way the server's Replay does,
// and nothing can render: every write answers with the same plain explanation.

import { ApiError } from "./api.js";

const MANIFEST = "static/manifest.json";
const PLAYBACK_SECONDS = 8; // a long render is compressed to at most this
const EVENTS_REPLAYED = new Set(["run", "stage", "identity", "approval"]);

export const LOCKED_MESSAGE =
  "This hosted copy replays recorded takes. Install OpenField and connect Comfy Cloud or a GPU box to render new ones.";

const locked = () => Promise.reject(new ApiError(409, "replay_unavailable", LOCKED_MESSAGE));

const idOf = (take) => (typeof take === "string" ? take : take.id);

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

  const at = (relative) => `${base}${relative}`; // base is empty in a browser page and a full URL in tests

  const known = (id) => session.get(id) ?? manifest.takes.find((t) => t.id === id);
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
    status: async () => manifest.status,
    moves: async () => manifest.moves,
    recorded: async () => manifest.recorded,
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
      const source = manifest.takes.find((t) => t.id === recordedId);
      if (!source || !manifest.recorded.some((r) => r.id === recordedId)) {
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
    media: (take, path) => at(`${folder(take)}/${path}`),
    workflowsUrl: (take) => at(`${folder(take)}/workflows.zip`),
    snippetUrl: (take) => at(`${folder(take)}/sdk-snippet.py`),

    plan: locked,
    setBackend: locked,
    fetchFaceModels: locked,
    startDirect: locked,
    startReshoot: locked,
    approve: locked,
    exportVertical: locked,
    exportReel: locked,
    importReceipt: locked,
  };
}
