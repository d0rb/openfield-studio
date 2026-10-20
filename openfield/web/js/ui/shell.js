// The shell: top bar, station rail, the workspace for the current station, the dock, and notices.

import { linkFromHash } from "../lib/remix.js";
import { initialDirect } from "../lib/direct.js";
import { h, icon, setText } from "./dom.js";
import { pill } from "./controls.js";
import { notify, remixFrom } from "./actions.js";
import { createPrompt, createDirectDock } from "./direct.js";
import { createReshootPrompt, createReshootDock, reshootEmpty } from "./reshoot.js";
import { createCastStation, createCastDock } from "./cast.js";
import { createTakes } from "./takes.js";
import { createMonitor } from "./monitor.js";
import { createFilmstrip } from "./filmstrip.js";
import { createDetails } from "./details.js";

export const STATIONS = [
  { id: "cast", label: "Cast", icon: "users-round" },
  { id: "direct", label: "Direct", icon: "clapperboard" },
  { id: "reshoot", label: "Re-shoot", icon: "repeat-2" },
  { id: "takes", label: "Takes", icon: "film" },
];
const ROUTES = new Set(STATIONS.map((s) => s.id));

export function routeFromHash(hash = location.hash) {
  const m = /^#\/([a-z]+)/.exec(hash);
  return m && ROUTES.has(m[1]) ? m[1] : "direct";
}

function directEmpty({ store }) {
  const locked = Boolean(store.get().status?.backend?.locked);
  const none = store.get().recorded.length === 0;
  return h("div", { class: "empty" }, icon("clapperboard", "lg"), h("h2", null, "Nothing shot yet"),
    h("p", null, locked && none
      ? "There are no recorded takes in this copy, and no backend is connected. Connect Comfy Cloud or a GPU box to render, or add recorded takes."
      : "Describe a shot above, choose a camera move in Settings, and press Shoot. Stills come first, so you can approve them before the video renders."));
}

function backendMenu(ctx) {
  const { store, controller } = ctx;
  const wrap = h("div", { class: "menu-wrap" });
  const button = h("button", { type: "button", class: "backend-btn", "aria-haspopup": "true", "aria-expanded": "false" });
  const menu = h("div", { class: "menu", hidden: true });
  wrap.append(button, menu);
  const close = () => { menu.hidden = true; button.setAttribute("aria-expanded", "false"); };
  button.addEventListener("click", () => { const open = menu.hidden; menu.hidden = !open; button.setAttribute("aria-expanded", String(open)); });
  document.addEventListener("click", (e) => !wrap.contains(e.target) && close());
  document.addEventListener("keydown", (e) => e.key === "Escape" && !menu.hidden && (close(), button.focus()));

  function paint() {
    const status = store.get().status;
    if (!status) {
      button.replaceChildren(h("span", { class: "status-dot" }), h("span", { class: "label-text" }, "Connecting…"));
      return;
    }
    const b = status.backend;
    const tone = !b.health?.ok ? "red" : b.locked ? "amber" : "green";
    button.replaceChildren(h("span", { class: "status-dot", "data-tone": tone }), h("span", { class: "label-text" }, b.locked ? "Replay · recorded takes" : b.label), icon("chevron-down", "sm"));
    const rows = [
      h("div", null, h("b", null, b.locked ? "Replay" : b.label), h("p", { class: "hint" }, b.locked
        ? "Watching takes that were rendered for real and recorded with their receipts. Nothing renders here."
        : b.health?.ok ? "Connected. New takes render on this backend." : `Not reachable: ${b.health?.detail ?? "unknown"}.`)),
    ];
    if (b.health?.detail && b.health.ok && !b.locked) rows.push(h("p", { class: "hint" }, b.health.detail));
    if (b.sdk_configured && b.locked) {
      const sw = h("button", { type: "button", class: "btn secondary" }, icon("cloud"), "Switch to the render backend");
      sw.addEventListener("click", async () => { await controller.setBackend("sdk"); close(); });
      rows.push(sw);
    } else if (!b.sdk_configured && b.locked) {
      rows.push(h("p", { class: "hint" }, "To render, set COMFY_BASE_URL (a GPU box) or COMFY_API_KEY (Comfy Cloud) in .env and restart. See docs/POD.md."));
    }
    if (!b.locked && b.kind !== "replay") {
      const sw = h("button", { type: "button", class: "btn secondary" }, icon("film"), "Switch to Replay");
      sw.addEventListener("click", async () => { await controller.setBackend("replay"); close(); });
      rows.push(sw);
    }
    const face = status.face_check;
    rows.push(h("p", { class: "hint" }, icon(face?.available ? "scan-face" : "circle-dashed", "sm"), face?.available ? " Face check ready (runs on this computer)." : " Face check is off. Run `openfield doctor --fetch-models` to enable it."));
    menu.replaceChildren(...rows);
  }
  store.subscribe((_, changed) => changed.includes("status") && paint());
  paint();
  return wrap;
}

