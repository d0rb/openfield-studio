// HTTP client for the OpenField API. Every call returns parsed JSON or throws an ApiError.
// A second implementation (static manifest, for the hosted Replay) shares this surface.

import { followTake } from "./sse.js";

export class ApiError extends Error {
  constructor(status, code, message, details = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function failure(res) {
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* not JSON */
  }
  const e = body?.error ?? {};
  return new ApiError(res.status, e.code ?? `http_${res.status}`, e.message ?? (res.statusText || "Request failed"), e);
}

async function send(path, init) {
  const res = await fetch(path, init);
  if (!res.ok) throw await failure(res);
  return res.status === 204 ? null : res.json();
}

const get = (path) => send(path);
const post = (path, body) =>
  send(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });
const postForm = (path, form) => send(path, { method: "POST", body: form });
const del = (path) => send(path, { method: "DELETE" });

const query = (params = {}) => {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null));
  return q.size ? `?${q}` : "";
};

const idOf = (take) => (typeof take === "string" ? take : take.id);

/** URL of a file in a take folder. Recorded takes carry a `media_base`; ledger takes use the API. */
const mediaBase = (take) => (typeof take === "object" && take.media_base) || `/api/takes/${idOf(take)}/media`;

export const http = {
  kind: "http",
  status: () => get("/api/status"),
  moves: () => get("/api/moves"),
  recorded: () => get("/api/replay/recorded"),
  recreate: (recordedId) => post("/api/replay/recreate", { id: recordedId }),
  plan: (body) => post("/api/direct/plan", body),
  setBackend: (mode) => post("/api/backend", { mode }),
  fetchFaceModels: () => post("/api/models/face"),

  takes: (params) => get(`/api/takes${query(params)}`),
  take: (id) => get(`/api/takes/${id}`),
  startDirect: (body) => post("/api/takes/direct", body),
  startReshoot: (form) => postForm("/api/takes/reshoot", form),
  approve: (id, reroll = []) => post(`/api/takes/${id}/approve`, { reroll }),
  cancel: (id) => post(`/api/takes/${id}/cancel`),
  remove: (id) => del(`/api/takes/${id}`),
  receipt: (take) => get(`/api/takes/${idOf(take)}/receipt`),
  media: (take, path) => `${mediaBase(take)}/${path}`,
  workflowsUrl: (take) => `/api/takes/${idOf(take)}/workflows.zip`,
  snippetUrl: (take) => `/api/takes/${idOf(take)}/sdk-snippet`,
  eventsUrl: (id) => `/api/takes/${id}/events`,
  follow: (id, handlers) => followTake(http, id, handlers),

  exportVertical: (id, focusX = 0.5) => post(`/api/takes/${id}/export/vertical`, { focus_x: focusX }),
  exportReel: (takeIds, crossfade = 0.5) => post("/api/exports/reel", { take_ids: takeIds, crossfade_s: crossfade }),
  importReceipt: (file) => {
    const form = new FormData();
    form.append("file", file);
    return postForm("/api/receipts/import", form);
  },

  cast: {
    list: () => get("/api/cast"),
    create: (form) => postForm("/api/cast", form),
    remove: (id) => del(`/api/cast/${id}`),
    refUrl: (id, file) => `/api/cast/${id}/refs/${file}`,
    /** Start a "generated character" take: a few candidate portraits of an invented person. */
    generate: (body) => post("/api/cast/generate", body),
    /** Keep one finished candidate as a Cast (always fictional, with its provenance). */
    fromTake: (takeId, candidate, name) => post("/api/cast/from-take", { take_id: takeId, candidate, name }),
  },
};

export { TERMINAL } from "./status.js";
