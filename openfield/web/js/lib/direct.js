// The Direct form's model: defaults, the request body, instant validation and the render estimate.
// Mirrors the server's rules so mistakes show before a request, but the server stays the authority.

import { sameRecipe } from "./format.js";

export const FALLBACK_RIG = {
  sensor: "modern_digital", lens: "clean_sharp", focal_length_mm: 35, aperture: "f4",
  lighting: "soft_cross", movement: "dolly_in", duration_seconds: 5, speed: "steady",
};
export const LIMITS = { subject: [3, 800], audio: 400, seed: 2 ** 31 - 1, focal: [8, 200], duration: [2, 10] };

export const defaultRig = (catalog) => ({ ...FALLBACK_RIG, ...(catalog?.defaults ?? {}) });

export function initialDirect(catalog) {
  return {
    subject: "",
    audio: "",
    rig: defaultRig(catalog),
    seed: "", // empty = a random seed, chosen by the server and recorded in the receipt
    orientation: "landscape",
    castId: null,
    quick: false,
    autoApprove: false,
  };
}

/** The JSON body for POST /api/takes/direct and /api/direct/plan. */
export function requestBody(state) {
  const body = {
    subject: state.subject.trim(),
    rig: state.rig,
    orientation: state.orientation,
    auto_approve: state.autoApprove,
    prompt_only: state.quick,
  };
  if (state.audio.trim()) body.audio = state.audio.trim();
  if (state.seed !== "" && state.seed != null) body.seed = Number(state.seed);
  if (state.castId) body.cast_id = state.castId;
  return body;
}

/** Problems with the form as typed: [{ field, message }]. Empty means it can be sent. */
export function validate(state, catalog) {
  const problems = [];
  const subject = state.subject.trim();
  if (subject.length < LIMITS.subject[0]) problems.push({ field: "subject", message: "Describe what is in the shot." });
  else if (subject.length > LIMITS.subject[1]) problems.push({ field: "subject", message: `Keep it under ${LIMITS.subject[1]} characters.` });
  if (state.audio.length > LIMITS.audio) problems.push({ field: "audio", message: `Keep sound under ${LIMITS.audio} characters.` });
  if (state.seed !== "" && state.seed != null) {
    const seed = Number(state.seed);
    if (!Number.isInteger(seed) || seed < 0 || seed > LIMITS.seed) {
      problems.push({ field: "seed", message: `A seed is a whole number from 0 to ${LIMITS.seed}.` });
    }
  }
  const { rig } = state;
  const options = catalog?.options ?? {};
  for (const key of ["sensor", "lens", "aperture", "lighting", "speed"]) {
    if (options[key] && !options[key].includes(rig[key])) problems.push({ field: key, message: `Pick a ${key}.` });
  }
  if (catalog && !catalog.moves.some((m) => m.id === rig.movement)) problems.push({ field: "movement", message: "Pick a camera move." });
  const [lo, hi] = catalog?.limits?.focal_length_mm ?? LIMITS.focal;
  if (!Number.isInteger(rig.focal_length_mm) || rig.focal_length_mm < lo || rig.focal_length_mm > hi) {
    problems.push({ field: "focal_length_mm", message: `Focal length is ${lo} to ${hi} mm.` });
  }
  const [dMin, dMax] = catalog?.limits?.duration_seconds ?? LIMITS.duration;
  if (!Number.isInteger(rig.duration_seconds) || rig.duration_seconds < dMin || rig.duration_seconds > dMax) {
    problems.push({ field: "duration_seconds", message: `Length is ${dMin} to ${dMax} seconds.` });
  }
  return problems;
}

const roundHalfEven = (x) => {
  const floor = Math.floor(x);
  const diff = x - floor;
  if (diff !== 0.5) return Math.round(x);
  return floor % 2 === 0 ? floor : floor + 1; // Python's round(): 2.5 -> 2, 3.5 -> 4
};

/**
 * The shot plan for a move and a length, worked out in the browser so the plan line stays live without
 * a server (the hosted Replay has none). Mirrors engine/rig.py compile_shot; a fixture test keeps them equal.
 */
