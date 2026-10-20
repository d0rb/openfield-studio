// The Cast station's models: saving references (consent first) and generating an invented character.

export const KINDS = ["character", "product", "wardrobe", "location"];
export const CONSENT = {
  mine: "These are photos of me.",
  consented: "The people shown agreed to this use.",
  fictional: "These are AI-generated or fictional.",
};
export const LIMITS = { name: [1, 40], images: [1, 8], imageMB: 12, description: [3, 400], candidates: [1, 4], seed: 2 ** 31 - 1 };
export const IMAGE_TYPES = [".png", ".jpg", ".jpeg", ".webp"];

const extension = (name) => (name.includes(".") ? name.slice(name.lastIndexOf(".")).toLowerCase() : "");

export const initialCast = () => ({ name: "", kind: "character", consent: null, files: [] });

/** Saving references. Consent has no default on purpose: the person has to choose. */
export function validate(state) {
  const problems = [];
  const name = state.name.trim();
  if (name.length < LIMITS.name[0] || name.length > LIMITS.name[1]) problems.push({ field: "name", message: "Give the cast a name of 1 to 40 characters." });
  if (!KINDS.includes(state.kind)) problems.push({ field: "kind", message: "Pick what this cast is." });
  if (!Object.hasOwn(CONSENT, state.consent ?? "")) problems.push({ field: "consent", message: "Say whether these are yours, consented to, or fictional." });
  const [min, max] = LIMITS.images;
  if (state.files.length < min || state.files.length > max) problems.push({ field: "files", message: `Add ${min} to ${max} images.` });
  for (const file of state.files) {
    if (!IMAGE_TYPES.includes(extension(file.name))) problems.push({ field: "files", message: `${file.name} is not a ${IMAGE_TYPES.join(", ")} image.` });
    else if (file.size > LIMITS.imageMB * 1024 * 1024) problems.push({ field: "files", message: `${file.name} is over ${LIMITS.imageMB} MB.` });
  }
  return problems;
}

export function toForm(state, FormDataImpl = globalThis.FormData) {
  const form = new FormDataImpl();
  form.append("name", state.name.trim());
  form.append("kind", state.kind);
  form.append("consent", state.consent);
  for (const file of state.files) form.append("files", file);
  return form;
}

// -- generating a fictional character -----------------------------------------------------------------

export const initialCharacter = () => ({ description: "", count: 3, seed: "" });

export function validateCharacter(state) {
  const problems = [];
  const text = state.description.trim();
  const [lo, hi] = LIMITS.description;
  if (text.length < lo) problems.push({ field: "description", message: "Describe the person: age, hair, clothing." });
  else if (text.length > hi) problems.push({ field: "description", message: `Keep it under ${hi} characters.` });
  const [cLo, cHi] = LIMITS.candidates;
  if (!Number.isInteger(state.count) || state.count < cLo || state.count > cHi) problems.push({ field: "count", message: `Ask for ${cLo} to ${cHi} candidates.` });
  if (state.seed !== "" && state.seed != null) {
    const seed = Number(state.seed);
    if (!Number.isInteger(seed) || seed < 0 || seed > LIMITS.seed) problems.push({ field: "seed", message: `A seed is a whole number from 0 to ${LIMITS.seed}.` });
  }
  return problems;
}

export function characterBody(state) {
  const body = { description: state.description.trim(), count: state.count };
  if (state.seed !== "" && state.seed != null) body.seed = Number(state.seed);
  return body;
}

/** The candidates of a finished generated-character take: [{ number, file }] (numbers are 1-based). */
export function candidatesOf(take) {
  if (!take || take.status !== "succeeded") return [];
  return (take.candidates ?? []).map((file, index) => ({ number: index + 1, file }));
}

/** A friendly default name for the character being kept, from the start of its description. */
export function suggestName(description) {
  const words = description.trim().split(/\s+/).filter((w) => !/^(a|an|the)$/i.test(w));
  const first = words.find((w) => /^[A-Za-z]/.test(w));
  return first ? first[0].toUpperCase() + first.slice(1).toLowerCase().replace(/[^a-z]/g, "").slice(0, 20) : "Character";
}
