// The Move Pad: twelve promoted camera moves as path glyphs, the rest under "More", and a live
// top and side view of the chosen path with numbered anchor stills.

import { withAngle } from "../lib/pathview.js";
import { describeMove, locate, organise, step } from "../lib/movepad.js";
import { ANGLE_DEFAULT, angleGeometry, describeAngle } from "../lib/direct.js";
import { posterAttrs, sampleTake, setPoster } from "../lib/stages.js";
import { h, icon } from "./dom.js";
import { field, pill, segmented } from "./controls.js";
import { createStageView } from "./stageview.js";
import { hoverClip, hoverPlay } from "./hoverplay.js";
import { tilePlan } from "./pathchip.js";
import { liveClip } from "./wall.js";

// the dials' short labels: a camera report's shorthand; the full name is the spoken label and the tooltip
const SHORT = { front: "F", front_right: "FR", right: "R", back_right: "BR", back: "B", back_left: "BL", left: "L", front_left: "FL", low: "Low", eye: "Eye", elevated: "Up", high: "High", close: "Close", medium: "Mid", wide: "Wide" };
const wrap = (n, m) => ((n % m) + m) % m;

/** Hover or keyboard focus on a move's tile plays a real render of the move inside it (the newest take that shows it): a
 * flagged move's own loop is pinned rather than doubled, and the glyph stays alone when no take shows the move. */
function playOnHover(tile, movement, { store, api }) {
  if (!api) return;
  hoverPlay(tile, (width) => {
    const take = sampleTake(store.get(), movement);
    return take ? hoverClip(store, take, api)(width) : null;
  });
}

