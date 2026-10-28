// The Direct form's model: defaults, the request body, instant validation and the render estimate.
// Mirrors the server's rules so mistakes show before a request, but the server stays the authority.

import { gpuCost } from "./billing.js";
import { sameRecipe, squash } from "./format.js";

export const FALLBACK_RIG = {
  sensor: "modern_digital", lens: "clean_sharp", focal_length_mm: 35, aperture: "f4",
  lighting: "soft_cross", movement: "dolly_in", duration_seconds: 5, speed: "steady",
};
export const LIMITS = { subject: [3, 800], audio: 400, line: 200, language: 40, action: [3, 300], seed: 2 ** 31 - 1, focal: [8, 200], duration: [2, 10] };
export const DELIVERY_DEFAULT = "natural";

export const defaultRig = (catalog) => ({ ...FALLBACK_RIG, ...(catalog?.defaults ?? {}) });

export function initialDirect(catalog) {
  return {
    subject: "",
    action: "", // what happens: in the video prompt only
    audio: "",
    line: "", // a spoken line: LTX 2.5 writes the voice with the picture when the prompt quotes it
    delivery: DELIVERY_DEFAULT,
    language: "", // empty: LTX assumes English
    rig: defaultRig(catalog),
    seed: "", // empty = a random seed, chosen by the server and recorded in the receipt
    orientation: "landscape",
    castId: null,
    quick: false,
    autoApprove: false,
    heroMode: "prompt", // prompt | image: the hero still is rendered from the text, or it is the person's own image
    sourceFile: null, // the image, when heroMode is "image" (a File; never part of a recipe link)
    quality: "standard", // draft | standard | fine: sizes and still steps (the catalog says what each changes)
  };
}

export const QUALITY_DEFAULT = "standard";

/** The longest action the server takes. */
export const actionMax = (catalog) => catalog?.direct?.action_max ?? catalog?.action_max ?? LIMITS.action[1];

/** The plan's quiet line when an action meets a keyframed move (quick mode off), else null. */
export function actionNote(state, catalog) {
  const move = catalog?.moves?.find((m) => m.id === state?.rig?.movement);
  if (move?.reversed) return `${move.label} is played backwards. Your still ends the shot.`;
  if (!squash(state?.action)) return null;
  if (move?.frozen) return `${move.label} freezes the action at its peak.`;
  if (move?.mode !== "keyframed" || state.quick) return null;
  return `The stills share one moment. The action may barely move.`;
}

/** What a tier changes, from the catalog; null for an unknown tier. */
export function describeQuality(catalog, tier) {
  return (catalog?.quality ?? []).find((q) => q.id === tier) ?? null;
}

/** The spoken-line controls from the catalog: the deliveries to pick from, the limits, and whether a render checked it. */
export function describeDialogue(catalog) {
  const d = catalog?.dialogue ?? { deliveries: [{ id: DELIVERY_DEFAULT, label: "Natural" }], tested: false };
  return {
    deliveries: d.deliveries ?? [],
    maxChars: d.max_chars ?? LIMITS.line,
    tested: Boolean(d.tested),
  };
}

/** One line for the plan: a measured time on this backend, or the honest absence of one. */
export function estimateLine(estimate) {
  if (!estimate) return null; // not asked yet, or not answered: nothing is shown rather than a guess
  if (estimate.samples === 0 || estimate.seconds == null) {
    return estimate.basis === "Replay renders nothing" ? null : "No time measured yet on this backend";
  }
  const s = Math.round(estimate.seconds);
  const clock = s >= 60 ? `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s` : `${s} s`;
  const cost = gpuCost(estimate.seconds); // the price before the click, at the rate every receipt is priced at
  return `≈ ${clock}${cost ? `, about ${cost}` : ""}, measured here (${estimate.samples} take${estimate.samples === 1 ? "" : "s"})`;
}

/**
 * An effect from the catalog with its kind: "prompt" (one sentence on the shot) or "keyframed" (the last still is edited
 * into the end state and LTX renders the change). Null for none or an unknown id.
 */
export function describeEffect(catalog, id) {
  if (!id || id === "none") return null;
  return (catalog?.effects ?? []).find((e) => e.id === id) ?? null;
}

export const effectKind = (catalog, id) => describeEffect(catalog, id)?.kind ?? null;

export const ANGLE_DEFAULT = "front/eye/medium"; // the hero as shot (engine/rig.py ANGLE_DEFAULT); left out of recipes

