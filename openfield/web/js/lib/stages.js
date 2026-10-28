// What the Monitor says about a take in flight: the steps it will go through and where it is now.
// Pure functions over the take, the move catalog and the live state from live.js.

import { posterSet } from "./pictures.js";
import { ANGLE_DEFAULT, effectKind, estimatePlan } from "./direct.js";

const step = (id, name) => ({ id, name: name ?? stepName(id) });

/** A take whose hero still is the person's own image (nothing was rendered for it). */
export const sourced = (take) => Boolean(take?.recipe?.source_sha256);

/** Short names for the rail ("Hero still", "Anchor 1", "End state", "Shot 2"). */
export function stepName(id) {
  const fixed = { hero: "Hero still", angle: "Angled still", review: "Approve", finish: "Finish", prepare: "Prepare clip", motion: "Motion transfer", replay: "Replay",
    bridge: "Bridge", source: "Source still", face: "Face swap", edit: "Edit", extend: "Extension", upscale: "Upscale" };
  if (fixed[id]) return fixed[id];
  const numbered = /^(anchor|shoot|candidate|transform|shot)_(\d+)$/.exec(id);
  if (numbered) return numbered[1] === "transform" ? "End state" : `${{ anchor: "Anchor", shoot: "Shot", candidate: "Portrait", shot: "Setup" }[numbered[1]]} ${numbered[2]}`;
  const retried = /^(.+)_retry$/.exec(id); // the one re-roll a drifted or doubled still gets
  if (retried) return `${stepName(retried[1])}, re-rolled`;
  return id.replace(/_/g, " ");
}

