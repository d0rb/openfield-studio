// The caption that travels with a take or a reel: one paste-ready line for social posts.

import { titleOf } from "./stages.js";

const MAX = 280;
const SECOND = "A film studio on open weights, built on the Comfy Developer Platform. Every take keeps its receipt.";
const QWEN = "Built with Qwen";
const ELLIPSIS = "…";

const clean = (text) => String(text ?? "").trim();
// the takes Qwen-Image made: a direct shot, its export, a board of shots and an edit
const QWEN_KINDS = ["direct", "export", "shots", "edit"];

/** A move's human label from the catalog, falling back to a tidied id. */
function moveLabel(id, catalog) {
  const list = Array.isArray(catalog) ? catalog : catalog?.moves ?? [];
  const found = list.find((move) => move?.id === id);
  if (found?.label) return clean(found.label);
  const text = clean(id);
  return text ? text.replace(/[_-]+/g, " ").replace(/^./, (c) => c.toUpperCase()) : "";
}

/** The distinct move labels of the direct takes, in take order. */
function labelsOf(takes, catalog) {
  const labels = [];
  for (const take of takes) {
    if (take?.kind !== "direct") continue;
    const label = moveLabel(take.recipe?.rig?.movement, catalog);
    if (label && !labels.includes(label)) labels.push(label);
  }
  return labels;
}

/**
 * A plain-text caption for the ticked takes (or the takes of a reel), at most 280 characters.
 *
 * Layout, one line each: the takes headline (`<title>: <move>` for a single Direct take,
 * `<title>: same motion, new character` for a single Re-shoot, `<n> takes: <moves>` for
 * several), the studio line, "Built with Qwen" when a Direct, Export, Shots or Edit take is present
 * (those are Qwen-Image only), the take `url` when given, and the `hashtag` last. The move list is
 * shortened first, then the title with an ellipsis, so the caption always fits.
 *
 * @param {object} options
 * @param {Array<object>} options.takes takes in list order; `kind` decides the headline
 * @param {string} [options.url] link to the take (usually `takeLink(id)`)
 * @param {{ moves: Array<{ id: string, label: string }> }} [options.moves] the move catalog
 * @param {string} [options.hashtag] the tag that ends the caption
 * @returns {string} the caption, ready to paste
 */
export function captionFor({ takes = [], url = "", moves = null, hashtag = "#ComfyUI" } = {}) {
  const list = (Array.isArray(takes) ? takes : []).filter(Boolean);
  const qwen = list.some((take) => QWEN_KINDS.includes(take.kind));
  const tag = clean(hashtag);

  let urlText = clean(url);

  const assemble = (head, link = urlText) => [clean(head), SECOND, ...(qwen ? [QWEN] : []), clean(link), tag].filter(Boolean).join("\n");

  const budget = (link = urlText) => MAX - assemble("", link).length - 1;

  const headline = () => {
    if (list.length === 0) return "";
    if (list.length === 1) {
      const take = list[0];
      const title = clean(titleOf(take)) || "Take";
      let suffix = "";
      if (take.kind === "direct") {
        const label = moveLabel(take.recipe?.rig?.movement, moves);
        if (label) suffix = `: ${label}`;
      } else if (take.kind === "reshoot") suffix = ": same motion, new character";
      const room = budget();
      if (title.length + suffix.length <= room) return title + suffix;
      if (suffix.length + 1 >= room) return title.slice(0, Math.max(1, room - 1)).trimEnd() + ELLIPSIS;
      return title.slice(0, Math.max(1, room - suffix.length - 1)).trimEnd() + ELLIPSIS + suffix;
    }
    return "";
  };

  let out;
  let multi = null;
  if (list.length >= 2) {
    let labels = labelsOf(list, moves);
    const build = () => assemble(labels.length ? `${list.length} takes: ${labels.join(", ")}` : `${list.length} takes`);
    out = build();
    while (out.length > MAX && labels.length > 0) {
      labels = labels.slice(0, -1);
      out = build();
    }
    multi = build;
  } else {
    out = assemble(headline());
  }

  // A very long link is the last thing to give way, so the fixed lines and the hashtag stay intact.
  while (out.length > MAX && urlText.length > 0) {
    const keep = Math.max(0, urlText.length - (out.length - MAX) - 1);
    urlText = keep ? urlText.slice(0, keep) + ELLIPSIS : "";
    out = multi ? multi() : assemble(headline());
  }

  return out;
}