export function estimatePlan(move, durationSeconds, quick = false) {
  const keyframed = move.mode === "keyframed" && !quick;
  const anchors = [{ index: 0, role: "hero" }];
  if (!keyframed) {
    return { mode: quick && move.mode === "keyframed" ? "prompt_only" : move.mode, anchors, segments: [{ index: 0, seconds: durationSeconds }], total_seconds: durationSeconds, notes: [] };
  }
  for (let i = 1; i < move.anchors; i += 1) {
    anchors.push({ index: i, role: move.id === "orbit_360" && i === move.anchors - 1 ? "repeat_hero" : "edit" });
  }
  const count = move.anchors - 1;
  const per = Math.max(2, roundHalfEven(durationSeconds / count));
  const total = per * count;
  const notes = total === durationSeconds ? [] : [`${count} shot${count === 1 ? "" : "s"} of ${per} s make ${total} s, not ${durationSeconds} s`];
  return { mode: "keyframed", anchors, segments: Array.from({ length: count }, (_, index) => ({ index, seconds: per })), total_seconds: total, notes };
}

const OPTION_LABELS = {
  "35mm_film": "35mm film", "8mm_film": "8mm film", dv_camcorder: "DV camcorder", clean_sharp: "Clean, sharp",
  contre_jour: "Contre-jour", "f1.4": "f/1.4", f4: "f/4", f11: "f/11",
};

/** "vintage_anamorphic" -> "Vintage anamorphic"; a few are written by hand. */
export function optionLabel(id) {
  if (OPTION_LABELS[id]) return OPTION_LABELS[id];
  const words = String(id).replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The recipe a form would send, in the shape recorded takes keep, for comparing with recordings. */
const core = (r) => ({
  subject: (r.subject ?? "").trim(), rig: r.rig ?? {}, audio: (r.audio ?? "").trim(),
  seed: r.seed ?? null, orientation: r.orientation ?? "landscape", prompt_only: Boolean(r.prompt_only),
});

export const formRecipe = (state) => core({
  subject: state.subject, rig: state.rig, audio: state.audio, seed: state.seed === "" || state.seed == null ? null : Number(state.seed),
  orientation: state.orientation, prompt_only: state.quick,
});

/**
 * Whether a recorded take is exactly this shot, so Replay can stand in for a render. The server has the
 * last word (it compares a fingerprint); this only decides which button to offer.
 */
export function matchesRecording(state, recorded, castName = null) {
  if (recorded?.kind !== "direct" || !recorded.recipe) return false;
  return sameRecipe(formRecipe(state), core(recorded.recipe)) && (recorded.recipe.cast_name ?? null) === (castName ?? null);
}

/** How many ComfyUI renders a plan will make, split by what they cost most. */
export function renderEstimate(plan) {
  const stills = plan.anchors.length; // hero + one edit per extra anchor ("repeat_hero" reuses the hero)
  const reused = plan.anchors.filter((a) => a.role === "repeat_hero").length;
  const videos = plan.segments.length;
  return { stills: stills - reused, videos, total: stills - reused + videos, seconds: plan.total_seconds };
}

/** One readable line for the plan preview. */
export function planSummary(plan) {
  const { stills, videos, seconds } = renderEstimate(plan);
  const parts = [`${stills} still${stills === 1 ? "" : "s"}`, `${videos} shot${videos === 1 ? "" : "s"}`, `${seconds} s`];
  return parts.join(", ");
}

/** Load a recipe (from an imported receipt or a recorded take) back into the form. */
export function fromRecipe(recipe, catalog) {
  const state = initialDirect(catalog);
  state.subject = recipe.subject ?? "";
  state.audio = recipe.audio ?? "";
  state.rig = { ...state.rig, ...(recipe.rig ?? {}) };
  state.seed = recipe.seed ?? "";
  state.orientation = recipe.orientation ?? "landscape";
  state.quick = Boolean(recipe.prompt_only);
  return state;
}
