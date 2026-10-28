// The Takes station: every take with its receipt one click away, and reels made from several of them.

import { ago } from "../lib/format.js";
import { ledgerLine } from "../lib/billing.js";
import { FILM_KINDS, children, ledgerTakes, reelable, statusLabel } from "../lib/takes.js";
import { angleSheet, posterAttrs, recordingIds, sampleTake, setPoster, sheetSubject, titleOf } from "../lib/stages.js";
import { takeLink } from "../lib/route.js";
import { captionFor } from "../lib/share.js";
import { angleGeometry, describeAngle, optionLabel } from "../lib/direct.js";
import { withAngle } from "../lib/pathview.js";
import { describeMove, organise } from "../lib/movepad.js";
import { editPreset } from "../lib/edit.js";
import { holdStill, onMotionChange } from "../lib/motion.js";
import { stripItems } from "./filmstrip.js";
import { notify } from "./actions.js";
import { copyText, fill, flip, h, icon, renderList, setText } from "./dom.js";
import { pill, segmented, sliderField } from "./controls.js";
import { identityPill } from "./monitor.js";
import { clipVideo, hoverClip, hoverPlay } from "./hoverplay.js";
import { tilePlan } from "./pathchip.js";
import { KIND, cap, claimSlot, createWall, freeSlot } from "./wall.js";

const FILTERS = [{ value: "wall", label: "Wall" }, { value: "all", label: "All" }, { value: "direct", label: "Direct" }, { value: "reshoot", label: "Re-shoot" }, { value: "export", label: "Exports" }, { value: "moves", label: "Moves" }, { value: "angles", label: "Angles" }];

function subline(take, catalog) {
  const r = take.recipe ?? {};
  if (take.kind === "direct") {
    const move = catalog?.moves?.find((m) => m.id === r.rig?.movement)?.label ?? optionLabel(r.rig?.movement ?? "");
    return [move, r.rig?.duration_seconds ? `${r.rig.duration_seconds} s` : null, r.cast_name].filter(Boolean).join(" · ");
  }
  if (take.kind === "reshoot") return r.reference_name ? `New character: ${r.reference_name}` : "Motion transfer";
  if (take.kind === "export") return r.format ?? "Export";
  if (take.kind === "transition") return [catalog?.transitions?.styles.find((s) => s.id === r.style)?.label, r.seconds ? `${r.seconds} s bridge` : null].filter(Boolean).join(" · ");
  if (take.kind === "shots") return "Nine setups of one still";
  if (take.kind === "edit") return [editPreset(catalog, r.preset)?.label, r.detail || r.cast_name].filter(Boolean).join(" · ");
  if (take.kind === "extend") return r.seconds ? `${r.seconds} s added` : "";
  if (take.kind === "upscale") return r.target ? `${r.target.toUpperCase()} upscale` : "";
  return "";
}

