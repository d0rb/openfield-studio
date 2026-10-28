// The filmstrip: recent takes of this station as poster tiles, ending in the recorded takes to watch.

import { ago } from "../lib/format.js";
import { fromRecorded, posterAttrs, recordingIds, setPoster, titleOf } from "../lib/stages.js";
import { statusLabel } from "../lib/takes.js";
import { holdStill } from "../lib/motion.js";
import { h, icon, renderList, setText } from "./dom.js";
import { hoverClip, hoverPlay } from "./hoverplay.js";
import { chipOn } from "./pathchip.js";

export function stripItems(state, kinds) {
  const isRecording = recordingIds(state);
  const own = state.takes.filter((t) => kinds.includes(t.kind)).map((t) => (isRecording.has(t.id) ? { ...t, recording: true } : t));
  const ids = new Set(state.takes.map((t) => t.id));
  // recordings follow the showcase's reel (a mix of people and places) when it names one, else stay newest first
  const reel = new Map((state.status?.hero_reel ?? []).map((id, i) => [id, i]));
  const place = (r) => reel.get(r.id) ?? reel.size;
  const recordings = state.recorded.filter((r) => kinds.includes(r.kind) && !ids.has(r.id))
    .map((r, i) => ({ r, i })).sort((a, b) => place(a.r) - place(b.r) || a.i - b.i)
    .map(({ r }) => ({ ...fromRecorded(r), recording: true }));
  // running and waiting takes first, then finished ones and recordings, then the ones that ended without footage
  const rank = (t) => (["running", "queued", "awaiting_approval"].includes(t.status) ? 0 : ["failed", "canceled"].includes(t.status) ? 2 : 1);
  return [...own, ...recordings].map((t, order) => ({ t, order })).sort((a, b) => rank(a.t) - rank(b.t) || a.order - b.order).map(({ t }) => t);
}

const flagOf = (take) => (take.recording ? "Recorded" : take.replay ? "Replay" : take.status === "awaiting_approval" ? "Needs approval" : take.status === "failed" ? "Failed" : take.status === "canceled" ? "Canceled" : "");

export function createFilmstrip({ api, store, controller, ui, scope }) {
  const kinds = scope === "reshoot" ? ["reshoot"] : ["direct", "transition", "extend", "upscale"]; // a bridge, an extension or an upscale plays beside the shots it comes from
  let quiet = ""; // the flag most tiles share says nothing (in Replay every tile is a recording); only the odd ones out are flagged
  const count = h("span", { class: "hint" });
  const all = h("button", { type: "button", class: "btn ghost sm" }, "All takes", icon("chevron-right", "sm"));
  all.addEventListener("click", () => ui.go("takes"));
  const strip = h("div", { class: "strip", role: "list", "aria-label": "Recent takes" });
  const empty = h("p", { class: "strip-empty hint" }, "Takes you shoot appear here, newest first.");
  const el = h("section", { class: "filmstrip", "aria-label": "Recent takes" }, h("div", { class: "filmstrip-head" }, h("h3", null, "Recent takes"), count, h("span", { class: "grow" }), all), strip, empty);

  function tile(take) {
    const poster = h("img", { alt: "", loading: "lazy", draggable: "false" });
    const badge = h("span", { class: "tile-badge" });
    const flag = h("span", { class: "tile-flag" });
    const bar = h("span", { class: "tile-bar" }, h("span"));
    const frame = h("span", { class: "tile-frame" }, poster, flag, badge, bar);
    const name = h("span", { class: "tile-name" });
    const button = h("button", { type: "button", class: "tile", role: "listitem" }, frame, name);
    button.addEventListener("click", () => controller.select(take.id));
    // the pointer or keyboard focus on a frame plays that take inside it, muted, in one of the shared decoder slots
    hoverPlay(button, (width) => {
      const now = stripItems(store.get(), kinds).find((t) => t.id === take.id);
      return now?.status === "succeeded" ? hoverClip(store, now, api)(width) : null;
    }, { into: frame });
    const movement = take.kind === "direct" && take.recipe?.rig?.movement; // and a Direct take draws its camera's path
    if (movement) chipOn(button, () => frame.querySelector("video.hover-clip"), { catalog: () => store.get().moves, movement, angle: take.recipe.rig.angle ?? null, into: frame });
    return button;
  }

  function paint(button, take) {
    const selected = store.get().selected === take.id;
    button.setAttribute("aria-current", String(selected));
    button.dataset.status = take.status;
    button.classList.toggle("dead", ["failed", "canceled"].includes(take.status));
    setPoster(button.querySelector("img"), posterAttrs(store.get(), take, api, "104px")); // the tile's small picture, not the take's full poster
    const seconds = take.seconds;
    const badge = button.querySelector(".tile-badge");
    badge.replaceChildren(...(take.status === "succeeded" ? (seconds ? [`${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`] : []) : [icon(take.status === "failed" ? "triangle-alert" : take.status === "canceled" ? "ban" : "clock", "sm")]));
    button.querySelector(".tile-bar > span").style.width = `${Math.round((take.progress ?? 0) * 100)}%`;
    button.querySelector(".tile-bar").hidden = !["running", "queued"].includes(take.status);
    setText(button.querySelector(".tile-name"), titleOf(take));
    const note = take.recording ? "Recorded take" : take.replay ? "Replay" : take.status === "succeeded" ? ago(take.created_at) : statusLabel(take);
    button.title = `${titleOf(take)}: ${note}`;
    button.setAttribute("aria-label", `${titleOf(take)}: ${note}`); // the name is not printed under the tile
    const flag = button.querySelector(".tile-flag");
    const text = flagOf(take);
    flag.textContent = text === quiet ? "" : text;
    flag.dataset.tone = take.replay ? "amber" : take.status === "awaiting_approval" ? "accent" : take.status === "failed" ? "red" : "";
  }

  let lastSelected = null;
  function update() {
    const items = stripItems(store.get(), kinds).slice(0, 30);
    const counts = new Map();
    for (const t of items) { const f = flagOf(t); if (f) counts.set(f, (counts.get(f) ?? 0) + 1); }
    quiet = [...counts].find(([, n]) => n >= 2 && n > items.length / 2)?.[0] ?? "";
    renderList(strip, items, (t) => t.id, (t) => { const b = tile(t); paint(b, t); return b; }, paint);
    const picked = store.get().selected;
    if (picked !== lastSelected) {
      lastSelected = picked;
      const current = strip.querySelector('[aria-current="true"]');
      if (current) { // bring the picked take into view, gliding, without moving the page
        const [t, s] = [current.getBoundingClientRect(), strip.getBoundingClientRect()];
        if (t.left < s.left || t.right > s.right) {
          // land on a tile's edge (the one before it, for context), so scroll snapping keeps the picked one whole
          const lead = current.previousElementSibling ?? current;
          strip.scrollTo({ left: strip.scrollLeft + lead.getBoundingClientRect().left - s.left, behavior: holdStill() ? "auto" : "smooth" });
        }
      }
    }
    empty.hidden = items.length > 0;
    strip.hidden = items.length === 0;
    setText(count, items.length ? String(items.length) : "");
  }

  store.subscribe((_, changed) => changed.some((k) => ["takes", "recorded", "selected", "previews"].includes(k)) && update());
  update();
  return { el, update };
}
