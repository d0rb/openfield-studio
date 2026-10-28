// Compare two takes: both play side by side, in step, over a table of what their receipts say differently. It works on
// every copy, because the receipts travel with the takes, and it shows what one change did to a shot.

import { compareCandidates, driftAction, receiptRows } from "../lib/receiptdiff.js";
import { fileOf, fromRecorded, posterAttrs, thumbOf, titleOf } from "../lib/stages.js";
import { holdStill } from "../lib/motion.js";
import { h, icon } from "./dom.js";
import { radioKeys } from "./controls.js";
import { openSheet } from "./sheet.js";
import { hoverClip, hoverPlay } from "./hoverplay.js";
import { claimSlot, freeSlot, previewOf } from "./wall.js";

/** Every finished take with footage, recordings included, each once. */
function footage(state) {
  const own = new Set(state.takes.map((t) => t.id));
  return [...state.takes, ...(state.recorded ?? []).filter((r) => !own.has(r.id)).map(fromRecorded)]
    .filter((t) => t.status === "succeeded" && t.kind !== "export" && fileOf(t, "video"));
}

/** Whether there is another take to set beside this one. */
export function canCompare(state, take) {
  const id = take.replay_of ?? take.id;
  return footage(state).some((t) => (t.replay_of ?? t.id) !== id);
}