export function createTakes(ctx) {
  const { api, store, controller, ui } = ctx;
  let filter = "wall";
  const wall = createWall(ctx);
  const chosen = new Set();
  const list = h("ul", { class: "take-list", role: "list" });
  const sheet = h("div", { class: "moves-sheet", role: "list", "aria-label": "One take for every promoted camera move", hidden: true });
  const empty = h("div", { class: "empty" }, h("img", { class: "empty-art", src: "art/art-takes.webp", alt: "", loading: "lazy", decoding: "async" }), h("h2", null, "No takes yet"), h("p", null, "Shoot something in Direct. It lands here with its receipt."));
  const emptyAngles = h("div", { class: "empty", hidden: true }, icon("film", "lg"), h("h2", null, "No angled takes yet"), h("p", null, "In Direct, drag the camera on the stage, then shoot."));
  const filters = segmented({ label: "Filter", options: FILTERS, value: "wall", onChange: (v) => { filter = v; paint(); } });
  const crossfade = sliderField({ id: "xfade", label: "Crossfade", min: 0, max: 2, step: 0.25, value: 0.5, unit: "s" });
  const reel = h("button", { type: "button", class: "btn primary" }, icon("film"), "Make reel");
  const caption = h("button", { type: "button", class: "btn secondary" }, icon("link"), "Copy caption");
  const reelBar = h("div", { class: "reel-bar", hidden: true }, h("span", { class: "reel-count" }), h("span", { class: "grow" }), h("label", { class: "hint", for: "xfade" }, "Crossfade"), crossfade.el, caption, reel);
  const playAll = h("button", { type: "button", class: "btn secondary sm play-all", "aria-pressed": "false", hidden: true }, icon("play", "sm"), "Play all");
  // the sameness is the point: one still, one subject, twelve moves; the motion shows on hover or with Play all
  const sheetHint = h("p", { class: "hint sheet-hint", hidden: true }, "Same still for every card. Hover one or play all.");
  // the ledger line has a place of its own from the first paint (empty until the status comes): the head does not jump when it fills
  const ledgerEl = h("span", { class: "takes-ledger" });
  const el = h("section", { class: "takes-station", "aria-label": "Takes" },
    h("div", { class: "station-head" }, h("h1", null, "Takes"), h("p", { class: "count hint" }), ledgerEl), h("div", { class: "takes-tools" }, filters.el, playAll, sheetHint), wall.el, list, sheet, empty, emptyAngles, reelBar);

  // -- Play all: the cards play their loops at once, pinned in the shared decoder slots, a few at a time (the hover
  // clip stands aside while it does) ----------------------------------------------------------------------------------
  let playing = false;
  const sheetTakes = new Map(); // card element -> its take
  const halt = (video) => { freeSlot(video); video.pause(); video.removeAttribute("src"); video.load(); video.remove(); };
  function paintPlayAll() {
    if (holdStill()) playing = false;
    playAll.setAttribute("aria-pressed", String(playing));
    playAll.replaceChildren(icon(playing ? "pause" : "play", "sm"), playing ? "Pause all" : "Play all");
    const limit = cap(); // as on the wall: a phone plays four at a time, a wide screen twelve
    let started = 0;
    for (const [card, take] of sheetTakes) {
      const frame = card.querySelector(".move-card-frame");
      const current = frame.querySelector("video.all");
      if (current && playing && started < limit) { started += 1; continue; } // already playing: it holds one of the slots
      if (current) { halt(current); continue; } // paused, or the window narrowed: this card steps aside
      if (!playing || started >= limit) continue; // the rest of the row keeps its poster
      const clip = hoverClip(store, take, api)(frame.clientWidth); // the loop that fills the frame, not the take's own file
      if (!clip) continue;
      const video = clipVideo(clip, "preview all");
      frame.prepend(video);
      claimSlot(video, { pin: true });
      started += 1;
      video.play().catch(() => {});
    }
  }
  playAll.addEventListener("click", () => { playing = !playing; paintPlayAll(); });
  // reduced motion turned on stops the cards and hides Play all; turned off, Play all comes back
  onMotionChange(() => { if (holdStill() && playing) { playing = false; paintPlayAll(); } paint(); });

  // -- the moves sheet: the same shot under every promoted move, each card playing its newest take ----------
  function card(move, take, { label = move.label, sub = null, id = move.id } = {}) {
    const frame = h("span", { class: "move-card-frame" }, tilePlan(move));
    const picture = take ? posterAttrs(store.get(), take, api, "(max-width: 719px) 46vw, 300px") : null;
    if (picture) frame.append(h("img", { ...picture, alt: "", loading: "lazy", draggable: "false" }));
    const b = h("button", { type: "button", class: "move-card", role: "listitem", "data-move": id, disabled: !take },
      frame, h("span", { class: "move-card-name" }, label),
      h("span", { class: "hint move-card-sub" }, take ? (sub ?? `${describeMove(move, { quick: Boolean(take.recipe?.prompt_only) }).modeLabel} \u00b7 ${take.recipe?.rig?.duration_seconds ?? ""} s`) : "No take with this move yet"));
    if (take) {
      b.addEventListener("click", () => { controller.select(take.id); ui.go("direct"); });
      // the card's own take, so the poster and the clip agree; a card Play all runs keeps its video
      hoverPlay(b, (width) => (frame.querySelector("video.all") ? null : hoverClip(store, take, api)(width)), { into: frame });
    }
    return b;
  }
  function paintSheet(state) {
    const catalog = state.moves;
    if (!catalog) return;
    const featured = organise(catalog).featured;
    const subject = sheetSubject(state, featured.map((m) => m.id));  // the same shot under every move
    const samples = featured.map((m) => [m, sampleTake(state, m.id, { subject })]);
    const key = samples.map(([m, t]) => `${m.id}:${t?.id ?? ""}`).join();
    if (sheet.dataset.key === key) return;
    sheet.dataset.key = key;
    sheetTakes.clear();
    sheet.replaceChildren(...samples.map(([m, t]) => { const c = card(m, t); if (t) sheetTakes.set(c, t); return c; }));
    if (playing) paintPlayAll();
  }
  // -- the angles sheet: one subject re-shot from every recorded camera position, each card its own take -----------
  function paintAngles(state) {
    const catalog = state.moves;
    if (!catalog) return;
    const items = angleSheet(state, catalog);
    const key = `angles:${items.map((i) => `${i.angle}:${i.take.id}`).join()}`;
    emptyAngles.hidden = items.length > 0;
    if (sheet.dataset.key === key) return;
    sheet.dataset.key = key;
    sheetTakes.clear();
    sheet.replaceChildren(...items.map(({ angle, take }) => {
      const move = catalog.moves.find((m) => m.id === take.recipe?.rig?.movement) ?? { id: "static", label: "Static", path: [] };
      const pivot = angleGeometry(catalog, angle);
      const shown = pivot && move.path?.length ? { ...move, path: withAngle(move.path, pivot) } : move;
      const c = card(shown, take, { label: describeAngle(catalog, angle), sub: `${move.label} · ${take.recipe?.rig?.duration_seconds ?? ""} s`, id: angle });
      sheetTakes.set(c, take);
      return c;
    }));
    if (playing) paintPlayAll();
  }

  caption.addEventListener("click", async () => {
    const state = store.get();
    const ids = new Set(chosen);
    const takes = state.takes.filter((take) => ids.has(take.id));
    const first = takes[0]?.id ?? [...chosen][0];
    if (!first) return;
    const text = captionFor({ takes, url: takeLink(first), moves: state.moves });
    if (await copyText(text)) notify(ctx, "Caption copied.", "Paste it with the video. Edit freely.");
    else notify(ctx, "Could not copy the caption.", "Your browser blocked copying. Copy the take's link instead.", "error");
  });

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
    const thumb = h("span", { class: "take-thumb" }, poster);
    const body = h("button", { type: "button", class: "take-row-main" },
      thumb, h("span", { class: "take-text" }, h("b", { class: "take-title" }), h("span", { class: "hint take-sub" })),
      h("span", { class: "take-kind" }), h("span", { class: "take-len num hint" }), h("span", { class: "take-id" }), h("span", { class: "take-when hint" }), h("span", { class: "take-state" }));
    body.addEventListener("click", () => controller.select(take.id));
    // the row's take plays in its thumb under the hand: read again each time, so a take that finished since has its file
    hoverPlay(body, (width) => hoverClip(store, store.get().takes.find((t) => t.id === take.id) ?? take, api)(width), { into: thumb });
    return h("li", { class: "take-row" }, h("label", { class: "take-check", title: "Add to reel" }, check), body);
  }

  function paintRow(li, take) {
    const state = store.get();
    li.dataset.depth = take.parent && state.takes.some((t) => t.id === take.parent) ? "1" : "0";
    li.querySelector(".take-row-main").setAttribute("aria-current", String(state.selected === take.id));
    setPoster(li.querySelector("img"), posterAttrs(state, take, api, "96px"));
    setText(li.querySelector(".take-title"), titleOf(take));
    setText(li.querySelector(".take-sub"), subline(take, state.moves));
    li.querySelector(".take-kind").replaceChildren(pill(KIND[take.kind] ?? take.kind));
    setText(li.querySelector(".take-len"), take.seconds ? `${take.seconds.toFixed(1)} s` : "");
    li.querySelector(".take-id").replaceChildren(...[identityPill(take.identity)].filter(Boolean));
    setText(li.querySelector(".take-when"), take.recording ? "Recorded" : ago(take.created_at));
    fill(li.querySelector(".take-state"), take.replay ? pill("Replay", "amber") : take.recording ? pill("Recorded take", null, { dot: true }) : take.status === "succeeded" ? null : pill(statusLabel(take), take.status === "failed" ? "red" : take.status === "canceled" ? null : "accent"));
    const can = !take.recording && reelable([take]).length > 0 && api.kind !== "static" && !state.status?.backend?.locked;
    const box = li.querySelector("input");
    box.hidden = !can;
    box.checked = chosen.has(take.id);
  }

  function paintReel() {
    const n = chosen.size;
    reelBar.hidden = n === 0;
    setText(reelBar.querySelector(".reel-count"), `${n} take${n === 1 ? "" : "s"} selected`);
    caption.disabled = n === 0;
    reel.disabled = n < 2 || n > 8;
    reel.title = n < 2 ? "Pick at least two takes" : n > 8 ? "A reel joins up to eight takes" : "";
  }

  function paint() {
    const state = store.get();
    const recordings = recordingIds(state);
    const all = [...ledgerTakes(state.takes).map((t) => (recordings.has(t.id) ? { ...t, recording: true } : t)), ...stripItems({ ...state, takes: [] }, [...FILM_KINDS]).filter((r) => !state.takes.some((t) => t.id === r.id))]
      .sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
    const shown = all.filter((t) => filter === "all" || filter === "wall" || t.kind === filter);
    const onWall = filter === "wall";
    wall.el.hidden = !onWall;
    if (onWall) { // one monitor per recording: a replay of a recorded take shows once
      const seen = new Set();
      wall.paint(all.filter((t) => { const id = t.replay_of ?? t.id; return !seen.has(id) && seen.add(id); }));
    }
    // a take's exports and remixes follow it, indented; one whose source is not on the list stands alone
    const under = children(shown);
    const present = new Set(shown.map((t) => t.id));
    const items = shown.filter((t) => !t.parent || !present.has(t.parent)).flatMap((t) => [t, ...(under[t.id] ?? [])]);
    list.dataset.identity = String(items.some((t) => Object.keys(t.identity ?? {}).length > 0));
    flip(list, () => renderList(list, items, (t) => t.id, (t) => { const li = row(t); paintRow(li, t); return li; }, paintRow), { keys: items.map((t) => t.id) }); // a re-rank glides
    const sheetMode = filter === "moves" || filter === "angles";
    sheet.hidden = !sheetMode;
    sheet.setAttribute("aria-label", filter === "angles" ? "One take for every recorded camera position" : "One take for every promoted camera move");
    if (filter === "moves") paintSheet(state);
    else if (filter === "angles") paintAngles(state);
    if (filter !== "angles") emptyAngles.hidden = true;
    playAll.hidden = !sheetMode || holdStill() || (filter === "angles" && !emptyAngles.hidden);
    sheetHint.hidden = !sheetMode || (filter === "angles" && !emptyAngles.hidden); // an empty sheet has nothing to hover
    setText(sheetHint, filter === "angles" ? "Same shot from each camera position. Hover one or play all." : "Same still for every card. Hover one or play all.");
    if (!sheetMode && playing) { playing = false; paintPlayAll(); }
    list.hidden = sheetMode || onWall || items.length === 0;
    empty.hidden = sheetMode || items.length > 0;
    // what the recorded takes cost to make, summed from their receipts (failed tries and idle time are not in it)
    const gpu = state.status?.gpu;
    const ledger = all.length ? ledgerLine(gpu) : null;
    fill(el.querySelector(".count"), h("span", { class: "num" }, all.length ? String(all.length) : " ")); // the count's line is held from the first paint, so the head never grows when it fills in
    setText(ledgerEl, ledger ? `the recorded takes took ${ledger}` : "");
    ledgerEl.title = ledger ? "GPU time from the receipts. Failed tries excluded." : "";
    ledgerEl.hidden = Boolean(state.status) && !ledger; // the status is in and has no ledger to print: the line gives its room back
    for (const id of [...chosen]) if (!items.some((t) => t.id === id)) chosen.delete(id);
    paintReel();
  }
  store.subscribe((_, changed) => changed.some((k) => ["takes", "recorded", "selected", "status", "moves", "previews"].includes(k)) && paint());
  paint();
  return { el };
}
