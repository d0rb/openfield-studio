// The Move Pad: twelve promoted camera moves as path glyphs, the rest under "More", and a live
// top and side view of the chosen path with numbered anchor stills.

import { anchorsAlong, glyph, heading, sideFit, topFit } from "../lib/pathview.js";
import { describeMove, locate, organise, step } from "../lib/movepad.js";
import { h, icon, svg } from "./dom.js";
import { pill } from "./controls.js";

const ARROW = "M-4 -3.2 L4 0 L-4 3.2 Z";
const stroke = { "vector-effect": "non-scaling-stroke" };

function tileGlyph(move) {
  const g = glyph(move);
  const root = svg("svg", { viewBox: "0 0 100 100", class: "glyph", "aria-hidden": "true" });
  if (g.kind === "path") {
    root.append(
      svg("path", { d: g.d, class: "g-path", ...stroke }),
      svg("circle", { cx: g.start.x, cy: g.start.y, r: 4, class: "g-start" }),
      svg("path", { d: ARROW, class: "g-head", transform: `translate(${g.end.x} ${g.end.y}) rotate(${g.angle}) scale(2)` }),
    );
  } else if (g.kind === "zoom") {
    const [outer, inner] = g.direction === "in" ? [34, 17] : [17, 34];
    root.append(
      svg("rect", { x: 50 - outer, y: 50 - outer * 0.62, width: outer * 2, height: outer * 1.24, rx: 3, class: "g-frame faint", ...stroke }),
      svg("rect", { x: 50 - inner, y: 50 - inner * 0.62, width: inner * 2, height: inner * 1.24, rx: 3, class: "g-frame", ...stroke }),
    );
  } else if (g.kind === "turn") {
    root.append(svg("path", { d: "M26 62 A26 26 0 0 1 74 62", class: "g-path", ...stroke }), svg("path", { d: ARROW, class: "g-head", transform: "translate(74 62) rotate(60) scale(1.5)" }));
  } else {
    root.append(svg("circle", { cx: 50, cy: 50, r: 16, class: "g-frame", ...stroke }));
  }
  return root;
}

function planView(move, which) {
  const poses = move.path;
  const view = which === "top" ? topFit(poses, { pad: 18 }) : sideFit(poses, { pad: 18 });
  const root = svg("svg", { viewBox: "0 8 100 84", class: "path-plan", role: "img", "aria-label": `${which === "top" ? "Top" : "Side"} view of the camera path` });
  root.append(
    svg("line", { x1: 12, y1: 50, x2: 88, y2: 50, class: "p-axis", ...stroke }),
    svg("line", { x1: 50, y1: 12, x2: 50, y2: 88, class: "p-axis", ...stroke }),
    svg("circle", { cx: view.origin.x, cy: view.origin.y, r: 4.5, class: "g-subject" }),
    svg("path", { d: view.d, class: "p-path", pathLength: "1" }), // drawn on over 180 ms; its width is in user units so the dash can follow it
  );
  const spots = move.mode === "keyframed" ? anchorsAlong(view, Math.max(2, move.anchors)) : [view.points[0]];
  spots.forEach((p, i) => {
    root.append(svg("circle", { cx: p.x, cy: p.y, r: 6, class: "p-anchor" }), svg("text", { x: p.x, y: p.y + 2.6, class: "p-num", "text-anchor": "middle" }, String(i + 1)));
  });
  if (which === "top") {
    // the camera is drawn last and a step ahead of each end of the path, along the way it faces, so no anchor hides it
    for (const index of [0, poses.length - 1]) {
      const at = view.points[index];
      const dir = heading(poses[index]);
      root.append(svg("path", { d: ARROW, class: "p-cam", transform: `translate(${at.x + dir.x * 12} ${at.y + dir.y * 12}) rotate(${(Math.atan2(dir.y, dir.x) * 180) / Math.PI}) scale(1.4)` }));
    }
  }
  return root;
}

export function createMovePad({ forms, store }) {
  const el = h("div", { class: "movepad" });
  const grid = h("div", { class: "move-grid", role: "radiogroup", "aria-label": "Camera move" });
  const preview = h("div", { class: "move-preview" });
  const info = h("div", { class: "move-info" });
  const moreToggle = h("button", { type: "button", class: "btn ghost sm more-toggle", "aria-expanded": "false" });
  const more = h("div", { class: "move-more", hidden: true });
  el.append(grid, preview, info, moreToggle, more);

  let organised = null;
  const tiles = new Map(); // promoted moves: a radio group with arrow keys
  const rows = new Map(); // the rest: toggle buttons, each its own tab stop
  let shown = null;
  let opened = null;

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
    moreToggle.replaceChildren(icon(open ? "chevron-up" : "chevron-down", "sm"), `${open ? "Hide" : "More"} moves (${total})`);
  };
  moreToggle.addEventListener("click", () => setMore(moreToggle.getAttribute("aria-expanded") !== "true"));

  function build(catalog) {
    organised = organise(catalog);
    tiles.clear();
    rows.clear();
    grid.replaceChildren(...organised.featured.map((m) => {
      const tile = h("button", { type: "button", role: "radio", class: "move-tile", "aria-checked": "false", tabindex: "-1" }, tileGlyph(m), h("span", null, m.label));
      tile.addEventListener("click", () => choose(m.id));
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
    shown = null;
  }

  function update() {
    const catalog = store.get().moves;
    const { rig, quick } = forms.get().direct;
    if (!catalog || !rig) return;
    if (!organised || organised.moves.size !== catalog.moves.length) build(catalog);
    const current = organised.moves.get(rig.movement);
    const promoted = tiles.has(rig.movement);
    for (const [id, tile] of tiles) {
      tile.setAttribute("aria-checked", String(id === rig.movement));
      tile.tabIndex = id === rig.movement ? 0 : -1;
    }
    if (!promoted) grid.firstElementChild.tabIndex = 0; // the grid stays reachable when the choice lives under "More"
    for (const [id, row] of rows) row.setAttribute("aria-pressed", String(id === rig.movement));
    if (current && locate(organised, rig.movement)?.hidden && opened !== rig.movement) {
      opened = rig.movement;
      setMore(true); // once per choice, so a person can close it again
    }
    const key = `${rig.movement}|${quick}`;
    if (key === shown || !current) return;
    shown = key;
    const d = describeMove(current, { quick });
    preview.replaceChildren(
      h("figure", null, planView(current, "top"), h("figcaption", null, "Top view")),
      h("figure", null, planView(current, "side"), h("figcaption", null, "Side view")),
    );
    info.replaceChildren(
      h("div", { class: "move-name" }, h("strong", null, current.label), pill(d.modeLabel, d.mode === "experimental" ? "amber" : "accent"), h("span", { class: "hint" }, d.stillsLabel)),
      h("p", { class: "hint" }, d.hint),
      h("p", { class: "hint tested", "data-tested": String(d.tested) }, icon(d.tested ? "badge-check" : "circle-dashed", "sm"), d.testedLabel),
    );
  }

  forms.subscribe(update);
  store.subscribe((_, changed) => changed.includes("moves") && update());
  update();
  return { el, update };
}