export function createMovePad({ forms, store, api = null, playhead = null }) {
  const el = h("div", { class: "movepad" });
  const grid = h("div", { class: "move-grid", role: "radiogroup", "aria-label": "Camera move" });
  const preview = h("div", { class: "move-preview", title: "Drag to move the camera. Up and down sets its height." });
  const angleBox = h("div", { class: "angle-box" });
  const info = h("div", { class: "move-info" });
  const moreToggle = h("button", { type: "button", class: "btn ghost sm more-toggle", "aria-expanded": "false" });
  const more = h("div", { class: "move-more", hidden: true });
  el.append(preview, grid, info, angleBox, moreToggle, more); // the stage leads, the grid picks the move, then where the camera starts

  let organised = null;
  const tiles = new Map(); // promoted moves: a radio group with arrow keys
  const rows = new Map(); // the rest: toggle buttons, each its own tab stop
  let shown = null;
  let opened = null;
  let stage = null; // the previs stage at the top of the pad
  let angleCtl = null; // the three dials under it: where the camera starts

  // -- where the camera starts: the dials, and a drag on the stage itself -------------------------------------------
  const setAngle = (angle) => forms.set((s) => ({ direct: { ...s.direct, rig: { ...s.direct.rig, angle } } }));
  const currentAngle = (a) => forms.get().direct?.rig?.angle ?? a?.default ?? ANGLE_DEFAULT;
  function buildAngleControls(catalog) {
    const a = catalog.angles;
    if (!a) return { el: h("span"), set() {} };
    const dial = (label, list, i) => segmented({
      label, options: list.map((s) => ({ value: s.id, label: SHORT[s.id] ?? s.label, name: s.label, title: s.label })),
      value: currentAngle(a).split("/")[i],
      onChange: (v) => { const p = currentAngle(a).split("/"); p[i] = v; setAngle(p.join("/")); },
    });
    // three camera-report fields, like Aperture and Quality; the readout under them is the dock's meta line
    const around = dial("Around", a.azimuths, 0);
    const height = dial("Height", a.elevations, 1);
    const distance = dial("Distance", a.distances, 2);
    const readout = h("p", { class: "move-meta angle-readout", "aria-live": "polite" });
    const reset = h("button", { type: "button", class: "btn ghost sm", title: "Back to the camera position the hero was shot from" }, icon("undo-2", "sm"), "As shot");
    reset.addEventListener("click", () => setAngle(a.default));
    const root = h("div", { class: "angle-controls stack angle-dials" },
      field("Around", around.el).el, field("Height", height.el).el, field("Distance", distance.el).el,
      h("div", { class: "angle-line" }, readout, reset));
    return {
      el: root,
      set(angle) {
        const [az, el_, d] = angle.split("/");
        around.set(az); height.set(el_); distance.set(d);
        const label = describeAngle(catalog, angle);
        readout.replaceChildren(...(label
          ? [label, h("span", { class: "sep" }, "·"), "Hero re-shot from here first."]
          : ["Camera as shot", h("span", { class: "sep" }, "·"), "drag the stage, or pick a position"]));
        reset.hidden = !label;
      },
    };
  }
  // dragging the stage pivots the camera: sideways to the next azimuth stop, up or down to the next height
  const STOP_PX = 36;
  let drag = null;
  preview.addEventListener("pointerdown", (e) => {
    const a = store.get().moves?.angles;
    const frozen = store.get().moves?.moves?.find((m) => m.id === forms.get().direct.rig.movement)?.frozen;
    if (!a || e.button !== 0 || frozen) return; // a frozen move's angles are part of the move
    const [az, el_] = currentAngle(a).split("/");
    drag = { x: e.clientX, y: e.clientY, az: a.azimuths.findIndex((s) => s.id === az), el: a.elevations.findIndex((s) => s.id === el_) };
    preview.setPointerCapture(e.pointerId);
    preview.classList.add("dragging");
  });
  preview.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const a = store.get().moves.angles;
    const az = a.azimuths[wrap(drag.az + Math.round((e.clientX - drag.x) / STOP_PX), a.azimuths.length)].id;
    const lift = e.pointerType === "touch" ? 0 : Math.round((e.clientY - drag.y) / STOP_PX); // a finger scrolls the sheet; height stays on its dial
    const el_ = a.elevations[Math.min(a.elevations.length - 1, Math.max(0, drag.el - lift))].id;
    const next = `${az}/${el_}/${currentAngle(a).split("/")[2]}`;
    if (next !== currentAngle(a)) setAngle(next);
  });
  const endDrag = (e) => {
    if (!drag) return;
    drag = null;
    preview.classList.remove("dragging");
    try { preview.releasePointerCapture(e.pointerId); } catch { /* already released */ }
  };
  preview.addEventListener("pointerup", endDrag);
  preview.addEventListener("pointercancel", endDrag);
  // the stage follows the take on the wall when that take shows the move chosen here; otherwise it rests at the start
  const follow = () => {
    const p = playhead?.get();
    stage?.seek(p && p.movement === forms.get().direct?.rig?.movement ? p.t : 0);
  };
  playhead?.subscribe(follow);

  const choose = (id, focus = false) => {
    forms.set((s) => ({ direct: { ...s.direct, rig: { ...s.direct.rig, movement: id } } }));
    if (focus) tiles.get(id)?.focus();
  };

  grid.addEventListener("keydown", (e) => {
    const delta = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (!delta || !organised) return;
    e.preventDefault();
    choose(step(organised.featured, forms.get().direct.rig.movement, delta), true);
  });

  const setMore = (open) => {
    moreToggle.setAttribute("aria-expanded", String(open));
    more.hidden = !open;
    const total = organised ? organised.groups.reduce((n, g) => n + g.more.length, 0) : 0;
    moreToggle.replaceChildren(icon(open ? "chevron-up" : "chevron-down", "sm"), `${open ? "Hide" : "More"} moves `, h("span", { class: "num" }, `(${total})`));
  };
  moreToggle.addEventListener("click", () => setMore(moreToggle.getAttribute("aria-expanded") !== "true"));

  function build(catalog) {
    organised = organise(catalog);
    tiles.clear();
    rows.clear();
    grid.replaceChildren(...organised.featured.map((m) => {
      const tile = h("button", { type: "button", role: "radio", class: "move-tile", "aria-checked": "false", tabindex: "-1", "data-move": m.id, title: describeMove(m).hint }, tilePlan(m), h("span", null, m.label));
      tile.addEventListener("click", () => choose(m.id));
      playOnHover(tile, m.id, { store, api });
      tiles.set(m.id, tile);
      return tile;
    }));
    more.replaceChildren(...organised.groups.filter((g) => g.more.length).map((g) =>
      h("div", { class: "more-group", role: "group", "aria-label": g.label }, h("div", { class: "more-title" }, g.label),
        ...g.more.map((m) => {
          const row = h("button", { type: "button", class: "more-row", "aria-pressed": "false" },
            h("span", null, m.label), pill(describeMove(m).modeLabel, m.mode === "experimental" ? "amber" : null));
          row.addEventListener("click", () => choose(m.id));
          rows.set(m.id, row);
          return row;
        }))));
    setMore(false);
    angleCtl = buildAngleControls(catalog);
    angleBox.replaceChildren(angleCtl.el);
    shown = null;
  }

  const catalogMove = (id) => store.get().moves?.moves.find((m) => m.id === id);
  function update() {
    const catalog = store.get().moves;
    const { rig, quick } = forms.get().direct;
    if (!catalog || !rig) return;
    if (!organised || organised.moves.size !== catalog.moves.length) build(catalog);
    const current = organised.moves.get(rig.movement);
    const promoted = tiles.has(rig.movement);
    const state = store.get();
    for (const [id, tile] of tiles) {
      tile.setAttribute("aria-checked", String(id === rig.movement));
      tile.tabIndex = id === rig.movement ? 0 : -1;
      // a tile is footage: the poster frame of the newest take that shows the move, under its track
      const take = api ? sampleTake(state, id) : null;
      const picture = take ? posterAttrs(state, take, api, "76px") : null;
      let img = tile.querySelector("img.poster");
      if (picture) {
        if (!img) { img = h("img", { class: "poster", alt: "", loading: "lazy", draggable: "false" }); tile.prepend(img); }
        setPoster(img, picture);
      } else img?.remove();
      // a move checked by eye shows its recorded loop at rest; an untested one keeps its track drawing only
      const loop = catalogMove(id)?.validated && state.previews?.moves?.[id] && state.previews.takes?.[state.previews.moves[id]];
      const clip = tile.querySelector("video.live-clip");
      const wanted = loop ? api.asset?.(loop.video) : null;
      if (wanted && clip?.dataset.src !== wanted) { clip?.remove(); tile.prepend(liveClip({ video: wanted, poster: api.asset(loop.poster) })); }
      else if (!wanted) clip?.remove();
      tile.classList.toggle("live", Boolean(wanted));
    }
    if (!promoted) grid.firstElementChild.tabIndex = 0; // the grid stays reachable when the choice lives under "More"
    for (const [id, row] of rows) row.setAttribute("aria-pressed", String(id === rig.movement));
    if (current && locate(organised, rig.movement)?.hidden && opened !== rig.movement) {
      opened = rig.movement;
      setMore(true); // once per choice, so a person can close it again
    }
    const portrait = forms.get().direct.orientation === "portrait";
    const angle = currentAngle(catalog.angles);
    angleCtl?.set(angle);
    if (angleCtl) angleCtl.el.hidden = Boolean(current?.frozen); // a frozen move (bullet time) sets its own angles
    const key = `${rig.movement}|${quick}|${portrait}|${angle}`;
    if (key === shown || !current) return;
    shown = key;
    const d = describeMove(current, { quick });
    const hollow = current.mode !== "keyframed" || Boolean(quick);
    const pivot = angleGeometry(catalog, angle); // the path starts where the camera starts
    stage = createStageView(current, { hollow, aspect: portrait ? 9 / 16 : 16 / 9, poses: pivot ? withAngle(current.path, pivot) : null });
    preview.replaceChildren(h("figure", { class: "stage-figure" }, stage.el, h("figcaption", null, hollow ? "Planned camera · first still only" : "Planned camera")));
    follow();
    // the name, then one quiet line: how the move is made and how many stills it plans; the long hint is the tooltip
    info.title = d.hint;
    info.replaceChildren(
      h("div", { class: "move-name" }, h("strong", null, current.label)),
      h("p", { class: "move-meta" }, d.modeLabel, h("span", { class: "sep" }, "·"), d.stillsLabel),
    );
  }

  forms.subscribe(update);
  store.subscribe((_, changed) => changed.some((k) => ["moves", "takes", "recorded", "status", "previews"].includes(k)) && update());
  update();
  return { el, update };
}
