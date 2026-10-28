// The Lobby's galleries. Camera moves: every move whose recorded take shows it, in the rig's groups. Effects: every effect
// on a rail. Each frame plays its loop while it is on screen, and under the mouse the frame scrubs its take, so the hand
// drives the camera. A move opens its own sheet; an effect starts Direct from the settings of the take that shows it.

import { h, icon } from "./dom.js";
import { liveClip, previewOf } from "./wall.js";
import { chipOn } from "./pathchip.js";
import { scrubbable } from "./scrub.js";
import { loadTake } from "./actions.js";
import { deckFilters, effectDeck, inFilter, moveDeck } from "../lib/deck.js";
import { holdStill } from "../lib/motion.js";
import { settle } from "./reveal.js";

const EASE = "cubic-bezier(0.16, 1, 0.3, 1)";
const plainClick = (e) => !(e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button !== 0);

/** A frame of footage: the take's loop, a line that follows the scrub, and whatever the card lays over it. */
function showFrame(state, takeId, api, extra = null) {
  const clip = previewOf(state, { id: takeId }, api, { width: Math.min(340, globalThis.innerWidth * 0.22) });
  const video = clip ? liveClip(clip) : h("span", { class: "live-clip blank" });
  const box = h("span", { class: "show-frame" }, video, extra, h("span", { class: "scrub-line", "aria-hidden": "true" }));
  if (clip) scrubbable(box, video);
  return box;
}

/** The camera moves: filters by group, a grid of frames, each opening its move. */
export function createMoveShow(ctx, { onOpen }) {
  const filters = h("div", { class: "show-filters", role: "group", "aria-label": "Show camera moves" });
  const grid = h("ul", { class: "move-grid", "aria-labelledby": "lobby-moves" });
  const el = h("section", { class: "moves-show", hidden: true },
    h("div", { class: "show-head" },
      h("h2", { id: "lobby-moves", class: "lobby-h2" }, "Camera moves"),
      h("p", { class: "show-lede" },
        h("span", { class: "for-mouse" }, "Run the mouse across a frame to drive the camera."),
        h("span", { class: "for-touch" }, "Tap a frame."))),
    filters, grid);
  let key = "";
  let filter = "featured";
  let deck = [];

  function choose(id, animate = true) {
    filter = id;
    for (const b of filters.children) b.setAttribute("aria-pressed", String(b.dataset.filter === id));
    if (animate) settle(grid); // a filter change is never a reveal: every frame stands as it is, then the reflow moves it
    const items = [...grid.children];
    if (animate) for (const li of items) for (const a of li.getAnimations()) a.cancel(); // a glide still running would be measured part-way
    const before = new Map(items.filter((li) => !li.hidden).map((li) => [li, li.getBoundingClientRect()]));
    const byId = new Map(deck.map((m) => [m.id, m]));
    for (const li of items) li.hidden = !inFilter(byId.get(li.dataset.move), id);
    if (!animate || holdStill()) return;
    let fresh = 0;
    for (const li of items) {
      if (li.hidden) continue;
      const was = before.get(li);
      const now = li.getBoundingClientRect();
      if (was) {
        const dx = was.left - now.left;
        const dy = was.top - now.top;
        if (dx || dy) li.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }], { duration: 460, easing: EASE });
      } else {
        li.animate([{ opacity: 0, transform: "translateY(14px)" }, { opacity: 1, transform: "none" }],
          { duration: 380, delay: Math.min(260, 26 * fresh++), easing: EASE, fill: "backwards" });
      }
    }
  }

  function paint(state) {
    const next = moveDeck(state.moves, state.previews);
    const k = next.map((m) => `${m.id}:${m.takeId}`).join();
    if (k === key) return deck;
    key = k;
    deck = next;
    el.hidden = !deck.length;
    if (!deck.length) return deck;
    const list = deckFilters(deck, state.moves.groups ?? []);
    if (!list.some((f) => f.id === filter)) filter = list[0].id;
    filters.replaceChildren(...list.map((f) => h("button", { type: "button", class: "show-filter", "data-filter": f.id, "aria-pressed": String(f.id === filter),
      onclick: () => choose(f.id) }, h("span", null, f.label), h("span", { class: "num" }, String(f.count)))));
    grid.replaceChildren(...deck.map((m) => {
      const frame = showFrame(state, m.takeId, ctx.api);
      const card = h("a", { class: "show-card", href: `#/lobby/${m.id}`, "data-move": m.id },
        frame,
        h("span", { class: "show-name" }, m.label),
        h("span", { class: "show-meta" }, m.groupLabel));
      // the move's path over its frame, lit as far as the loop or the scrub has run, from where that take's camera started
      const proof = [...(state.recorded ?? []), ...state.takes].find((t) => t.id === m.takeId);
      chipOn(card, () => frame.querySelector("video"), { catalog: () => ctx.store.get().moves, movement: m.id, angle: proof?.recipe?.rig?.angle ?? null, into: frame });
      card.addEventListener("click", (e) => {
        if (!plainClick(e)) return;
        e.preventDefault();
        onOpen(m.id, card.querySelector(".show-frame")); // the move's page flies in from this frame
      });
      return h("li", { "data-move": m.id }, card);
    }));
    choose(filter, false);
    return deck;
  }

  return { el, paint, ids: () => deck.filter((m) => inFilter(m, filter)).map((m) => m.id), all: () => deck.map((m) => m.id) };
}

