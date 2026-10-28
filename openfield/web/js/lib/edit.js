// The take-from-a-take sheets as data (Edit with words, Dub, Transition, Extend, Upscale): what each sends, and the
// recording Replay plays instead. (The fields' maxlength keeps the words within the catalog's limits.)

import { sameRecipe, squash } from "./format.js";
import { fileOf } from "./stages.js";

const idsOf = (take) => [take?.id, take?.replay_of].filter(Boolean);
const editWords = (form) => squash(form.detail) || (form.preset === "relight" ? form.light ?? "" : ""); // or Relight's light id

/** A preset of the catalog's edits, or null. */
export const editPreset = (catalog, id) => catalog?.edits?.presets?.find((p) => p.id === id) ?? null;

export function editProblem(form, catalog) {
  const preset = editPreset(catalog, form.preset);
  if (!preset) return "Pick an edit.";
  if (preset.needs_cast && !form.castId) return "Pick a character from Cast.";
  return preset.needs_detail && !editWords(form) ? "Say what to change." : null;
}

/** The JSON `request` for POST /api/takes/edit. */
export function editRequest(form, catalog) {
  const preset = editPreset(catalog, form.preset);
  const body = { preset: form.preset };
  if (preset?.needs_detail && editWords(form)) body.detail = editWords(form);
  if (form.take) body.take = form.take;
  if (form.still) body.still = form.still;
  if (preset?.needs_cast && form.castId) body.cast_id = form.castId;
  if (form.seed !== "" && form.seed != null) body.seed = Number(form.seed);
  return body;
}

/** The recorded edit of this still (none: the take's first) with this preset, or null. */
export const recordedEdit = (recorded, take, preset, still = null) => (recorded ?? []).find((r) => r.kind === "edit"
  && idsOf(take).includes(r.recipe?.take) && r.recipe?.preset === preset && (r.recipe?.still ?? null) === (still ?? null)) ?? null;

/** Where a dub starts: the hero before any angle (the rig re-shoots it), else the first approved still, else the poster. */
export const heroStill = (take, receipt) => receipt?.inputs?.angle?.source_file ?? receipt?.inputs?.anchors?.[0]?.file ?? fileOf(take, "poster");

export const dubProblem = ({ line, language }) => (!squash(language) ? "Name the language of the new line." : squash(line) ? null : "Write the line in that language.");

/** The Direct body for a dub: the take's subject, rig, seed and sound with the new line, its stills approved. */
export function dubRequest(recipe, { line, language }) {
  const body = { subject: recipe.subject, rig: recipe.rig, orientation: recipe.orientation ?? "landscape", auto_approve: true, line: squash(line), delivery: recipe.delivery || "natural" };
  if (squash(language)) body.language = squash(language);
  if (recipe.seed != null) body.seed = recipe.seed;
  if (recipe.audio) body.audio = recipe.audio;
  if (recipe.action) body.action = recipe.action;
  if (recipe.quality) body.quality = recipe.quality;
  if (recipe.prompt_only) body.prompt_only = true; // a quick take stays quick
  return body;
}

/** Recorded talking takes of this subject and rig (as the server records both) in a named language, this take aside. */
export const recordedDubs = (recorded, take) => (recorded ?? []).filter((r) => r.kind === "direct" && !idsOf(take).includes(r.id)
  && r.recipe?.line && squash(r.recipe.language) && r.recipe.subject === take.recipe?.subject && sameRecipe(r.recipe.rig, take.recipe?.rig));

export const dubIn = (dubs, language) => dubs.find((r) => squash(r.recipe.language).toLowerCase() === squash(language).toLowerCase()) ?? null;

/** The transition body: the idea only when there is one, tidied as the server keeps it. */
const ideaOf = (idea) => squash(idea).replace(/\.+$/, ""); // rig.transition_idea drops closing stops
export const bridgeRequest = ({ first, second, style, seconds, idea }) => ({ first, second, style, seconds, ...(ideaOf(idea) ? { idea: ideaOf(idea) } : {}) });

/** The recorded bridge of this pair, style, length and idea (none matches none), or null. */
export const recordedBridge = (recorded, form) => (recorded ?? []).find((r) => r.kind === "transition" && sameRecipe(bridgeRequest(r.recipe ?? {}), bridgeRequest(form))) ?? null;

/** The recorded extension of this take (a replay: of its recording) by these seconds, or upscale to this target. */
const recordedFrom = (kind, key) => (recorded, take, value) => (recorded ?? []).find((r) => r.kind === kind
  && idsOf(take).includes(r.recipe?.take) && r.recipe?.[key] === value) ?? null;
export const recordedExtend = recordedFrom("extend", "seconds");
export const recordedUpscale = recordedFrom("upscale", "target");

/** The takes the dock offers to upscale: never an upscale, which the server refuses to enlarge again. */
export const upscalable = (take) => ["direct", "reshoot", "transition", "extend"].includes(take?.kind);
