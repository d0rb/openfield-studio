// The Takes station: every take with its receipt one click away, and reels made from several of them.

import { ago } from "../lib/format.js";
import { children, ledgerTakes, reelable, statusLabel } from "../lib/takes.js";
import { fileOf, recordingIds, titleOf } from "../lib/stages.js";
import { optionLabel } from "../lib/direct.js";
import { stripItems } from "./filmstrip.js";
import { fill, h, icon, renderList, setText } from "./dom.js";
import { pill, segmented, sliderField } from "./controls.js";
import { identityPill } from "./monitor.js";

const FILTERS = [{ value: "all", label: "All" }, { value: "direct", label: "Direct" }, { value: "reshoot", label: "Re-shoot" }, { value: "export", label: "Exports" }];
const KIND = { direct: "Direct", reshoot: "Re-shoot", export: "Export" };

function subline(take, catalog) {
  const r = take.recipe ?? {};
  if (take.kind === "direct") {
    const move = catalog?.moves?.find((m) => m.id === r.rig?.movement)?.label ?? optionLabel(r.rig?.movement ?? "");
    return [move, r.rig?.duration_seconds ? `${r.rig.duration_seconds} s` : null, r.cast_name].filter(Boolean).join(" · ");
  }
  if (take.kind === "reshoot") return r.reference_name ? `New character: ${r.reference_name}` : "Motion transfer";
  if (take.kind === "export") return r.format ?? "Export";
  return "";
}

export function createTakes(ctx) {
  const { api, store, controller } = ctx;
  let filter = "all";
  const chosen = new Set();
  const list = h("ul", { class: "take-list", role: "list" });
  const empty = h("div", { class: "empty" }, icon("film", "lg"), h("h2", null, "No takes yet"), h("p", null, "Shoot something in Direct or Re-shoot. Every take lands here with its receipt."));
  const filters = segmented({ label: "Filter", options: FILTERS, value: "all", onChange: (v) => { filter = v; paint(); } });
  const crossfade = sliderField({ id: "xfade", label: "Crossfade", min: 0, max: 2, step: 0.25, value: 0.5, unit: "s" });
  const reel = h("button", { type: "button", class: "btn primary" }, icon("film"), "Make reel");
  const reelBar = h("div", { class: "reel-bar", hidden: true }, h("span", { class: "reel-count" }), h("span", { class: "grow" }), h("label", { class: "hint", for: "xfade" }, "Crossfade"), crossfade.el, reel);
  const el = h("section", { class: "takes-station", "aria-label": "Takes" },
    h("div", { class: "station-head" }, h("h1", null, "Takes"), h("p", { class: "count hint" })), h("div", { class: "takes-tools" }, filters.el), list, empty, reelBar);

  reel.addEventListener("click", async () => {
    const ids = [...chosen];
    reel.disabled = true;
    const out = await controller.exportReel(ids, Number(crossfade.el.querySelector("input[type=number]").value || 0.5));
    reel.disabled = false;
    if (out) { chosen.clear(); paint(); controller.select(out.id); }
  });

  function row(take) {
    const check = h("input", { type: "checkbox", "aria-label": "Add to reel" });
    check.addEventListener("click", (e) => e.stopPropagation());
    check.addEventListener("change", () => { check.checked ? chosen.add(take.id) : chosen.delete(take.id); paintReel(); });
    const poster = h("img", { alt: "", loading: "lazy", draggable: "false" });
    const body = h("button", { type: "button", class: "take-row-main" },
      h("span", { class: "take-thumb" }, poster), h("span", { class: "take-text" }, h("b", { class: "take-title" }), h("span", { class: "hint take-sub" })),
      h("span", { class: "take-kind" }), h("span", { class: "take-len num hint" }), h("span", { class: "take-id" }), h("span", { class: "take-when hint" }), h("span", { class: "take-state" }));
    body.addEventListener("click", () => controller.select(take.id));
    return h("li", { class: "take-row" }, h("label", { class: "take-check", title: "Add to reel" }, check), body);
  }

  function paintRow(li, take) {
    const state = store.get();
    li.dataset.depth = take.parent && state.takes.some((t) => t.id === take.parent) ? "1" : "0";
    li.querySelector(".take-row-main").setAttribute("aria-current", String(state.selected === take.id));
    const posterFile = fileOf(take, "poster");
    const poster = li.querySelector("img");
    const src = posterFile ? api.media(take, posterFile) : "";
    if (src && poster.getAttribute("src") !== src) poster.src = src;
    poster.hidden = !src;
    setText(li.querySelector(".take-title"), titleOf(take));
    setText(li.querySelector(".take-sub"), subline(take, state.moves));
    li.querySelector(".take-kind").replaceChildren(pill(KIND[take.kind] ?? take.kind));
    setText(li.querySelector(".take-len"), take.seconds ? `${take.seconds.toFixed(1)} s` : "");
    li.querySelector(".take-id").replaceChildren(...[identityPill(take.identity)].filter(Boolean));
    setText(li.querySelector(".take-when"), take.recording ? "Recorded" : ago(take.created_at));
    fill(li.querySelector(".take-state"), take.replay ? pill("Replay", "amber") : take.recording ? pill("Recorded take", "accent") : take.status === "succeeded" ? null : pill(statusLabel(take), take.status === "failed" ? "red" : take.status === "canceled" ? null : "accent"));
    const can = !take.recording && reelable([take]).length > 0 && api.kind !== "static" && !state.status?.backend?.locked;
    const box = li.querySelector("input");
    box.hidden = !can;
    box.checked = chosen.has(take.id);
  }

  function paintReel() {
    const n = chosen.size;
    reelBar.hidden = n === 0;
    setText(reelBar.querySelector(".reel-count"), `${n} take${n === 1 ? "" : "s"} selected`);
    reel.disabled = n < 2 || n > 8;
    reel.title = n < 2 ? "Pick at least two takes" : n > 8 ? "A reel joins up to eight takes" : "";
  }

  function paint() {
    const state = store.get();
    const recordings = recordingIds(state);
    const all = [...ledgerTakes(state.takes).map((t) => (recordings.has(t.id) ? { ...t, recording: true } : t)), ...stripItems({ ...state, takes: [] }, ["direct", "reshoot", "export"]).filter((r) => !state.takes.some((t) => t.id === r.id))]
      .sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
    const shown = all.filter((t) => filter === "all" || t.kind === filter);
    // a take's exports and remixes follow it, indented; one whose source is not on the list stands alone
    const under = children(shown);
    const present = new Set(shown.map((t) => t.id));
    const items = shown.filter((t) => !t.parent || !present.has(t.parent)).flatMap((t) => [t, ...(under[t.id] ?? [])]);
    list.dataset.identity = String(items.some((t) => Object.keys(t.identity ?? {}).length > 0));
    renderList(list, items, (t) => t.id, (t) => { const li = row(t); paintRow(li, t); return li; }, paintRow);
    list.hidden = items.length === 0;
    empty.hidden = items.length > 0;
    setText(el.querySelector(".count"), all.length ? `${all.length} take${all.length === 1 ? "" : "s"}` : "");
    for (const id of [...chosen]) if (!items.some((t) => t.id === id)) chosen.delete(id);
    paintReel();
  }
  store.subscribe((_, changed) => changed.some((k) => ["takes", "recorded", "selected", "status", "moves"].includes(k)) && paint());
  paint();
  return { el };
}
