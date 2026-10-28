// Remix: turn an imported receipt or recipe link into the form it belongs in, and say what is still needed.
// A receipt keeps hashes of the files that went in, not the files, so a remix is never a perfect clone.

import { fromRecipe } from "./direct.js";

/**
 * @param {object} imported the answer of POST /api/receipts/import ({ verified, recipe, label })
 * @param {object} catalog  the move catalog
 * @param {object[]} [recorded] the recordings: the one a receipt names tells quick mode on a one-still move
 * @returns {{ form: "direct"|"reshoot"|"portrait"|null, state: object|null, needs: string[], notice: string }}
 */
export function remix(imported, catalog, recorded = []) {
  const recipe = imported.recipe ?? {};
  const inputs = recipe.inputs ?? {};
  const notice = noticeFor(imported.verified);
  switch (recipe.kind) {
    case "direct": {
      // the receipt keeps the plan's mode (quick only on a keyframed move, else as its recording says) and the line under dialogue
      const move = catalog?.moves?.find((m) => m.id === (inputs.move ?? inputs.rig?.movement));
      const twin = inputs.recipe_hash && recorded?.find((r) => r.recipe_hash === inputs.recipe_hash);
      const { line, delivery, language } = inputs.dialogue ?? inputs;
      const state = fromRecipe({ ...inputs, line, delivery, language, prompt_only: twin ? Boolean(twin.recipe?.prompt_only) : inputs.mode === "prompt_only" && move?.mode === "keyframed" }, catalog);
      const needs = inputs.cast?.name ? [`the character "${inputs.cast.name}" (pick it again in Cast)`] : [];
      if (inputs.source) needs.push("your image (the hero still was your own photo)");
      return { form: "direct", state, needs, notice };
    }
    case "reshoot":
      return {
        form: "reshoot",
        state: { prompt: inputs.prompt ?? "", background: inputs.background ?? "", motion: inputs.motion ?? "", seed: inputs.seed ?? "" },
        needs: ["your source clip", inputs.reference_name ? `a reference image (it was "${inputs.reference_name}")` : "a reference image"],
        notice,
      };
    case "portrait":
      return {
        form: "portrait",
        state: { description: inputs.description ?? "", count: inputs.count ?? 3, seed: inputs.seed ?? "" },
        needs: [],
        notice,
      };
    default:
      return {
        form: null,
        state: null,
        needs: [],
        notice: recipe.kind === "export"
          ? "Open the source take to export it again."
          : "OpenField cannot rebuild a take from this receipt.",
      };
  }
}

/** Parse a recipe link ("#recipe=...") out of a URL hash; returns the packed string or null. */
export function linkFromHash(hash) {
  const match = /^#?recipe=([A-Za-z0-9_-]+)$/.exec(hash ?? "");
  return match ? match[1] : null;
}

function noticeFor(verified) {
  if (verified === true) return "The checksum matches. It does not prove who wrote it.";
  if (verified === null || verified === undefined) return "Settings only. Nothing in it is checked.";
  return "The checksum does not match. Edited, or not made here.";
}

/** Decode a recipe link (base64url of zlib-compressed JSON) in the browser, with no server round trip. */
export async function decodeRecipeLink(link) {
  const standard = link.replace(/-/g, "+").replace(/_/g, "/");
  const bytes = Uint8Array.from(atob(standard + "=".repeat((4 - (standard.length % 4)) % 4)), (c) => c.charCodeAt(0));
  const text = await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate"))).text();
  const recipe = JSON.parse(text);
  if (!recipe || typeof recipe !== "object" || Array.isArray(recipe)) throw new Error("That link does not hold a recipe.");
  return recipe;
}
