// Things a person can do with a take, shared by the Monitor, the details dock and the Takes list.

import { fromRecipe, initialDirect } from "../lib/direct.js";
import { remix, decodeRecipeLink } from "../lib/remix.js";
import { initialReshoot } from "../lib/reshoot.js";
import { initialCharacter } from "../lib/cast.js";

export function notify(ctx, message, how, tone = "info") {
  const entry = { id: Date.now() + Math.random(), code: tone, tone, message, how };
  ctx.store.set((s) => ({ notices: [...s.notices, entry].slice(-4) }));
  return entry;
}

/** Put a take's settings back in the form it came from, so it can be changed and shot again. */
export function loadTake(ctx, take) {
  const { store, forms, ui } = ctx;
  const recipe = take.recipe ?? {};
  if (take.kind === "direct") {
    const catalog = store.get().moves;
    const state = fromRecipe(recipe, catalog);
    state.castId = store.get().cast.find((c) => c.name === recipe.cast_name)?.id ?? null;
    state.autoApprove = Boolean(recipe.auto_approve);
    forms.set({ direct: state });
    if (recipe.cast_name && !state.castId) notify(ctx, `Settings loaded. The character "${recipe.cast_name}" is not in this Cast.`, "Add them in Cast, then pick them in Settings.");
    if (recipe.source_sha256) notify(ctx, "Settings loaded. Add your image again in Character.");
    ui.go("direct");
  } else if (take.kind === "reshoot") {
    forms.set((s) => ({ reshoot: { ...initialReshoot(), prompt: recipe.prompt ?? "", background: recipe.background ?? "", motion: recipe.motion ?? "", seed: recipe.seed ?? "", faceOnly: Boolean(recipe.face_only), clip: s.reshoot.clip, referenceFile: s.reshoot.referenceFile } }));
    notify(ctx, "Settings loaded. Add your source clip and a reference image again.");
    ui.go("reshoot");
  }
}

/** A still from a take's folder as a File, to upload again. */
export async function stillFile(api, take, path, name = path.split("/").pop()) {
  const res = await fetch(api.media(take, path));
  if (!res.ok) throw new Error(`could not load ${path}`);
  const blob = await res.blob();
  return new File([blob], name, { type: blob.type || "image/png" });
}

/** A still becomes the first frame of a new Direct shot (My image). */
export async function animateStill(ctx, take, path, label, name) {
  const { api, forms, ui } = ctx;
  try {
    const file = await stillFile(api, take, path, name);
    const direct = forms.get().direct;
    if (direct?.sourcePreview) URL.revokeObjectURL(direct.sourcePreview);
    forms.set({ direct: { ...direct, heroMode: "image", sourceFile: file, sourcePreview: URL.createObjectURL(file) } });
    ui.go("direct");
    notify(ctx, `${label} is the first frame now.`, "Pick a move, then shoot.", "info");
  } catch {
    notify(ctx, "Could not load that still.", "Try again, or download it from the take's folder.", "error");
  }
}

/** Open a receipt, an OpenField .mp4 or .png, or a recipe link, and load what it holds into the right form. */
export async function remixFrom(ctx, source) {
  const { api, store, forms, ui } = ctx;
  try {
    const imported = typeof source === "string"
      ? { verified: null, recipe: await decodeRecipeLink(source) }
      : await api.importReceipt(source);
    const result = remix(imported, store.get().moves, store.get().recorded);
    if (!result.form) return notify(ctx, result.notice, null, "error");
    if (result.form === "direct") forms.set({ direct: result.state });
    else if (result.form === "reshoot") forms.set((s) => ({ reshoot: { ...s.reshoot, ...result.state } }));
    else if (result.form === "portrait") forms.set({ character: { ...initialCharacter(), ...result.state } });
    notify(ctx, result.notice, result.needs.length ? `Still needed: ${result.needs.join("; ")}.` : null);
    ui.go(result.form === "portrait" ? "cast" : result.form);
  } catch (error) {
    notify(ctx, error.message ?? "That file could not be opened.", null, "error");
  }
}

export const freshDirect = (catalog) => initialDirect(catalog);
