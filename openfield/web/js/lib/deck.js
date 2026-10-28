// The Lobby's galleries as data: which camera moves and effects can play a recorded take, in the rig's own order, the
// trailer's segments as a reel, and the marquee's counts. Pure functions, so the galleries are tested without a browser.

/** The moves that can play: each move whose flag says a real render held and whose measured take has a loop. */
export function moveDeck(catalog, previews) {
  const tiles = previews?.moves ?? {};
  const loops = previews?.takes ?? {};
  return (catalog?.moves ?? [])
    .filter((m) => m.validated && tiles[m.id] && loops[tiles[m.id]])
    .map((m) => ({ id: m.id, label: m.label, group: m.group, groupLabel: m.group_label ?? m.group, featured: Boolean(m.featured), takeId: tiles[m.id] }));
}

/** The filters over a deck: the featured moves, all of them, then each group with a move to show, with counts. */
export function deckFilters(deck, groups = []) {
  const count = (keep) => deck.filter(keep).length;
  const out = [];
  const featured = count((m) => m.featured);
  if (featured) out.push({ id: "featured", label: "Featured", count: featured });
  out.push({ id: "all", label: "All", count: deck.length });
  for (const g of groups) {
    const n = count((m) => m.group === g.id);
    if (n) out.push({ id: g.id, label: g.label, count: n });
  }
  return out;
}

/** Whether a move shows under a filter. */
export const inFilter = (move, filter) => filter === "all" || (filter === "featured" ? move.featured : move.group === filter);

const TIME = new Set(["time_freeze", "slow_motion"]);
const kindOf = (e) => (e.kind === "keyframed" ? "Transformation" : TIME.has(e.id) ? "Time" : "Weather and light");

/** The effects that can play, in the rig's order: each whose flag says it held and whose take has a loop. */
export function effectDeck(catalog, previews) {
  const tiles = previews?.effects ?? {};
  const loops = previews?.takes ?? {};
  return (catalog?.effects ?? [])
    .filter((e) => e.id !== "none" && e.tested && tiles[e.id] && loops[tiles[e.id]])
    .map((e) => ({ id: e.id, label: e.label, kind: e.kind, kindLabel: kindOf(e), takeId: tiles[e.id] }));
}

/** The trailer's segments as a reel: each keeps its place and its share of the running time (its width). */
export function trailerReel(segments = []) {
  const length = (s) => Math.max(0, (s.end ?? 0) - (s.start ?? 0));
  const total = segments.reduce((n, s) => n + length(s), 0) || 1;
  return segments.map((s, index) => ({ ...s, index, share: length(s) / total }));
}

/** Where the trailer is at t seconds: the segment playing and how far through it (0..1); -1 between segments. */
export function reelAt(reel, t) {
  const index = reel.findIndex((s) => t >= s.start && t < s.end);
  if (index < 0) return { index: -1, through: 0 };
  const s = reel[index];
  return { index, through: Math.min(1, Math.max(0, (t - s.start) / (s.end - s.start || 1))) };
}

/** The marquee's middle line, one count at a time: only what the data holds, and nothing about testing. */
export function marqueeCounts({ moves = 0, effects = 0, takes = 0 } = {}) {
  return [moves ? `${moves} CAMERA MOVES` : null, effects ? `${effects} EFFECTS` : null, takes ? `${takes} RECORDED TAKES` : null].filter(Boolean);
}

/** The time under a pointer x pixels across a frame w wide, over a clip d seconds long (kept inside the clip). */
export const scrubTime = (x, w, d) => (w > 0 && d > 0 ? Math.min(d - 0.04, Math.max(0, (x / w) * d)) : 0);

/** The next item in a list after `id`, wrapping at both ends (delta 1 or -1): the move sheet's arrows walk the gallery with it.
 * With no `id` to stand on, either way gives the first item. */
export function stepIn(ids, id, delta) {
  if (!ids.length) return null;
  const at = ids.indexOf(id);
  return ids[(((at < 0 ? 0 : at + delta) % ids.length) + ids.length) % ids.length];
}
