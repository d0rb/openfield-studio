// Keykode: the micro-type a frame carries along its own edge.
//
// Film stock prints its key numbers down the sprocket edge, so a strip of footage can never be separated from the
// record of where it came from. Every frame this studio shows does the same: its serial, the seed it was rolled on
// and the head of its recipe hash run up the left gutter of the picture in 8px mono. It is HTML over the frame, never
// burnt into the render (the renders carry no words). It is decorative to a screen reader: every frame that carries
// one already names its take in its own accessible name (the tile's aria-label, the hero's chip), and reading a hash
// out aloud on each of 137 tiles would bury that name rather than add to it.

import { h } from "./dom.js";

const serial = (id) => String(id ?? "").replace(/^tk_/, "").replace(/_/g, " ").toUpperCase();

/** The fields a keykode prints, in the billing order: serial, seed, recipe. A field the take did not record is left
    out rather than guessed, so a strip never claims a number it has not got. */
function fields(take, full) {
  const out = [];
  if (take?.id) out.push(serial(take.id));
  if (take?.recipe?.seed != null) out.push(`SEED ${take.recipe.seed}`);
  // the recipe only on a frame tall enough to print all of it: a field is dropped whole rather than cut short,
  // because half a hash is not a fact anyone can check
  if (full && take?.recipe_hash) out.push(take.recipe_hash.slice(0, 8).toUpperCase());
  return out;
}

/** The keykode element for a take, or null when the take records nothing to print. The orange ticks between fields are
    the stock's foot marks: they are the one place the accent appears on a picture. */
export function keykode(take, { full = false } = {}) {
  const parts = fields(take, full);
  if (!parts.length) return null;
  const kids = [];
  parts.forEach((part, i) => {
    if (i) kids.push(h("b", null, "·"));
    kids.push(part);
  });
  return h("span", { class: full ? "keykode full" : "keykode", "aria-hidden": "true" }, ...kids);
}

/** Print a take's keykode into a frame, replacing the one it already carries. `frame` must be the positioned element
    the picture fills. Returns the element printed, or null when there was nothing to print. */
export function printKeykode(frame, take, opts) {
  if (!frame) return null;
  frame.querySelector(":scope > .keykode")?.remove();
  const mark = keykode(take, opts);
  if (mark) frame.append(mark);
  return mark;
}
