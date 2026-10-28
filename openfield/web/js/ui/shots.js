// The Shots station: one still re-shot as nine setups (wide, close-up, the three-quarters, both profiles, low, high,
// from behind), each a Qwen-Image 2.1 edit checked like an anchor. Start from a take's still or your own image; send
// any setup to Direct as the shot's first frame, or change it with words.

import { fileOf, fromRecorded, posterAttrs, stillThumb, thumbOf, titleOf } from "../lib/stages.js";
import { h, icon, renderList, setText } from "./dom.js";
import { identityPill } from "./monitor.js";
import { animateStill } from "./actions.js";
import { hoverClip, hoverPlay } from "./hoverplay.js";
import { openEditSheet } from "./edit.js";

const ACTIVE = new Set(["queued", "running", "awaiting_approval"]);
const pool = (state) => [...state.takes, ...state.recorded.map((r) => ({ ...fromRecorded(r), recording: true }))];

/** The newest board made from a take, this install's own first; a recording (a take too in the hosted copy) or its replay is `recording`. */
export function boardFor(state, takeId) {
  const src = pool(state).find((t) => t.id === takeId); // a replayed source still owns its recorded board
  const ids = new Set([takeId, src?.replay_of].filter(Boolean));
  const recorded = new Set(state.recorded.map((r) => r.id));
  const all = pool(state).filter((t) => t.kind === "shots" && ids.has(t.recipe?.take))
    .map((t) => (recorded.has(t.id) || recorded.has(t.replay_of) ? { ...t, recording: true } : t));
  return all.find((t) => ACTIVE.has(t.status)) ?? all.find((t) => t.status === "succeeded" || t.recording) ?? null;
}

/**
 * What the room opens on: a start take on the strip that owns a board; else a finished board whose start take is not in
 * this copy (its nine stills are, so the room still opens on a real board: the showcase reel's choice, then the newest);
 * else the first start take. `pinned` names that board when its start take is missing.
 */
