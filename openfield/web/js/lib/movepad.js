// The Move Pad's data: the 35 moves organised into the 7 groups, with only the promoted moves
// on the surface and the rest behind "More". Pure functions over the catalog from /api/moves.

const MODE_COPY = {
  keyframed: { label: "Keyframed", hint: "Plans still frames along the path for you to approve, then renders between them." },
  prompt_only: { label: "Quick", hint: "One still and a camera instruction. No anchor stills to approve." },
  experimental: { label: "Experimental", hint: "A camera instruction only. Not tested with a real render yet." },
};

/** Groups in catalog order; each has its promoted moves up front and the rest under `more`. */
export function organise(catalog) {
  const groups = catalog.groups.map((g) => ({ ...g, featured: [], more: [] }));
  const byId = new Map(groups.map((g) => [g.id, g]));
  const moves = new Map();
  for (const move of catalog.moves) {
    moves.set(move.id, move);
    (byId.get(move.group) ?? groups[0])[move.featured ? "featured" : "more"].push(move);
  }
  return { groups, moves, featured: catalog.moves.filter((m) => m.featured) };
}

/** What to tell the person about a move, honestly: tested only once a real render exists. */
export function describeMove(move, { quick = false } = {}) {
  const mode = quick && move.mode === "keyframed" ? "prompt_only" : move.mode;
  const copy = MODE_COPY[mode] ?? MODE_COPY.experimental;
  const stills = mode === "keyframed" ? move.anchors : 1;
  return {
    id: move.id,
    label: move.label,
    mode,
    modeLabel: copy.label,
    hint: copy.hint,
    stills,
    stillsLabel: stills === 1 ? "1 still" : `${stills} stills`,
    tested: Boolean(move.validated),
    testedLabel: move.validated ? "Tested with a real render" : "Not yet tested with a real render",
    phrase: move.phrase,
  };
}

/** The next/previous move within the promoted set, for keyboard arrows; wraps around. */
export function step(featured, currentId, delta) {
  if (!featured.length) return null;
  const at = featured.findIndex((m) => m.id === currentId);
  return featured[(at + delta + featured.length) % featured.length].id;
}

/** Which group a move belongs to, and whether it is hidden behind "More". */
export function locate(organised, moveId) {
  for (const group of organised.groups) {
    if (group.featured.some((m) => m.id === moveId)) return { group: group.id, hidden: false };
    if (group.more.some((m) => m.id === moveId)) return { group: group.id, hidden: true };
  }
  return null;
}