/** The three stops of an angle id ("azimuth/height/distance") from the catalog; null at the default or for an unknown id. */
export function angleStops(catalog, id) {
  const a = catalog?.angles;
  if (!a || !id || id === (a.default ?? ANGLE_DEFAULT)) return null;
  const [az, el, dist] = String(id).split("/");
  const stop = (list, key) => (list ?? []).find((s) => s.id === key) ?? null;
  const found = [stop(a.azimuths, az), stop(a.elevations, el), stop(a.distances, dist)];
  return found.every(Boolean) ? { azimuth: found[0], elevation: found[1], distance: found[2] } : null;
}

/** "Back-left quarter · Low angle · Wide", or null when the camera starts where the hero was shot. */
export function describeAngle(catalog, id) {
  const s = angleStops(catalog, id);
  return s ? `${s.azimuth.label} · ${s.elevation.label} · ${s.distance.label}` : null;
}

/** The numbers the stage pivots by for an angle id, or null at the default. */
export function angleGeometry(catalog, id) {
  const s = angleStops(catalog, id);
  return s ? { azimuth: s.azimuth.degrees, elevation: s.elevation.degrees, distance: s.distance.scale } : null;
}

/** Whether a shot from this form renders its stills in one LTX pass: three or more stills, not quick, and the catalog says so. */
export function onePass(state, catalog) {
  if (!catalog?.single_pass) return false;
  const move = catalog.moves?.find((m) => m.id === state?.rig?.movement);
  if (state?.quick && !move?.frozen) return false;
  return Boolean(move && move.mode === "keyframed" && move.anchors >= 3);
}

export const IMAGE_TYPES = [".png", ".jpg", ".jpeg", ".webp"];
export const IMAGE_MB = 20;
const extension = (name) => (name.includes(".") ? name.slice(name.lastIndexOf(".")).toLowerCase() : "");

/** Whether the form starts from the person's own image. */
export const fromImage = (state) => state.heroMode === "image";

/** The multipart form for POST /api/takes/direct/from-image: the JSON body as `request`, the image as `source`. */
export function toImageForm(state, FormDataImpl = globalThis.FormData) {
  const form = new FormDataImpl();
  form.append("request", JSON.stringify(requestBody(state)));
  form.append("source", state.sourceFile);
  return form;
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
  if (squash(state.action)) body.action = squash(state.action);
  if ((state.line ?? "").trim()) { // a spoken line travels with its delivery; the language only when named
    body.line = state.line.trim();
    body.delivery = state.delivery || DELIVERY_DEFAULT;
    if ((state.language ?? "").trim()) body.language = state.language.trim();
  }
  if (state.seed !== "" && state.seed != null) body.seed = Number(state.seed);
  if (state.castId) body.cast_id = state.castId;
  if (state.quality && state.quality !== QUALITY_DEFAULT) body.quality = state.quality; // standard is the server's default
  return body;
}