export function openCompareSheet(ctx, firstId, { secondId = null } = {}) {
  const { store, api, ui } = ctx;
  const pool = footage(store.get());
  const a = pool.find((t) => t.id === firstId);
  if (!a) return null;
  const candidates = compareCandidates(a, pool).slice(0, 12);
  let b = pool.find((t) => t.id === secondId) ?? candidates[0] ?? null;
  let onlyDiff = true;
  let rows = [];
  const videos = [];

  const body = h("div", { class: "compare-sheet" });
  const screens = h("div", { class: "compare-screens" });
  const play = h("button", { type: "button", class: "btn secondary sm compare-play" }, icon("play", "sm"), h("span", null, "Play both"));
  const only = h("button", { type: "button", class: "btn ghost sm compare-only", "aria-pressed": "true" }, h("span", null, "Only what differs"));
  const summary = h("p", { class: "compare-summary", "aria-live": "polite" });
  const table = h("div", { class: "compare-table", role: "table", "aria-label": "What the two receipts say" });
  const pick = h("div", { class: "compare-pick", role: "radiogroup", "aria-label": "Compare with" });
  const bar = h("div", { class: "compare-bar" }, play, summary, only);
  const pickBlock = h("div", { class: "compare-with" }, h("h4", null, "Compare with"), pick);

  const pin = (v) => claimSlot(v, { pin: true }); // the two takes keep their decoders while the sheet is open
  const release = () => {
    for (const v of videos.splice(0)) { freeSlot(v); v.pause(); v.removeAttribute("src"); v.load(); }
  };
  const sheet = openSheet({ title: "Compare two takes", body, className: "sheet-compare", focusSheet: true, onClose: release });

  const open = (take) => { sheet.close(); history.pushState(null, "", `#/takes/${take.id}`); ui.openTake(take.id); };
  function screen(take, side) {
    const video = h("video", { class: "compare-video", muted: true, loop: true, playsinline: true, preload: "auto", disablepictureinpicture: true,
      poster: previewOf(store.get(), take, api, { width: 560 })?.poster ?? (thumbOf(store.get(), take, api) || null), "aria-label": `${side === "a" ? "This take" : "Compared with"}: ${titleOf(take)}` });
    video.muted = true;
    video.src = api.media(take, fileOf(take, "video"));
    videos.push(video);
    const name = h("button", { type: "button", class: "compare-name", title: `Open ${titleOf(take)}` }, titleOf(take));
    name.addEventListener("click", () => open(take));
    return h("figure", { class: "compare-screen", "data-side": side }, video,
      h("figcaption", null, h("span", { class: "compare-chip", "aria-hidden": "true" }, side.toUpperCase()), name));
  }

  // B follows A: same play state, same moment, a small drift taken up by B's speed (a shorter take loops on its own once A
  // runs past its end)
  function link([lead, follow]) {
    const align = () => { if (follow.duration > lead.currentTime) follow.currentTime = lead.currentTime; };
    lead.addEventListener("play", () => { follow.play().catch(() => {}); paintPlay(); });
    lead.addEventListener("pause", () => { follow.pause(); follow.playbackRate = 1; paintPlay(); }); // a nudge ends with the pair
    lead.addEventListener("seeked", align);
    lead.addEventListener("timeupdate", () => {
      if (lead.seeking) return; // a loop or a seek fires timeupdate first: seeked aligns B once, above
      const step = follow.duration > lead.currentTime ? driftAction(lead.currentTime - follow.currentTime) : "none";
      if (step === "seek") align();
      follow.playbackRate = step === "nudge-up" ? 1.05 : step === "nudge-down" ? 0.95 : 1;
    });
  }
  const paintPlay = () => {
    const playing = videos[0] && !videos[0].paused;
    play.replaceChildren(icon(playing ? "pause" : "play", "sm"), h("span", null, playing ? "Pause both" : "Play both"));
  };
  play.addEventListener("click", () => {
    const [lead] = videos;
    if (!lead) return;
    if (lead.paused) { videos.forEach(pin); lead.play().catch(() => {}); } else lead.pause();
  });
  only.addEventListener("click", () => { onlyDiff = !onlyDiff; only.setAttribute("aria-pressed", String(onlyDiff)); paintTable(); });

  function cell(row, side) {
    if (row.words) {
      const runs = row.words[side];
      return runs.length ? runs.flatMap((r, i) => [i ? " " : "", r.op === "same" ? r.text : h("mark", { class: `compare-${r.op}` }, r.text)]) : ["–"];
    }
    if (row.key === "models") {
      if (row.same) return [`${row.shared} files, the same`];
      const mine = side === "a" ? row.onlyA : row.onlyB;
      return [...mine.map((f) => h("code", null, f)), row.shared ? h("span", { class: "compare-also" }, `and ${row.shared} the same`) : ""];
    }
    return [row[side] ?? "–"];
  }
  function paintTable() {
    const differ = rows.filter((r) => !r.same).length;
    summary.textContent = !rows.length ? "No receipt to compare." : differ ? `${differ} of ${rows.length} things differ.` : "These two takes were made the same way.";
    const shown = rows.filter((r) => !onlyDiff || !r.same);
    table.replaceChildren(...shown.map((r) => h("div", { class: "compare-row", role: "row", "data-same": String(r.same) },
      h("span", { class: "compare-label", role: "rowheader" }, r.label),
      h("span", { class: "compare-cell", role: "cell", "data-side": "a" }, ...cell(r, "a")),
      h("span", { class: "compare-cell", role: "cell", "data-side": "b" }, ...cell(r, "b")))));
    only.hidden = !differ || differ === rows.length;
  }

  // made once, so a tile keeps the focus while the pair reloads
  const choose = (t) => { if (t && t.id !== b?.id) { b = t; paint(); } };
  const tiles = candidates.map((t) => {
    const tile = h("button", { type: "button", role: "radio", class: "compare-option", "aria-checked": "false", title: titleOf(t) },
      h("img", { ...posterAttrs(store.get(), t, api, "96px"), alt: titleOf(t), loading: "lazy", draggable: "false" }));
    tile.addEventListener("click", () => choose(t));
    hoverPlay(tile, hoverClip(store, t, api)); // a candidate plays under the hand or the arrow keys before it is picked
    return tile;
  });
  pick.append(...tiles);
  const syncKeys = radioKeys(pick, { onPick: (tile) => choose(candidates[tiles.indexOf(tile)]) });
  function paintPick() {
    tiles.forEach((tile, i) => tile.setAttribute("aria-checked", String(candidates[i].id === b?.id)));
    syncKeys();
  }

  let asked = 0;
  async function paint() {
    release();
    paintPick();
    if (!b) {
      body.replaceChildren(h("p", { class: "hint" }, "No other finished take to compare yet."));
      return;
    }
    const pair = [screen(a, "a"), screen(b, "b")];
    screens.replaceChildren(...pair);
    link(videos);
    rows = [];
    table.replaceChildren();
    summary.textContent = "Reading the two receipts…";
    if (screens.parentNode !== body) body.replaceChildren(screens, bar, table, pickBlock);
    paintPlay();
    if (!holdStill()) { videos.forEach(pin); videos[0].play().catch(() => {}); }
    const ask = ++asked;
    const [ra, rb] = await Promise.all([a, b].map((t) => api.receipt?.(t).then((v) => v?.receipt ?? null).catch(() => null)));
    if (ask !== asked || !sheet.el.isConnected) return; // another take was picked meanwhile
    rows = ra && rb ? receiptRows(ra, rb, store.get().moves) : [];
    paintTable();
  }
  paint();
  return sheet;
}