/** The effects: a rail of frames; one starts Direct from the take that shows it. */
export function createEffectShow(ctx) {
  const rail = h("ul", { class: "effect-rail", "aria-labelledby": "lobby-effects" });
  const back = h("button", { type: "button", class: "btn secondary sm icon-only rail-back", "aria-label": "Earlier effects" }, icon("chevron-left", "sm"));
  const on = h("button", { type: "button", class: "btn secondary sm icon-only rail-on", "aria-label": "More effects" }, icon("chevron-right", "sm"));
  const el = h("section", { class: "effects-show", hidden: true },
    h("div", { class: "show-head" },
      h("h2", { id: "lobby-effects", class: "lobby-h2" }, "Effects"),
      h("p", { class: "show-lede" }, "Weather, light and change. Pick one to start a shot."),
      h("div", { class: "rail-arrows" }, back, on)),
    rail);
  const page = (dir) => rail.scrollBy({ left: dir * rail.clientWidth * 0.8, behavior: holdStill() ? "auto" : "smooth" });
  back.addEventListener("click", () => page(-1));
  on.addEventListener("click", () => page(1));
  // the rail fades out on each side that has more cards: .at-start while some lie before the view, .at-end while some
  // lie after it (measured again when the rail is first shown or resized, not only when it scrolls)
  const ends = () => {
    const before = rail.scrollLeft >= 4;
    const after = rail.scrollLeft + rail.clientWidth <= rail.scrollWidth - 4;
    back.disabled = !before;
    on.disabled = !after;
    rail.classList.toggle("at-start", before);
    rail.classList.toggle("at-end", after);
  };
  rail.addEventListener("scroll", ends, { passive: true });
  if (globalThis.ResizeObserver) new ResizeObserver(ends).observe(rail);
  let key = "";

  function paint(state) {
    const deck = effectDeck(state.moves, state.previews);
    const k = deck.map((e) => `${e.id}:${e.takeId}`).join();
    if (k === key) return;
    key = k;
    el.hidden = !deck.length;
    rail.replaceChildren(...deck.map((e) => {
      const take = (state.recorded ?? []).find((t) => t.id === e.takeId) ?? null;
      const frame = showFrame(state, e.takeId, ctx.api);
      const card = h("a", { class: "show-card", href: `#/takes/${e.takeId}`, "data-effect": e.id, title: `${e.label}: start a shot with it` },
        frame,
        h("span", { class: "show-name" }, e.label),
        h("span", { class: "show-meta" }, e.kindLabel));
      const movement = take?.kind === "direct" && take.recipe?.rig?.movement; // a Direct take shows its camera's path too
      if (movement) chipOn(card, () => frame.querySelector("video"), { catalog: () => ctx.store.get().moves, movement, angle: take.recipe.rig.angle ?? null, into: frame });
      card.addEventListener("click", (ev) => {
        if (!plainClick(ev)) return;
        ev.preventDefault();
        if (take?.kind === "direct") loadTake(ctx, take);
        else ctx.ui.openTake(e.takeId);
      });
      return h("li", null, card);
    }));
    requestAnimationFrame(ends);
  }

  return { el, paint };
}
