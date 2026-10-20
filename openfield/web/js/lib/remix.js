// Remix: turn an imported receipt or recipe link into the form it belongs in, and say what is still needed.
// A receipt keeps hashes of the files that went in, not the files, so a remix is never a perfect clone.

import { fromRecipe } from "./direct.js";

/**
 * @param {object} imported the answer of POST /api/receipts/import ({ verified, recipe, label })
 * @param {object} catalog  the move catalog
 * @returns {{ form: "direct"|"reshoot"|"portrait"|null, state: object|null, needs: string[], notice: string }}
 */
export function remix(imported, catalog) {
  const recipe = imported.recipe ?? {};
  const inputs = recipe.inputs ?? {};
  const notice = noticeFor(imported.verified);
  switch (recipe.kind) {
    case "direct": {
      const state = fromRecipe({ ...inputs, prompt_only: inputs.mode === "prompt_only" }, catalog);
      const needs = inputs.cast?.name ? [`the character "${inputs.cast.name}" (pick it again in Cast)`] : [];
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
          ? "An export is made from its source take. Open that take and export it again."
          : "This receipt is not one OpenField can rebuild a take from.",
      };
  }
}

/** Parse a recipe link ("#recipe=...") out of a URL hash; returns the packed string or null. */
export function linkFromHash(hash) {
  const match = /^#?recipe=([A-Za-z0-9_-]+)$/.exec(hash ?? "");
  return match ? match[1] : null;
}

function noticeFor(verified) {
  if (verified === true) return "The receipt's checksum matches, so it has not been edited since it was written. A checksum shows edits, not who made it.";
  if (verified === null || verified === undefined) return "A recipe link carries a recipe, not a receipt: nothing here is checked or signed.";
  return "This receipt's checksum does not match: it was edited after it was written, or OpenField did not make it. What follows may not match what was rendered.";
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