/** The steps a take will go through, in order. The approval step is a pause, not a render. */
export function stageList(take, catalog) {
  const recipe = take?.recipe ?? {};
  switch (take?.kind) {
    case "reshoot":
      return recipe.face_only ? [step("prepare"), step("face"), step("motion"), step("finish")] : [step("prepare"), step("motion"), step("finish")];
    case "transition":
      return [step("prepare", "Prepare frames"), step("bridge"), step("finish")];
    case "shots":
      return [step("source"), ...Array.from({ length: recipe.board?.length || catalog?.shots?.board?.length || 9 }, (_, i) => step(`shot_${i + 1}`)), step("finish")];
    case "edit":
      return [step("source"), step("edit"), step("finish")];
    case "extend":
      return [step("prepare", "Last frame"), step("extend"), step("finish")];
    case "upscale":
      return [step("upscale"), step("finish")];
    case "portrait":
      return [...Array.from({ length: recipe.count ?? 3 }, (_, i) => step(`candidate_${i + 1}`)), step("finish")];
    case "direct": {
      const move = catalog?.moves?.find((m) => m.id === recipe.rig?.movement);
      if (!move) return [step("hero", sourced(take) ? "Your photo" : undefined), step("review"), step("shoot_1", "Shoot"), step("finish")];
      const plan = estimatePlan(move, recipe.rig.duration_seconds, recipe.prompt_only, { effectKind: effectKind(catalog, recipe.rig.effect), singlePass: Boolean(recipe.single_pass) });
      const list = [step("hero", sourced(take) ? "Your photo" : undefined)];
      if (recipe.rig?.angle && recipe.rig.angle !== ANGLE_DEFAULT) list.push(step("angle")); // the hero re-shot from the angle
      for (const anchor of plan.anchors) {
        if (anchor.role === "edit") list.push(step(`anchor_${anchor.index}`));
        else if (anchor.role === "transform") list.push(step(`transform_${anchor.index}`));
      }
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

/** A take's small picture for a tile or a card: the preview builder's first-frame JPEG (a few KB) when it cut one,
 * else the full poster (often a megabyte or more). Empty when the take has neither. */
export function thumbOf(state, take, api) {
  const small = take ? state?.previews?.takes?.[take.replay_of ?? take.id]?.poster : null;
  if (small && api?.asset) return api.asset(small);
  const file = fileOf(take, "poster");
  return file ? api.media(take, file) : "";
}

/** The attributes of a take's poster <img> drawn `sizes` wide (a CSS sizes value, "96px" or a media list): src, srcset over the
 * preview copies (lib/pictures.js picks by width and density; a phone is offered the small ones) and sizes, with async decoding;
 * a take with no previews gets its full poster, and a take with neither gets null. */
export function posterAttrs(state, take, api, sizes) {
  const entry = take ? state?.previews?.takes?.[take.replay_of ?? take.id] : null;
  const set = entry && api?.asset ? posterSet(entry, sizes, (path) => api.asset(path)) : null;
  if (set) return { src: set.src, srcset: set.srcset, sizes: set.sizes, decoding: "async" };
  const file = fileOf(take, "poster");
  return file ? { src: api.media(take, file), decoding: "async" } : null;
}

/** Put `posterAttrs` on an <img> that may be reused for another take (a list row, a strip tile): nothing is touched while the
 * picture is the same, a srcset left by the take before never outlives it (it would win over the new src), and a take with no
 * picture hides the image. `src` goes last, so the browser picks once. */
export function setPoster(img, attrs) {
  img.hidden = !attrs;
  if (!attrs) return;
  if (img.getAttribute("src") === attrs.src && (img.getAttribute("srcset") ?? null) === (attrs.srcset ?? null)) return;
  for (const name of ["srcset", "sizes"]) {
    if (attrs[name]) img.setAttribute(name, attrs[name]);
    else img.removeAttribute(name);
  }
  img.setAttribute("decoding", attrs.decoding ?? "async");
  img.setAttribute("src", attrs.src);
}

/** One of a take's stills, small enough for a card: the copy the preview builder cut, else the still itself. */
export function stillThumb(state, take, file, api) {
  const small = take && file ? state?.previews?.takes?.[take.replay_of ?? take.id]?.stills?.[file] : null;
  return small && api?.asset ? api.asset(small) : api.media(take, file);
}

/** What a take is called on screen: what was asked for, in full, not the server's shortened label. */
export function titleOf(take) {
  const r = take?.recipe ?? {};
  const asked = { direct: r.subject, reshoot: r.prompt, portrait: r.description }[take?.kind];
  let text = (asked || take?.label || "").replace(/ \(replay\)$/, "");
  // the server cuts a label's words at 48 characters: end a cut one on a whole word, with an ellipsis
  const cut = !asked && /^([^:]{1,24}: )(.{48})$/.exec(text);
  if (cut && !/[.!?…]$/.test(cut[2])) text = `${cut[1]}${cut[2].replace(/\s+\S*$/, "")}…`;
  return text.replace(/^./, (c) => c.toUpperCase());
}

/** A recorded take shown as if it were a finished take, so the Monitor can play it. */
export const fromRecorded = (rec) => ({
  id: rec.id, kind: rec.kind, label: rec.label, status: "succeeded", recipe: rec.recipe, outputs: rec.outputs,
  media_base: rec.media_base, created_at: rec.created_at, replay: false, ...(rec.recipe_hash ? { recipe_hash: rec.recipe_hash } : {}),
  ...(rec.identity ? { identity: rec.identity } : {}), ...(rec.audit ? { audit: rec.audit } : {}), ...(rec.notes ? { notes: rec.notes } : {}),
  ...(rec.seconds ? { seconds: rec.seconds } : {}), ...(rec.shots ? { shots: rec.shots, board: rec.board } : {}), ...(rec.edit ? { edit: rec.edit } : {}),
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

/**
 * The stills a take rendered on its way to the shot, from its receipt: the hero and the anchors as the approved files
 * (a re-roll is resolved to the still that was kept, named "re-rolled"), then the shot, each with its identity report.
 */
export function stageStrip(take, receipt) {
  const identity = take?.identity ?? {};
  const edit = take?.edit; // an edit: its still before and after
  if (edit?.after) return [{ id: "before", name: "Before", file: edit.before, report: null }, { id: "edit", name: "After", file: edit.after, report: identity.edit ?? null }];
  const items = (receipt?.inputs?.anchors ?? []).map((a) => {
    const stage = /^runs\/\d+_([^/]+)\//.exec(a.file ?? "")?.[1] ?? (a.index === 0 ? "hero" : `anchor_${a.index}`);
    const name = stage === "hero" && (sourced(take) || /^inputs\//.test(a.file ?? "")) ? "Your photo" : stepName(stage);
    return { id: stage, name, file: a.file, report: identity[stage] ?? null, approved: true };
  });
  const poster = fileOf(take, "poster");
  if (items.length && poster) {
    const shot = Object.keys(identity).find((k) => /^shoot_/.test(k));
    items.push({ id: "shot", name: "Shot", file: poster, report: shot ? identity[shot] : null, approved: false });
  }
  return items;
}

/** The newest finished Direct take that shows a camera move (recordings included), so a tile or card can play it. */
const samplePool = (state) => [...(state.takes ?? []), ...(state.recorded ?? []).map((r) => (r.status ? r : fromRecorded(r)))];
const shows = (t, movement) => t.kind === "direct" && t.status === "succeeded" && t.recipe?.rig?.movement === movement && Boolean(fileOf(t, "video"));

/** The subject line the moves sheet is built from: the one with a finished take under the most of these moves (newest wins a tie). */
export function sheetSubject(state, movements) {
  const seen = new Map();
  for (const t of samplePool(state)) {
    const subject = t.recipe?.subject;
    if (!subject || !movements.some((m) => shows(t, m))) continue;
    if (!seen.has(subject)) seen.set(subject, new Set());
    seen.get(subject).add(t.recipe.rig.movement);
  }
  let best = null;
  for (const [subject, moves] of seen) if (!best || moves.size > best[1].size) best = [subject, moves];
  return best ? best[0] : null;
}

/**
 * The recorded angles of one subject, for the Angles sheet: the subject with the most distinct camera positions, each
 * with its newest finished take, in the order of the catalog's dials (around, then height, then distance).
 */
export function angleSheet(state, catalog) {
  const a = catalog?.angles;
  if (!a) return [];
  const bySubject = new Map();
  for (const t of samplePool(state)) { // newest first, so the first take seen for an angle is the one kept
    const angle = t.recipe?.rig?.angle;
    if (t.kind !== "direct" || t.status !== "succeeded" || !angle || angle === a.default || !fileOf(t, "video")) continue;
    if (!bySubject.has(t.recipe.subject)) bySubject.set(t.recipe.subject, new Map());
    const seen = bySubject.get(t.recipe.subject);
    if (!seen.has(angle)) seen.set(angle, t);
  }
  let best = null;
  for (const entry of bySubject) if (!best || entry[1].size > best[1].size) best = entry;
  if (!best) return [];
  const rank = (id) => {
    const [az, el, d] = id.split("/");
    return [a.azimuths.findIndex((s) => s.id === az), a.elevations.findIndex((s) => s.id === el), a.distances.findIndex((s) => s.id === d)];
  };
  return [...best[1]].map(([angle, take]) => ({ angle, take }))
    .sort((p, q) => { const [x, y] = [rank(p.angle), rank(q.angle)]; return x[0] - y[0] || x[1] - y[1] || x[2] - y[2]; });
}

/** The newest finished Direct take that shows a move; given a subject line, the newest one with that subject first. */
export function sampleTake(state, movement, { subject = null } = {}) {
  const pool = samplePool(state);
  return (subject && pool.find((t) => shows(t, movement) && t.recipe?.subject === subject)) || pool.find((t) => shows(t, movement)) || null;
}
