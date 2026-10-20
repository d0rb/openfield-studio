// The filmstrip: recent takes of this station as poster tiles, ending in the recorded takes to watch.

import { ago } from "../lib/format.js";
import { fileOf, fromRecorded, recordingIds, titleOf } from "../lib/stages.js";
import { statusLabel } from "../lib/takes.js";
import { h, icon, renderList, setText } from "./dom.js";

export function stripItems(state, kinds) {
  const isRecording = recordingIds(state);
  const own = state.takes.filter((t) => kinds.includes(t.kind)).map((t) => (isRecording.has(t.id) ? { ...t, recording: true } : t));
  const ids = new Set(state.takes.map((t) => t.id));
  const recordings = state.recorded.filter((r) => kinds.includes(r.kind) && !ids.has(r.id)).map((r) => ({ ...fromRecorded(r), recording: true }));
  // running and waiting takes first, then finished ones and recordings, then the ones that ended without footage
  const rank = (t) => (["running", "queued", "awaiting_approval"].includes(t.status) ? 0 : ["failed", "canceled"].includes(t.status) ? 2 : 1);
  return [...own, ...recordings].map((t, order) => ({ t, order })).sort((a, b) => rank(a.t) - rank(b.t) || a.order - b.order).map(({ t }) => t);
}

export function createFilmstrip({ api, store, controller, ui, scope }) {
  const kinds = scope === "reshoot" ? ["reshoot"] : ["direct"];
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
    return button;
  }

  function paint(button, take) {
    const selected = store.get().selected === take.id;
    button.setAttribute("aria-current", String(selected));
    button.dataset.status = take.status;
    button.classList.toggle("dead", ["failed", "canceled"].includes(take.status));
    const posterFile = fileOf(take, "poster");
    const poster = button.querySelector("img");
    const src = posterFile ? api.media(take, posterFile) : "";
    if (src && poster.getAttribute("src") !== src) poster.src = src;
    poster.hidden = !src;
    const seconds = take.seconds;
    const badge = button.querySelector(".tile-badge");
    badge.replaceChildren(...(take.status === "succeeded" ? (seconds ? [`${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`] : []) : [icon(take.status === "failed" ? "triangle-alert" : take.status === "canceled" ? "ban" : "clock", "sm")]));
    button.querySelector(".tile-bar > span").style.width = `${Math.round((take.progress ?? 0) * 100)}%`;
    button.querySelector(".tile-bar").hidden = !["running", "queued"].includes(take.status);
    setText(button.querySelector(".tile-name"), titleOf(take));
    const note = take.recording ? "Recorded take" : take.replay ? "Replay" : take.status === "succeeded" ? ago(take.created_at) : statusLabel(take);
    button.title = `${titleOf(take)}: ${note}`;
    const flag = button.querySelector(".tile-flag");
    flag.textContent = take.recording ? "Recorded" : take.replay ? "Replay" : take.status === "awaiting_approval" ? "Needs approval" : take.status === "failed" ? "Failed" : take.status === "canceled" ? "Canceled" : "";
    flag.dataset.tone = take.replay ? "amber" : take.status === "awaiting_approval" ? "accent" : take.status === "failed" ? "red" : "";
  }

  let lastSelected = null;
  function update() {
    const items = stripItems(store.get(), kinds).slice(0, 30);
    renderList(strip, items, (t) => t.id, (t) => { const b = tile(t); paint(b, t); return b; }, paint);
    const picked = store.get().selected;
    if (picked !== lastSelected) {
      lastSelected = picked;
      const current = strip.querySelector('[aria-current="true"]');
      if (current) { // bring the picked take into view without moving the page
        const [t, s] = [current.getBoundingClientRect(), strip.getBoundingClientRect()];
        if (t.left < s.left) strip.scrollLeft -= s.left - t.left + 8;
        else if (t.right > s.right) strip.scrollLeft += t.right - s.right + 8;
      }
    }
    empty.hidden = items.length > 0;
    strip.hidden = items.length === 0;
    setText(count, items.length ? String(items.length) : "");
  }

  store.subscribe((_, changed) => changed.some((k) => ["takes", "recorded", "selected"].includes(k)) && update());
  update();
  return { el, update };
}
