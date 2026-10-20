// What the Monitor says about a take in flight: the steps it will go through and where it is now.
// Pure functions over the take, the move catalog and the live state from live.js.

import { estimatePlan } from "./direct.js";

const step = (id, name) => ({ id, name: name ?? stepName(id) });

/** Short names for the rail ("Hero still", "Anchor 1", "Shot 2"). */
export function stepName(id) {
  const fixed = { hero: "Hero still", review: "Approve", finish: "Finish", prepare: "Prepare clip", motion: "Motion transfer", replay: "Replay" };
  if (fixed[id]) return fixed[id];
  const numbered = /^(anchor|shoot|candidate)_(\d+)$/.exec(id);
  if (numbered) return `${{ anchor: "Anchor", shoot: "Shot", candidate: "Portrait" }[numbered[1]]} ${numbered[2]}`;
  return id.replace(/_/g, " ");
}

/** The steps a take will go through, in order. The approval step is a pause, not a render. */
export function stageList(take, catalog) {
  const recipe = take?.recipe ?? {};
  switch (take?.kind) {
    case "reshoot":
      return [step("prepare"), step("motion"), step("finish")];
    case "portrait":
      return [...Array.from({ length: recipe.count ?? 3 }, (_, i) => step(`candidate_${i + 1}`)), step("finish")];
    case "direct": {
      const move = catalog?.moves?.find((m) => m.id === recipe.rig?.movement);
      if (!move) return [step("hero"), step("review"), step("shoot_1", "Shoot"), step("finish")];
      const plan = estimatePlan(move, recipe.rig.duration_seconds, recipe.prompt_only);
      const list = [step("hero")];
      for (const anchor of plan.anchors) if (anchor.role === "edit") list.push(step(`anchor_${anchor.index}`));
      if (!recipe.auto_approve) list.push(step("review"));
      for (const segment of plan.segments) list.push(step(`shoot_${segment.index + 1}`, plan.segments.length === 1 ? "Shoot" : undefined));
      list.push(step("finish"));
      return list;
    }
    default:
      return [step("finish")];
  }
}

/**
 * done | active | pending for each step, plus failed / canceled on the step that was running.
 * `live` is the reduced event state: its latest stage and whether that stage started or finished.
 */
export function railStates(list, take, live) {
  const status = take?.status;
  let cursor = 0;
  if (status === "succeeded") cursor = list.length;
  else if (status === "awaiting_approval") cursor = Math.max(0, list.findIndex((s) => s.id === "review"));
  else if (live?.stage) {
    const at = list.findIndex((s) => s.id === live.stage);
    if (at >= 0) cursor = live.stageState === "done" ? at + 1 : at;
  }
  const ended = status === "failed" ? "failed" : status === "canceled" ? "canceled" : null;
  return list.map((_, i) => {
    if (i < cursor) return "done";
    if (i === cursor) return ended ?? (status === "queued" && !live?.stage ? "pending" : "active");
    return "pending";
  });
}

/** Which screen the Monitor shows for a take. */
export function monitorMode(take) {
  if (!take) return "empty";
  return { queued: "running", running: "running", awaiting_approval: "approval", failed: "failed", canceled: "canceled", succeeded: "ready" }[take.status] ?? "running";
}

/** One short line under the step name: what the machine is doing right now. */
export function runDetail(live, take) {
  if (live?.uploading) return `Uploading ${live.uploading.files} file${live.uploading.files === 1 ? "" : "s"}`;
  if (live?.runStatus === "queued") return live.queue ? `Waiting for a free GPU, position ${live.queue}` : "Waiting for a free GPU";
  if (live?.runStatus === "running") return live.steps ? `Step ${live.step} of ${live.steps}` : "Rendering";
  if (take?.status === "queued") return "Starting";
  return live?.stageState === "done" ? "Step finished" : "Working";
}

/** "1:05" for elapsed time. */
export function clock(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** The file a take keeps for a role ("video", "poster", "receipt"), or null. */
export const fileOf = (take, role) => take?.outputs?.find((o) => o.role === role)?.file ?? null;

/** What a take is called on screen: what was asked for, in full, not the server's shortened label. */
export function titleOf(take) {
  const r = take?.recipe ?? {};
  const asked = { direct: r.subject, reshoot: r.prompt, portrait: r.description }[take?.kind];
  const text = (asked || take?.label || "").replace(/ \(replay\)$/, "");
  return text.replace(/^./, (c) => c.toUpperCase());
}

/** A recorded take shown as if it were a finished take, so the Monitor can play it. */
export const fromRecorded = (rec) => ({
  id: rec.id, kind: rec.kind, label: rec.label, status: "succeeded", recipe: rec.recipe, outputs: rec.outputs,
  media_base: rec.media_base, created_at: rec.created_at, replay: false,
});

/**
 * Ids of takes that are recordings. In Replay every replayable take is one (the hosted copy lists its
 * recordings among its takes too); with a real backend a person's own takes are simply takes. A take made
 * by playing a recording back has an id of its own, so it is never in this set.
 */
export function recordingIds(state) {
  return state.status?.backend?.locked ? new Set(state.recorded.map((r) => r.id)) : new Set();
}

/**
 * The take a station shows: the one picked, else its newest, else a recorded take to watch.
 * `kinds` limits it to what the station is about (Direct shows Direct takes).
 */
export function focusTake(state, kinds) {
  const recordings = recordingIds(state);
  const found = (take) => ({ take, recorded: recordings.has(take.id) });
  const picked = state.takes.find((t) => t.id === state.selected);
  if (picked && kinds.includes(picked.kind)) return found(picked);
  const pickedRecording = state.recorded.find((r) => r.id === state.selected && kinds.includes(r.kind));
  if (pickedRecording) return { take: fromRecorded(pickedRecording), recorded: true };
  const latest = state.takes.find((t) => kinds.includes(t.kind));
  if (latest) return found(latest);
  const rec = state.recorded.find((r) => kinds.includes(r.kind));
  return rec ? { take: fromRecorded(rec), recorded: true } : { take: null, recorded: false };
}
