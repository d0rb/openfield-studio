// The Re-shoot wall's compare modes: wipe (a draggable split), side (both halves
// at once) and flip (one at a time). Pure: the UI applies the layout it is given.

export const MODES = ["wipe", "side", "flip"];

/** The next mode in the cycle: wipe -> side -> flip -> wipe. */
export function nextMode(mode) {
  const at = MODES.indexOf(mode);
  return MODES[(at + 1) % MODES.length];
}

/** Keep the wipe's before share inside the wall: 2%..98%. */
export const clampSplit = (split) => Math.min(98, Math.max(2, Number.isFinite(split) ? split : 50));

/**
 * What the wall should show in `mode`. `split` is the before share of the wipe,
 * `showing` is the side that is up in flip mode. `beforeClip` is a CSS clip-path.
 */
export function compareLayout(mode, { split = 50, showing = "after" } = {}) {
  if (mode === "side") {
    return { beforeClip: "none", beforeVisible: true, afterVisible: true, handle: false, sideBySide: true };
  }
  if (mode === "flip") {
    return {
      beforeClip: "none",
      beforeVisible: showing === "before",
      afterVisible: showing === "after",
      handle: false,
      sideBySide: false,
    };
  }
  return {
    beforeClip: `inset(0 ${100 - clampSplit(split)}% 0 0)`,
    beforeVisible: true,
    afterVisible: true,
    handle: true,
    sideBySide: false,
  };
}
