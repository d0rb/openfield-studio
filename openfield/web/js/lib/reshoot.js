// The Re-shoot form's model: validation that mirrors the server, and the multipart form it sends.

export const LIMITS = { clipMB: 200, imageMB: 20, prompt: [3, 400], text: 400, seed: 2 ** 31 - 1 };
export const CLIP_TYPES = [".mp4", ".mov", ".webm", ".mkv"];
export const IMAGE_TYPES = [".png", ".jpg", ".jpeg", ".webp"];

export function initialReshoot() {
  return { clip: null, referenceFile: null, castId: null, refIndex: 1, prompt: "", background: "", motion: "", seed: "" };
}

const extension = (name) => (name.includes(".") ? name.slice(name.lastIndexOf(".")).toLowerCase() : "");
const megabytes = (bytes) => bytes / (1024 * 1024);

/** Problems as typed: [{ field, message }]. Empty means it can be sent. */
export function validate(state) {
  const problems = [];
  const { clip, referenceFile, castId, prompt } = state;
  if (!clip) problems.push({ field: "clip", message: "Add the clip whose movement you want to keep." });
  else if (!CLIP_TYPES.includes(extension(clip.name))) problems.push({ field: "clip", message: `Use a ${CLIP_TYPES.join(", ")} file.` });
  else if (megabytes(clip.size) > LIMITS.clipMB) problems.push({ field: "clip", message: `Keep the clip under ${LIMITS.clipMB} MB.` });

  if (!referenceFile && !castId) problems.push({ field: "reference", message: "Add a reference image or pick a character." });
  else if (referenceFile && !IMAGE_TYPES.includes(extension(referenceFile.name))) {
    problems.push({ field: "reference", message: `Use a ${IMAGE_TYPES.join(", ")} image.` });
  } else if (referenceFile && megabytes(referenceFile.size) > LIMITS.imageMB) {
    problems.push({ field: "reference", message: `Keep the image under ${LIMITS.imageMB} MB.` });
  }

  const text = prompt.trim();
  if (text.length < LIMITS.prompt[0]) problems.push({ field: "prompt", message: "Describe the new character." });
  else if (text.length > LIMITS.prompt[1]) problems.push({ field: "prompt", message: `Keep it under ${LIMITS.prompt[1]} characters.` });
  if (state.background.length > LIMITS.text) problems.push({ field: "background", message: `Keep it under ${LIMITS.text} characters.` });
  if (state.motion.length > LIMITS.text) problems.push({ field: "motion", message: `Keep it under ${LIMITS.text} characters.` });

  if (state.seed !== "" && state.seed != null) {
    const seed = Number(state.seed);
    if (!Number.isInteger(seed) || seed < 0 || seed > LIMITS.seed) {
      problems.push({ field: "seed", message: `A seed is a whole number from 0 to ${LIMITS.seed}.` });
    }
  }
  return problems;
}

/** The multipart form for POST /api/takes/reshoot; empty optional fields are left out. */
export function toForm(state, FormDataImpl = globalThis.FormData) {
  const form = new FormDataImpl();
  form.append("prompt", state.prompt.trim());
  form.append("source", state.clip);
  if (state.referenceFile) form.append("reference", state.referenceFile);
  else if (state.castId) {
    form.append("cast_id", state.castId);
    form.append("ref_index", String(state.refIndex));
  }
  if (state.background.trim()) form.append("background", state.background.trim());
  if (state.motion.trim()) form.append("motion", state.motion.trim());
  if (state.seed !== "" && state.seed != null) form.append("seed", String(state.seed));
  return form;
}