export function openingBoard(state, starts) {
  const owned = starts.find((t) => boardFor(state, t.id));
  if (owned) return { source: owned.id, pinned: null };
  const reel = state.status?.hero_reel ?? [];
  const rank = (t) => reel.indexOf(t.id) + 1 || 999;
  const board = pool(state).filter((t) => t.kind === "shots" && t.status === "succeeded" && t.shots?.length)
    .sort((a, b) => rank(a) - rank(b) || String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")))[0];
  if (board) return { source: board.recipe?.take ?? null, pinned: board.id };
  return starts.length ? { source: starts[0].id, pinned: null } : null;
}

/** A tile's key: its board, its setup and its still, so only a new still makes a new tile. */
export const tileKey = ({ take, i, shot }) => `${take?.id}:${i}:${shot?.file ?? "pending"}`;

export function createShotsStation(ctx) {
  const { api, store, controller } = ctx;
  let source = null; // the id of the take whose still the board starts from
  let upload = null; // or a File the person picked (live only)
  let focus = 0; // the setup chosen on the board (1-9), 0 for none
  let pinned = null; // the board this station started or replayed last (an upload's board names no take)
  let followed = null; // the last opened board this station followed
  const sources = h("div", { class: "shots-sources", role: "radiogroup", "aria-label": "Start from a take" });
  const pickFile = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp", class: "sr-only", tabindex: "-1", "aria-label": "Your image" });
  const own = h("button", { type: "button", class: "btn secondary sm" }, icon("upload", "sm"), "My image…");
  own.addEventListener("click", () => pickFile.click());
  pickFile.addEventListener("change", () => { if (pickFile.files[0]) { upload = pickFile.files[0]; source = null; paint(); } pickFile.value = ""; });
  const shoot = h("button", { type: "button", class: "btn primary" }, icon("grid-3x3"), h("span", null, "Shoot 9 setups"));
  const plan = h("p", { class: "plan-line hint" });
  const board = h("div", { class: "shots-board", role: "list", "aria-label": "Nine setups of one still" });
  const animate = h("button", { type: "button", class: "btn secondary" }, icon("clapperboard"), "Animate this setup in Direct");
  const edit = h("button", { type: "button", class: "btn secondary" }, icon("image"), "Edit this setup…");
  const status = h("p", { class: "hint shots-status", "aria-live": "polite" });
  const el = h("section", { class: "shots-station", "aria-label": "Shots" },
    h("div", { class: "station-head" }, h("h1", null, "Shots"),
      h("p", { class: "hint" }, "One still, nine setups.")),
    h("div", { class: "shots-pick" }, h("span", { class: "label" }, "Start from"), sources, own, pickFile),
    h("div", { class: "shots-go" }, shoot, plan),
    board, h("div", { class: "shots-after" }, animate, edit, status));

  const locked = () => Boolean(store.get().status?.backend?.locked) || api.kind === "static";
  const finished = (state) => pool(state).filter((t) => t.status === "succeeded");
  const shownBoard = (state) => {
    const mine = pinned && pool(state).find((t) => t.id === pinned);
    const recorded = new Set(state.recorded.map((r) => r.id)); // the hosted copy lists its recordings as takes too
    if (mine && (!source || mine.recipe?.take === source)) {
      return recorded.has(mine.id) || recorded.has(mine.replay_of) ? { ...mine, recording: true } : mine;
    }
    return source ? boardFor(state, source) : null;
  };

  function paintSources(state) {
    const takes = finished(state).filter((t) => t.kind === "direct" && fileOf(t, "poster"));
    const seen = new Set();
    const unique = takes.filter((t) => { const id = t.replay_of ?? t.id; if (seen.has(id)) return false; seen.add(id); return true; });
    const reel = state.status?.hero_reel ?? [];
    unique.sort((a, b) => ((reel.indexOf(a.id) + 1 || 999) - (reel.indexOf(b.id) + 1 || 999)));
    if (!source && !upload && !pinned) {
      const opening = openingBoard(state, unique);
      if (opening) ({ source, pinned } = opening);
    }
    sources.replaceChildren(...unique.slice(0, 24).map((t) => {
      const b = h("button", { type: "button", role: "radio", class: "shots-source", "aria-checked": String(t.id === source), title: titleOf(t) },
        h("img", { ...posterAttrs(state, t, api, "96px"), alt: titleOf(t), loading: "lazy", draggable: "false" }),
        boardFor(state, t.id) ? h("span", { class: "shots-has", "aria-hidden": "true" }, icon("grid-3x3", "sm")) : null);
      b.addEventListener("click", () => { source = t.id; upload = null; focus = 0; paint(); });
      hoverPlay(b, hoverClip(store, t, api)); // a source plays its take under the hand; the board's setups are stills
      return b;
    }));
  }

  const ghostOf = (still) => h("img", { class: "shots-ghost", src: still, alt: "", loading: "lazy", draggable: "false" });
  function tile({ shot, take, i, planned, still }) {
    // before a still lands, the tile previews the plan: the source, dimmed, under the setup it will become
    if (!shot) return h("div", { class: "shots-tile pending", role: "listitem" }, still ? ghostOf(still) : null, h("span", { class: "shots-label" }, planned?.label ?? `Setup ${i + 1}`));
    const b = h("button", { type: "button", class: "shots-tile", role: "listitem", "aria-pressed": String(focus === shot.index) },
      h("img", { src: stillThumb(store.get(), take, shot.file, api), alt: `${shot.label}`, loading: "lazy", decoding: "async", draggable: "false" }),
      h("span", { class: "shots-label" }, shot.label), shot.identity ? identityPill({ shot: shot.identity }) : null); // a map, as overall() reads
    b.addEventListener("click", () => { focus = focus === shot.index ? 0 : shot.index; paint(); });
    return b;
  }
  // a tile that stays keeps its picture (its entrance has played): a click only moves the pressed state, and previews that
  // land after the tile give it the small copy of its still
  function retouch(el, { shot, take, still }) {
    if (shot) {
      el.setAttribute("aria-pressed", String(focus === shot.index));
      const picture = el.querySelector("img");
      const small = stillThumb(store.get(), take, shot.file, api);
      if (picture && picture.getAttribute("src") !== small) picture.setAttribute("src", small);
      if (shot.identity && !el.querySelector(".pill")) { const p = identityPill({ shot: shot.identity }); if (p) el.append(p); } // a face check that lands after its still
      return;
    }
    const ghost = el.querySelector(".shots-ghost"); // a pending tile follows the source it previews
    if ((ghost?.getAttribute("src") ?? null) === still) return;
    ghost?.remove();
    if (still) el.prepend(ghostOf(still));
  }

  function paint() {
    const state = store.get();
    const catalog = state.moves?.shots;
    if (!catalog) return;
    // a board opened from the wall or a link is the one shown, with its source picked
    const sel = state.selected && state.selected !== followed ? pool(state).find((t) => t.id === state.selected) : null;
    if (sel?.kind === "shots") { followed = sel.id; pinned = sel.id; source = sel.recipe?.take ?? source; upload = null; focus = 0; }
    paintSources(state);
    own.hidden = locked();
    const take = shownBoard(state);
    const shots = take?.shots ?? [];
    const running = take && ACTIVE.has(take.status);
    const sourceTake = source && finished(state).find((t) => t.id === source);
    const still = upload ? null : sourceTake && fileOf(sourceTake, "poster") ? thumbOf(state, sourceTake, api) : null;
    // keyed by board, setup and still: a new still is a new tile (and plays its entrance); the rest stay
    renderList(board, catalog.board.map((planned, i) => ({ shot: shots[i], take, i, planned, still })), tileKey, tile, retouch);
    board.dataset.state = running ? "running" : take ? "done" : "empty";
    const recordedHere = take && (take.recording || take.replay);
    if (locked()) {
      setText(shoot.querySelector("span"), take ? "Show the recorded board" : "Not recorded in this copy");
      shoot.disabled = !source || !boardFor(state, source)?.recording || Boolean(running);
    } else {
      setText(shoot.querySelector("span"), running ? "Shooting…" : "Shoot 9 setups");
      shoot.disabled = Boolean(running) || (!source && !upload);
    }
    plan.replaceChildren(`9 stills · Qwen-Image 2.1 edits · checked against ${upload ? "your image" : "the take's still"}`);
    animate.disabled = !focus || locked() || !take;
    animate.title = locked() ? "Connect a backend to animate a still" : focus ? "" : "Pick a setup on the board first";
    edit.disabled = !focus || take?.status !== "succeeded";
    edit.title = focus ? "" : "Pick a setup on the board first";
    setText(status, running ? `Setup ${shots.length} of 9…` : take ? `${recordedHere ? "Recorded board" : "Board"} · ${titleOf(take)}` : upload ? `Your image: ${upload.name}` : "");
  }

  shoot.addEventListener("click", async () => {
    const state = store.get();
    if (locked()) {
      const rec = boardFor(state, source);
      if (rec?.recording) { const out = await controller.recreate(rec.replay_of ?? rec.id); if (out) { pinned = out.id; paint(); } }
      return;
    }
    const form = new FormData();
    form.append("request", JSON.stringify(upload ? {} : { take: source }));
    if (upload) form.append("source", upload, upload.name);
    const out = await controller.startShots(form);
    if (out) { focus = 0; pinned = out.id; paint(); }
  });

  const chosen = () => {
    const take = shownBoard(store.get());
    return { take, shot: take?.shots?.find((s) => s.index === focus) };
  };
  animate.addEventListener("click", () => {
    const { take, shot } = chosen();
    if (shot) animateStill(ctx, take, shot.file, shot.label, `${shot.angle.replaceAll("/", "-")}.png`);
  });
  edit.addEventListener("click", () => {
    const { take, shot } = chosen();
    if (shot) openEditSheet(ctx, take, { still: shot.file });
  });

  store.subscribe((_, changed) => changed.some((k) => ["takes", "recorded", "status", "moves", "selected", "previews"].includes(k)) && paint());
  paint();
  return { el };
}