export function mountShell(ctx) {
  const { root, api, store, forms, controller } = ctx;
  const ui = ctx.ui;

  // -- chrome ----------------------------------------------------------------------------------
  const crumb = h("span", null);
  const open = h("input", { type: "file", accept: ".mp4,.png,.json", class: "sr-only", tabindex: "-1", "aria-label": "Choose an OpenField video, image or receipt" });
  const openBtn = h("button", { type: "button", class: "btn secondary", "aria-label": "Open file", title: "Open a receipt, or a video or image OpenField made, to remix it" }, icon("folder-open"), h("span", { class: "btn-label" }, "Open file"));
  openBtn.addEventListener("click", () => open.click());
  open.addEventListener("change", () => { if (open.files[0]) remixFrom(ctx, open.files[0]); open.value = ""; });
  const dockToggle = h("button", { type: "button", class: "btn ghost icon-only", "aria-label": "Show settings", "aria-expanded": "true", title: "Show or hide the panel ( [ )" }, icon("panel-right"));
  const topbar = h("header", { class: "topbar" },
    h("div", { class: "brand" }, h("span", { class: "brand-mark", "aria-hidden": "true" }, "OF"), h("span", { class: "wordmark" }, "OpenField Studio")),
    h("div", { class: "crumb" }, icon("chevron-right", "sm"), h("b", null, crumb)),
    h("span", { class: "grow" }),
    h("div", { class: "topbar-actions" }, openBtn, backendMenu(ctx), dockToggle, open));
  const rail = h("nav", { class: "rail", "aria-label": "Stations" }, STATIONS.map((s) => {
    const a = h("a", { class: "rail-item", href: `#/${s.id}`, "data-route": s.id }, icon(s.icon), h("span", null, s.label));
    return a;
  }));
  const stage = h("main", { class: "stage", id: "main", tabindex: "-1" });
  const dockTabs = h("div", { class: "tabs", role: "tablist" });
  const tabSettings = h("button", { type: "button", role: "tab", id: "tab-settings", "aria-selected": "true" }, "Settings");
  const tabTake = h("button", { type: "button", role: "tab", id: "tab-take", "aria-selected": "false" }, "Take");
  dockTabs.append(tabSettings, tabTake);
  const dockBody = h("div", { class: "dock-body" });
  const dock = h("aside", { class: "dock", "aria-label": "Settings and take details" }, dockTabs, dockBody);
  const notices = h("div", { class: "notices", "aria-live": "polite" });
  const app = h("div", { class: "app", "data-dock": "open" }, topbar, rail, stage, dock);
  root.replaceChildren(h("a", { class: "skip", href: "#main" }, "Skip to the workspace"), app, notices);

  // -- stations (built once, shown one at a time) ----------------------------------------------------
  const monitorDirect = createMonitor({ ...ctx, scope: "direct", empty: () => directEmpty(ctx) });
  const monitorReshoot = createMonitor({ ...ctx, scope: "reshoot", empty: () => reshootEmpty(ctx) });
  const station = (id, ...kids) => h("div", { class: "station", "data-station": id, hidden: true }, STATIONS.find((s) => s.id === id).id === "cast" || id === "takes" ? null : h("h1", { class: "sr-only" }, STATIONS.find((s) => s.id === id).label), kids);
  const stations = {
    direct: station("direct", createPrompt(ctx).el, monitorDirect.el, createFilmstrip({ ...ctx, scope: "direct" }).el),
    reshoot: station("reshoot", createReshootPrompt(ctx).el, monitorReshoot.el, createFilmstrip({ ...ctx, scope: "reshoot" }).el),
    cast: station("cast", createCastStation(ctx).el),
    takes: station("takes", createTakes(ctx).el),
  };
  stage.append(...Object.values(stations));
  const docks = { direct: createDirectDock(ctx).el, reshoot: createReshootDock(ctx).el, cast: createCastDock(ctx).el };
  const details = createDetails(ctx);
  dockBody.append(...Object.values(docks), details.el);

  // -- routing and dock --------------------------------------------------------------------------
  const compact = () => matchMedia("(max-width: 1179px)").matches;
  function paintDock() {
    const { dockOpen, dockTab } = ui.get();
    const route = store.get().route;
    const hasSettings = route !== "takes";
    const tab = hasSettings ? dockTab : "take";
    app.dataset.dock = dockOpen ? "open" : "closed";
    dockToggle.setAttribute("aria-expanded", String(dockOpen));
    dockToggle.setAttribute("aria-label", dockOpen ? "Hide the panel" : "Show the panel");
    tabSettings.hidden = !hasSettings;
    tabTake.hidden = route === "cast";
    tabSettings.setAttribute("aria-selected", String(tab === "settings"));
    tabTake.setAttribute("aria-selected", String(tab === "take"));
    for (const [id, pane] of Object.entries(docks)) pane.hidden = !(tab === "settings" && id === route);
    details.el.hidden = tab !== "take";
    if (tab === "take") details.render();
  }
  function paintRoute() {
    const route = store.get().route;
    for (const [id, node] of Object.entries(stations)) node.hidden = id !== route;
    for (const a of rail.children) (a.dataset.route === route ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
    setText(crumb, STATIONS.find((s) => s.id === route).label);
    document.title = `${STATIONS.find((s) => s.id === route).label} · OpenField Studio`;
    ui.set({ dockTab: route === "takes" ? "take" : "settings" }); // each station opens on its own panel
    paintDock();
  }
  ui.go = (route) => {
    if (!ROUTES.has(route)) return;
    if (location.hash !== `#/${route}`) history.pushState(null, "", `#/${route}`);
    store.set({ route });
  };
  ui.openDock = (tab) => { ui.set({ dockOpen: true, dockTab: tab }); };
  window.addEventListener("hashchange", async () => {
    const link = linkFromHash(location.hash);
    if (link) { history.replaceState(null, "", `#/${store.get().route}`); await remixFrom(ctx, link); return; }
    store.set({ route: routeFromHash() });
  });
  tabSettings.addEventListener("click", () => ui.set({ dockTab: "settings" }));
  tabTake.addEventListener("click", () => ui.set({ dockTab: "take" }));
  dockToggle.addEventListener("click", () => ui.set({ dockOpen: !ui.get().dockOpen }));
  document.addEventListener("keydown", (e) => {
    if (e.key === "[" && !e.target.closest?.("input,textarea,select,[contenteditable]")) ui.set({ dockOpen: !ui.get().dockOpen });
    if (e.key === "Escape" && compact() && ui.get().dockOpen && !e.defaultPrevented) ui.set({ dockOpen: false });
  });
  document.addEventListener("click", (e) => { // a floating dock closes when you click the workspace
    if (compact() && ui.get().dockOpen && !dock.contains(e.target) && !dockToggle.contains(e.target) && !e.target.closest(".notice")) ui.set({ dockOpen: false });
  });
  rail.addEventListener("click", (e) => {
    const a = e.target.closest("a");
    if (a) { e.preventDefault(); ui.go(a.dataset.route); stage.focus({ preventScroll: true }); }
  });
  ui.subscribe(paintDock);
  store.subscribe((_, changed) => changed.includes("route") && paintRoute());

  // -- notices ---------------------------------------------------------------------------------
  function paintNotices() {
    notices.replaceChildren(...store.get().notices.map((n) => {
      const close = h("button", { type: "button", class: "btn ghost sm icon-only", "aria-label": "Dismiss" }, icon("x", "sm"));
      close.addEventListener("click", () => controller.dismiss(n.id));
      const tone = n.tone ?? "error";
      if (tone === "info") setTimeout(() => controller.dismiss(n.id), 9000);
      return h("div", { class: "notice", "data-tone": tone, role: tone === "error" ? "alert" : "status" }, icon(tone === "error" ? "triangle-alert" : "info"),
        h("div", null, h("div", { class: "what" }, n.message), n.how ? h("div", { class: "how" }, n.how) : null), close);
    }));
  }
  store.subscribe((_, changed) => changed.includes("notices") && paintNotices());

  // -- first data -------------------------------------------------------------------------------
  const directFrom = (s, recording) => {
    const direct = initialDirect(s.moves);
    if (recording) {
      Object.assign(direct, { subject: recording.recipe.subject ?? "", audio: recording.recipe.audio ?? "", seed: recording.recipe.seed ?? "", orientation: recording.recipe.orientation ?? "landscape", quick: Boolean(recording.recipe.prompt_only) });
      direct.rig = { ...direct.rig, ...(recording.recipe.rig ?? {}) };
      direct.castId = s.cast.find((c) => c.name === recording.recipe.cast_name)?.id ?? null;
    }
    return direct;
  };
  function seedForms() {
    const s = store.get();
    if (!s.moves || forms.get().direct) return;
    forms.set({ direct: directFrom(s, s.status?.backend?.locked ? s.recorded.find((r) => r.kind === "direct") : null) });
  }
  // in Replay the form follows the recording you pick (or the one a replay came from), so Recreate names the take on screen
  function followSelection() {
    const s = store.get();
    if (!s.moves || !s.status?.backend?.locked) return;
    const chosen = s.takes.find((t) => t.id === s.selected);
    const recording = s.recorded.find((r) => r.id === (chosen?.replay_of ?? s.selected) && r.kind === "direct");
    if (recording) forms.set({ direct: directFrom(s, recording) });
  }
  store.subscribe((_, changed) => {
    if (changed.some((k) => ["moves", "recorded", "status", "cast"].includes(k))) seedForms();
    if (changed.includes("selected")) followSelection();
  });
  seedForms();
  paintRoute();
  paintNotices();
  return { app, stage };
}
