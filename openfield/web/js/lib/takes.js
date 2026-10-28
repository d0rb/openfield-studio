// The Takes list: what is shown, in what order, and how takes relate to each other.
// Generated-character takes belong to the Cast station and never clutter the film ledger.

export const FILM_KINDS = new Set(["direct", "reshoot", "export", "transition", "shots", "edit", "extend", "upscale"]);

const newestFirst = (a, b) => b.created_at.localeCompare(a.created_at);

/** Takes for the ledger: films (shots, re-shoots, bridges, boards and edits) and exports, newest first. */
export function ledgerTakes(takes, { kind = null, status = null } = {}) {
  return takes
    .filter((t) => FILM_KINDS.has(t.kind) && (!kind || t.kind === kind) && (!status || t.status === status))
    .sort(newestFirst);
}

/** Generated-character takes, newest first, for the Cast station's candidates. */
export const portraitTakes = (takes) => takes.filter((t) => t.kind === "portrait").sort(newestFirst);

/** { [parentId]: [child takes] }: exports and remixes hang under the take they came from. */
export function children(takes) {
  const out = {};
  for (const take of takes) if (take.parent) (out[take.parent] ??= []).push(take);
  for (const list of Object.values(out)) list.sort(newestFirst);
  return out;
}

/** The ancestors of a take, nearest first, so the ledger can show where it came from. */
export function lineage(takes, takeId) {
  const byId = new Map(takes.map((t) => [t.id, t]));
  const chain = [];
  let current = byId.get(takeId);
  const seen = new Set();
  while (current?.parent && !seen.has(current.parent)) {
    seen.add(current.parent);
    current = byId.get(current.parent);
    if (current) chain.push(current);
  }
  return chain;
}

/** Takes that can be joined into a reel: finished films with a video. */
export const reelable = (takes) =>
  takes.filter((t) => t.status === "succeeded" && t.kind !== "portrait" && t.outputs?.some((o) => o.role === "video"));

/** A short status word for a row. Replays say so: a replayed take is never passed off as a render. */
export function statusLabel(take) {
  if (take.status === "succeeded") return take.replay ? "Replay" : "Done";
  return { queued: "Queued", running: "Running", awaiting_approval: "Needs your approval", failed: "Failed", canceled: "Canceled" }[take.status] ?? take.status;
}

/** The crop focus remembered for a take's 9:16 export, or the centre. */
export const cropFocus = (map, takeId) => map.get(takeId) ?? 0.5;

/** The place a recipe can be reloaded into: the form it came from. */
export const formFor = (take) => (take.kind === "reshoot" ? "reshoot" : take.kind === "direct" ? "direct" : null);