/** Problems with the form as typed: [{ field, message }]. Empty means it can be sent. */
export function validate(state, catalog) {
  const problems = [];
  const subject = state.subject.trim();
  if (subject.length < LIMITS.subject[0]) problems.push({ field: "subject", message: "Describe what is in the shot." });
  else if (subject.length > LIMITS.subject[1]) problems.push({ field: "subject", message: `Keep it under ${LIMITS.subject[1]} characters.` });
  if (state.audio.length > LIMITS.audio) problems.push({ field: "audio", message: `Keep sound under ${LIMITS.audio} characters.` });
  const action = squash(state.action).length;
  if (action && (action < LIMITS.action[0] || action > actionMax(catalog))) problems.push({ field: "action", message: `Say what happens in ${LIMITS.action[0]} to ${actionMax(catalog)} characters, or leave it empty.` });
  // a move played backwards (through object, pedestal down) takes nothing that would run backwards with it
  const move = catalog?.moves?.find((m) => m.id === state.rig?.movement);
  if (move?.reversed) {
    const made = `${move.label} is played backwards`;
    if (action) problems.push({ field: "action", message: `${made}, so leave What happens empty.` });
    if ((state.line ?? "").trim()) problems.push({ field: "line", message: `${made}, so leave Line empty.` });
    if (state.rig?.effect && state.rig.effect !== "none") problems.push({ field: "effect", message: `${made}, so set Effect to None.` });
  }
  const dialogue = describeDialogue(catalog);
  if ((state.line ?? "").trim().length > dialogue.maxChars) problems.push({ field: "line", message: `Keep the line under ${dialogue.maxChars} characters.` });
  if ((state.line ?? "").trim() && dialogue.deliveries.length && !dialogue.deliveries.some((d) => d.id === (state.delivery || DELIVERY_DEFAULT))) {
    problems.push({ field: "delivery", message: "Pick a delivery." });
  }
  if ((state.language ?? "").trim().length > LIMITS.language) problems.push({ field: "language", message: `Keep the language under ${LIMITS.language} characters.` });
  if (state.seed !== "" && state.seed != null) {
    const seed = Number(state.seed);
    if (!Number.isInteger(seed) || seed < 0 || seed > LIMITS.seed) {
      problems.push({ field: "seed", message: `A seed is a whole number from 0 to ${LIMITS.seed}.` });
    }
  }
  const { rig } = state;
  const options = catalog?.options ?? {};
  for (const key of ["sensor", "lens", "aperture", "lighting", "speed", "effect", "grade", "score", "soundscape"]) {
    const value = ["effect", "grade", "score", "soundscape"].includes(key) ? rig[key] ?? "none" : rig[key]; // presets default to "none"
    if (options[key] && !options[key].includes(value)) problems.push({ field: key, message: `Pick a ${key}.` });
  }
  if (catalog && !catalog.moves.some((m) => m.id === rig.movement)) problems.push({ field: "movement", message: "Pick a camera move." });
  const chosen = catalog?.moves?.find((m) => m.id === rig.movement);
  if (chosen?.frozen && (rig.angle ?? ANGLE_DEFAULT) !== ANGLE_DEFAULT) problems.push({ field: "angle", message: `${chosen.label} needs the camera as shot.` });
  if (catalog?.angles && (rig.angle ?? ANGLE_DEFAULT) !== (catalog.angles.default ?? ANGLE_DEFAULT) && !angleStops(catalog, rig.angle)) {
    problems.push({ field: "angle", message: "Pick an angle." });
  }
  if (catalog?.quality && !catalog.quality.some((q) => q.id === (state.quality ?? QUALITY_DEFAULT))) problems.push({ field: "quality", message: "Pick a quality." });
  if (fromImage(state)) {
    const file = state.sourceFile;
    if (!file) problems.push({ field: "source", message: "Add the image the shot starts from." });
    else if (!IMAGE_TYPES.includes(extension(file.name))) problems.push({ field: "source", message: `Use a ${IMAGE_TYPES.join(", ")} image.` });
    else if (file.size > IMAGE_MB * 1024 * 1024) problems.push({ field: "source", message: `Keep the image under ${IMAGE_MB} MB.` });
  }
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
export function estimatePlan(move, durationSeconds, quick = false, { effectKind: kind = null, singlePass = false } = {}) {
  const keyframed = move.mode === "keyframed" && !(quick && !move.frozen); // a frozen move has no quick form
  const transform = kind === "keyframed"; // the last still is edited into the end state
  const anchors = [{ index: 0, role: "hero" }];
  if (!keyframed) {
    if (transform) anchors.push({ index: 1, role: "transform" });
    return { mode: quick && move.mode === "keyframed" ? "prompt_only" : move.mode, anchors, segments: [{ index: 0, seconds: durationSeconds }], total_seconds: durationSeconds, notes: [] };
  }
  for (let i = 1; i < move.anchors; i += 1) {
    anchors.push({ index: i, role: ["orbit_360", "loop"].includes(move.id) && i === move.anchors - 1 ? "repeat_hero" : "edit" });
  }
  if (transform) anchors[anchors.length - 1] = { index: anchors.length - 1, role: "transform" };
  const count = move.anchors - 1;
  if (singlePass && count >= 2) { // one LTX pass with the middle stills guided inside it
    return { mode: "keyframed", anchors, segments: [{ index: 0, seconds: durationSeconds }], total_seconds: durationSeconds, notes: [] };
  }
  const per = Math.max(2, roundHalfEven(durationSeconds / count));
  const total = per * count;
  const notes = total === durationSeconds ? [] : [`${count} shot${count === 1 ? "" : "s"} of ${per} s make ${total} s, not ${durationSeconds} s`];
  return { mode: "keyframed", anchors, segments: Array.from({ length: count }, (_, index) => ({ index, seconds: per })), total_seconds: total, notes };
}

const OPTION_LABELS = {
  "35mm_film": "35mm film", "8mm_film": "8mm film", dv_camcorder: "DV camcorder", clean_sharp: "Clean, sharp",
  contre_jour: "Contre-jour", "f1.4": "f/1.4", f4: "f/4", f11: "f/11",
  teal_orange: "Teal and orange", bleach_bypass: "Bleach bypass", noir_mono: "Noir monochrome", cross_process: "Cross-processed",
  solo_piano: "Solo piano", strings: "Strings", synth_pulse: "Synth pulse", drone: "Drone",
  acoustic_guitar: "Acoustic guitar", no_music: "No music",
  harbour: "Harbour", city_night: "City at night", rain_on_glass: "Rain on glass", forest: "Forest",
  interior_quiet: "Quiet interior", silence: "Silence",
};

/** "vintage_anamorphic" -> "Vintage anamorphic"; a few are written by hand. */
export function optionLabel(id) {
  if (OPTION_LABELS[id]) return OPTION_LABELS[id];
  const words = String(id).replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * A rig as a recipe records it: a preset at its default ("none" for effect and grade) is left out, exactly as the server's
 * recipe_rig does, so recordings made before the preset existed still match.
 */
export function recipeRig(rig) {
  const { effect, grade, score, soundscape, angle, ...rest } = rig ?? {};
  const out = { ...rest };
  if (effect && effect !== "none") out.effect = effect;
  if (grade && grade !== "none") out.grade = grade;
  if (score && score !== "none") out.score = score;
  if (soundscape && soundscape !== "none") out.soundscape = soundscape;
  if (angle && angle !== ANGLE_DEFAULT) out.angle = angle;
  return out;
}

// a line as rig.dialogue_plan keeps it: whitespace collapsed, quotes stripped
const spoken = (text) => squash(text).replace(/^"+|"+$/g, "").replace(/^[“”]+|[“”]+$/g, "").replace(/^"+|"+$/g, "");

/**
 * The recipe a form would send, in the shape recorded takes keep, for comparing with recordings. A sourced hero is
 * part of it: a form with an image never matches a recording, and a form without one never matches a sourced recording.
 * A one-pass shot is part of it too: it is a different recording from its segmented twin.
 */
const core = (r) => {
  const line = spoken(r.line); // a spoken line is in a recipe only when there is one; silent recipes carry nothing
  const action = squash(r.action); // the same for what happens, tidied as the server keeps it
  return {
    subject: (r.subject ?? "").trim(), rig: recipeRig(r.rig), audio: (r.audio ?? "").trim(),
    seed: r.seed ?? null, orientation: r.orientation ?? "landscape", prompt_only: Boolean(r.prompt_only),
    source_sha256: r.source_sha256 ?? null, quality: r.quality ?? QUALITY_DEFAULT, single_pass: Boolean(r.single_pass),
    line, delivery: line ? r.delivery || DELIVERY_DEFAULT : DELIVERY_DEFAULT, language: line ? squash(r.language) : "",
    ...(action ? { action } : {}),
  };
};

export const formRecipe = (state, catalog = null) => core({
  subject: state.subject, rig: state.rig, audio: state.audio, seed: state.seed === "" || state.seed == null ? null : Number(state.seed),
  orientation: state.orientation, prompt_only: state.quick, source_sha256: fromImage(state) ? "upload" : null, quality: state.quality,
  single_pass: onePass(state, catalog), line: state.line, delivery: state.delivery, language: state.language, action: state.action,
});

/**
 * Whether a recorded take is exactly this shot, so Replay can stand in for a render. The server has the
 * last word (it compares a fingerprint); this only decides which button to offer.
 */
export function matchesRecording(state, recorded, castName = null, catalog = null) {
  if (recorded?.kind !== "direct" || !recorded.recipe) return false;
  return sameRecipe(formRecipe(state, catalog), core(recorded.recipe)) && (recorded.recipe.cast_name ?? null) === (castName ?? null);
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
  state.action = recipe.action ?? "";
  state.audio = recipe.audio ?? "";
  state.line = recipe.line ?? "";
  state.delivery = recipe.line ? recipe.delivery || DELIVERY_DEFAULT : DELIVERY_DEFAULT;
  state.language = recipe.line ? recipe.language ?? "" : "";
  state.rig = { ...state.rig, ...(recipe.rig ?? {}) };
  state.seed = recipe.seed ?? "";
  state.orientation = recipe.orientation ?? "landscape";
  state.quick = Boolean(recipe.prompt_only);
  state.heroMode = recipe.source_sha256 || recipe.source ? "image" : "prompt"; // the image itself must be added again
  state.sourceFile = null;
  state.quality = typeof recipe.quality === "string" ? recipe.quality : QUALITY_DEFAULT;
  return state;
}
