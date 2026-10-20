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
    ui.go("direct");
  } else if (take.kind === "reshoot") {
    forms.set((s) => ({ reshoot: { ...initialReshoot(), prompt: recipe.prompt ?? "", background: recipe.background ?? "", motion: recipe.motion ?? "", seed: recipe.seed ?? "", clip: s.reshoot.clip, referenceFile: s.reshoot.referenceFile } }));
    notify(ctx, "Settings loaded. Add your source clip and a reference image again.", "Receipts keep hashes of your files, not the files.");
    ui.go("reshoot");
  }
}

/** Open a receipt, an OpenField .mp4 or .png, or a recipe link, and load what it holds into the right form. */
export async function remixFrom(ctx, source) {
  const { api, store, forms, ui } = ctx;
  try {
    const imported = typeof source === "string"
      ? { verified: null, recipe: await decodeRecipeLink(source) }
      : await api.importReceipt(source);
    const result = remix(imported, store.get().moves);
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
