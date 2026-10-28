// The shell: top bar, station rail, the workspace for the current station, the dock, and notices.

import { linkFromHash } from "../lib/remix.js";
import { parseHash } from "../lib/route.js";
import { fromRecipe, initialDirect, matchesRecording } from "../lib/direct.js";
import { sampleTake } from "../lib/stages.js";
import { h, icon, leave, setText, svg } from "./dom.js";
import { pill } from "./controls.js";
import { holdStill } from "../lib/motion.js";
import { play } from "./sound.js";
import { createAmbient } from "./ambient.js";
import { notify, remixFrom } from "./actions.js";
import { createPrompt, createDirectDock } from "./direct.js";
import { createReshootPrompt, createReshootDock, reshootEmpty } from "./reshoot.js";
import { createCastStation, createCastDock } from "./cast.js";
import { createTakes } from "./takes.js";
import { createShotsStation } from "./shots.js";
import { createLobby } from "./lobby.js";
import { createChatStation } from "./chat.js";
import { createMonitor } from "./monitor.js";
import { createFilmstrip, stripItems } from "./filmstrip.js";
import { createDetails } from "./details.js";
import { openConnectSheet } from "./connect.js";
import { openSheet } from "./sheet.js";

const KEYS = [
  ["Space, K", "Play or pause the take on the wall"],
  ["J, L", "Back or forward a second"],
  ["← →", "A frame at a time while paused, a second while playing"],
  ["↑ ↓", "The previous or next take in the filmstrip"],
  ["M", "The take's sound on or off"],
  ["F", "Full screen"],
  ["[", "Show or hide the panel"],
  ["Ctrl+Enter", "Shoot, or Recreate a recorded take"],
  ["X", "Flip between before and after (Re-shoot, Flip)"],
  ["C", "Cinema: the take alone, full window"],
  ["Esc", "Close a sheet or a menu, leave cinema"],
  ["?", "This list"],
];
/** The keyboard shortcuts, one sheet: what each key does where the pointer would otherwise go. */
export function showKeys() {
  const list = h("dl", { class: "kv keys-list" }, KEYS.flatMap(([keys, what]) => [h("dt", null, ...keys.split(", ").map((k) => h("kbd", { class: "kbd" }, k))), h("dd", null, what)]));
  return openSheet({ title: "Keyboard", body: h("div", { class: "keys-body" }, list), className: "sheet-keys", focusSheet: true });
}

export const STATIONS = [
  { id: "lobby", label: "Lobby", icon: "ticket" },
  { id: "cast", label: "Cast", icon: "users-round" },
  { id: "direct", label: "Direct", icon: "clapperboard" },
  { id: "shots", label: "Shots", icon: "grid-3x3" },
  { id: "reshoot", label: "Re-shoot", icon: "repeat-2" },
  { id: "takes", label: "Takes", icon: "film" },
  { id: "chat", label: "Chat", icon: "message-square", art: false }, // no rendered prop yet: the icon stands in
];
/** The mark: a strip of floor tape laid as a T, the actor's mark on a set. */
export function tapeMark() {
  return svg("svg", { class: "brand-mark", viewBox: "0 0 20 20", "aria-hidden": "true", focusable: "false" },
    svg("rect", { x: 2, y: 4, width: 16, height: 3, rx: 0.5 }),
    svg("rect", { x: 8.5, y: 7, width: 3, height: 9, rx: 0.5 }));
}

export const ROUTES = new Set(STATIONS.map((s) => s.id));

export function routeFromHash(hash = location.hash) {
  return parseHash(hash, ROUTES).route;
}

function directEmpty({ store }) {
  const locked = Boolean(store.get().status?.backend?.locked);
  const none = store.get().recorded.length === 0;
  return h("div", { class: "empty" }, h("img", { class: "empty-art", src: "art/art-direct.webp", alt: "", loading: "lazy", decoding: "async" }), h("h2", null, "Nothing shot yet"),
    h("p", null, locked && none
      ? "No backend connected. Connect one in the header to render."
      : "Describe a shot. Pick a camera move in Settings. Press Shoot."));
}

function backendMenu(ctx) {
  const { store, controller } = ctx;
  const wrap = h("div", { class: "menu-wrap" });
  const button = h("button", { type: "button", class: "backend-btn", "aria-haspopup": "true", "aria-expanded": "false" });
  const menu = h("div", { class: "menu", hidden: true });
  wrap.append(button, menu);
  // the menu leaves the way it came (.menu.leaving); closed twice it leaves once, and it opens again once it has gone
  const shown = () => !menu.hidden && !menu.classList.contains("leaving");
  const close = () => {
    if (!shown()) return;
    button.setAttribute("aria-expanded", "false");
    leave(menu).then(() => { menu.hidden = true; menu.classList.remove("leaving"); });
  };
  button.addEventListener("click", () => {
    if (shown()) return close();
    if (!menu.hidden) return; // still leaving
    menu.hidden = false;
    button.setAttribute("aria-expanded", "true");
  });
  document.addEventListener("click", (e) => !wrap.contains(e.target) && close());
  document.addEventListener("keydown", (e) => e.key === "Escape" && shown() && (close(), button.focus()));

  function paint() {
    const status = store.get().status;
    if (!status) {
      button.replaceChildren(h("span", { class: "status-dot" }), h("span", { class: "label-text" }, "Connecting…"));
      return;
    }
    const b = status.backend;
    const tone = !b.health?.ok ? "red" : b.locked ? "amber" : "green";
    const where = !b.locked && b.kind === "pod" && b.target?.host ? `${b.label} · ${b.target.host}` : b.label;
    button.replaceChildren(h("span", { class: "status-dot", "data-tone": tone }), h("span", { class: "label-text" }, b.locked ? "Recorded takes" : where), icon("chevron-down", "sm"));
    const rows = [
      h("div", null, h("b", null, b.locked ? "Recorded takes" : where), h("p", { class: "hint" }, b.locked
        ? "Playing recorded takes. Connect a GPU to shoot new ones."
        : b.health?.ok ? "Connected. New takes render on this backend." : `Not reachable: ${b.health?.detail ?? "unknown"}.`)),
    ];
    if (b.health?.detail && b.health.ok && !b.locked) rows.push(h("p", { class: "hint" }, b.health.detail));
    const configured = b.configured ?? b.sdk_configured;
    if (configured && b.locked) {
      const sw = h("button", { type: "button", class: "btn secondary" }, icon("cloud"), `Switch to ${b.target?.label ?? "the render backend"}`);
      sw.addEventListener("click", async () => { await controller.setBackend("sdk"); close(); });
      rows.push(sw);
    }
    const connect = h("button", { type: "button", class: "btn secondary connect-btn" }, icon("cloud"), configured ? "Connection…" : "Connect a backend…");
    connect.addEventListener("click", () => { close(); openConnectSheet(ctx); });
    rows.push(connect);
    if (!b.locked && b.kind !== "replay") {
      const sw = h("button", { type: "button", class: "btn secondary" }, icon("film"), "Switch to Replay");
      sw.addEventListener("click", async () => { await controller.setBackend("replay"); close(); });
      rows.push(sw);
    }
    const face = status.face_check;
    rows.push(h("p", { class: "hint" }, icon(face?.available ? "scan-face" : "circle-dashed", "sm"), face?.available ? " Face check ready." : " Face check off. Run `openfield doctor --fetch-models` to enable."));
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
  const openBtn = h("button", { type: "button", class: "btn secondary", "aria-label": "Open file", title: "Open a receipt, video or image to remix it." }, icon("folder-open"), h("span", { class: "btn-label" }, "Open file"));
  openBtn.addEventListener("click", () => open.click());
  open.addEventListener("change", () => { if (open.files[0]) remixFrom(ctx, open.files[0]); open.value = ""; });
  const dockToggle = h("button", { type: "button", class: "btn ghost icon-only", "aria-label": "Show settings", "aria-expanded": "true", title: "Show or hide the panel ( [ )" }, icon("panel-right"));
  const topbar = h("header", { class: "topbar" },
    h("div", { class: "brand" }, tapeMark(), h("span", { class: "wordmark" }, "OpenField Studio")),
    h("div", { class: "crumb" }, icon("chevron-right", "sm"), h("b", null, crumb)),
    h("span", { class: "grow" }),
    h("div", { class: "topbar-actions" }, openBtn, backendMenu(ctx), dockToggle, open));
  const rail = h("nav", { class: "rail", "aria-label": "Stations" }, STATIONS.map((s) => {
    // each room's sign is a rendered prop (art/btn-<room>.webp, made on our GPU); the word beside it is the name
    const a = h("a", { class: "rail-item", href: `#/${s.id}`, "data-route": s.id },
      s.art === false ? h("span", { class: "rail-art rail-sign", "aria-hidden": "true" }, icon(s.icon, "lg"))
        : h("img", { class: "rail-art", src: `art/btn-${s.id}.webp`, alt: "", width: 40, height: 40, decoding: "async", draggable: "false" }), h("span", null, s.label));
    return a;
  }));
  const mark = h("span", { class: "rail-mark", "aria-hidden": "true" }); // lies in the current room's item
  const stage = h("main", { class: "stage", id: "main", tabindex: "-1" });
  const ambient = createAmbient(stage); // the room's light, in the stage's grid cell under it
  const dockTabs = h("div", { class: "tabs", role: "tablist" });
  const tabSettings = h("button", { type: "button", role: "tab", id: "tab-settings", "aria-selected": "true" }, "Settings");
  const tabTake = h("button", { type: "button", role: "tab", id: "tab-take", "aria-selected": "false" }, "Take");
  dockTabs.append(tabSettings, tabTake);
  const dockBody = h("div", { class: "dock-body" });
  const dock = h("aside", { class: "dock", "aria-label": "Settings and take details" }, dockTabs, dockBody);
  const notices = h("div", { class: "notices", "aria-live": "polite" });
  const app = h("div", { class: "app", "data-dock": "open" }, topbar, rail, ambient.el, stage, dock);
  root.replaceChildren(h("a", { class: "skip", href: "#main" }, "Skip to the workspace"), app, notices);

  // -- stations (built once, shown one at a time) ----------------------------------------------------
  const monitorDirect = createMonitor({ ...ctx, scope: "direct", empty: () => directEmpty(ctx) });
  const monitorReshoot = createMonitor({ ...ctx, scope: "reshoot", empty: () => reshootEmpty(ctx) });
  const station = (id, ...kids) => h("div", { class: "station", "data-station": id, hidden: true }, ["lobby", "cast", "takes", "shots", "chat"].includes(id) ? null : h("h1", { class: "sr-only" }, STATIONS.find((s) => s.id === id).label), kids);
  const prompt = createPrompt(ctx);
  monitorDirect.lead(prompt.plan); // the plan line reads out over the wall; the shot card keeps the subject and the button
  const stations = {
    lobby: station("lobby", createLobby(ctx).el),
    direct: station("direct", prompt.el, monitorDirect.el, createFilmstrip({ ...ctx, scope: "direct" }).el),
    reshoot: station("reshoot", createReshootPrompt(ctx).el, monitorReshoot.el, createFilmstrip({ ...ctx, scope: "reshoot" }).el),
    cast: station("cast", createCastStation(ctx).el),
    shots: station("shots", createShotsStation(ctx).el),
    takes: station("takes", createTakes(ctx).el),
    chat: station("chat", createChatStation(ctx).el),
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
    const hasSettings = !["takes", "shots", "lobby", "chat"].includes(route);
    const tab = hasSettings ? dockTab : "take";
    app.dataset.dock = dockOpen ? "open" : "closed";
    app.dataset.cinema = String(Boolean(ui.get().cinema) && ["direct", "reshoot"].includes(route));
    dockToggle.setAttribute("aria-expanded", String(dockOpen));
    dockToggle.setAttribute("aria-label", dockOpen ? "Hide the panel" : "Show the panel");
    tabSettings.hidden = !hasSettings;
    tabTake.hidden = ["cast", "lobby", "chat"].includes(route);
    dockToggle.hidden = ["lobby", "chat"].includes(route); // rooms with no panel
    tabSettings.setAttribute("aria-selected", String(tab === "settings"));
    tabTake.setAttribute("aria-selected", String(tab === "take"));
    for (const [id, pane] of Object.entries(docks)) pane.hidden = !(tab === "settings" && id === route);
    details.el.hidden = tab !== "take";
    if (tab === "take") details.render();
  }
  // a room change in two parts: what is right at once (the rail, the crumb, the title, the dock and its tab, so a take link
  // still lands on its receipt tab), then the picture, which changeRoom crossfades
  function paintRoute() {
    const route = store.get().route;
    for (const a of rail.children) (a.dataset.route === route ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
    setText(crumb, STATIONS.find((s) => s.id === route).label);
    document.title = `${STATIONS.find((s) => s.id === route).label} · OpenField Studio`;
    ui.set({ dockTab: ["takes", "shots"].includes(route) ? "take" : "settings" }); // each station opens on its own panel
    paintDock();
  }
  /** The picture: the room's station at its top, the mark in its item, the prop clicking in. The route comes from the store, so
      a quicker change that skips this transition still shows the right room. Focus left in the room that went moves to the
      stage (not at boot: the skip link stays the first stop). */
  function showRoom({ focus = true } = {}) {
    const route = store.get().route;
    app.dataset.room = route; // the Lobby and Chat give the dock's column back (lobby.css); the Lobby keeps its own light
    stage.scrollTop = 0; // every room opens at its top (the rooms share one scrolling stage)
    for (const [id, node] of Object.entries(stations)) node.hidden = id !== route;
    placeMark();
    clickProp();
    const at = document.activeElement;
    if (focus && (!at || at === document.body || at.closest?.("[hidden]"))) stage.focus({ preventScroll: true });
  }
  ui.go = (route) => {
    if (!ROUTES.has(route)) return;
    if (location.hash !== `#/${route}`) history.pushState(null, "", `#/${route}`);
    store.set({ route });
  };
  ui.openDock = (tab) => { ui.set({ dockOpen: true, dockTab: tab }); };
  ui.showKeys = showKeys;
  /** A take link: select the take, show the station that plays it, and open its receipt. */
  ui.openTake = (id) => {
    const s = store.get();
    const take = s.takes.find((t) => t.id === id) ?? s.recorded.find((r) => r.id === id);
    if (!take) {
      notify(ctx, "That take is not in this copy.", "Showing your takes instead.", "info");
      store.set({ route: "takes" });
      return false;
    }
    // a bridge, an extension or an upscale plays on the Direct monitor beside its shots; a board opens on its own station
    const route = { reshoot: "reshoot", direct: "direct", transition: "direct", extend: "direct", upscale: "direct", shots: "shots" }[take.kind] ?? "takes";
    store.set({ route, selected: id });
    // the address bar carries the take, so it can be copied; replaceState leaves the history and the hash alone
    history.replaceState(null, "", `#/takes/${id}`);
    ui.set({ dockOpen: true, dockTab: "take" });
    return true;
  };
  /** Show a take on its wall without touching the dock: the Move Pad stays where the pointer is. */
  ui.selectTake = (id) => store.set({ selected: id });
  window.addEventListener("hashchange", async () => {
    const link = linkFromHash(location.hash);
    if (link) { history.replaceState(null, "", `#/${store.get().route}`); await remixFrom(ctx, link); return; }
    if (!location.hash.startsWith("#/")) return; // "#main" (the skip link) is a place on the page, not a room
    const { route, id } = parseHash(location.hash, ROUTES);
    if (id && route === "lobby") { store.set({ route }); ui.openMove?.(id); } // a move's own page
    else if (id) ui.openTake(id);
    else store.set({ route });
  });
  tabSettings.addEventListener("click", () => ui.set({ dockTab: "settings" }));
  tabTake.addEventListener("click", () => ui.set({ dockTab: "take" }));
  dockToggle.addEventListener("click", () => ui.set({ dockOpen: !ui.get().dockOpen }));
  document.addEventListener("keydown", (e) => {
    if (e.key === "[" && !e.target.closest?.("input,textarea,select,[contenteditable]")) ui.set({ dockOpen: !ui.get().dockOpen });
    if (e.key === "Escape" && compact() && ui.get().dockOpen && !e.defaultPrevented) ui.set({ dockOpen: false });
    const typing = e.target.closest?.("input,textarea,select,[contenteditable]");
    if (e.key === "?" && !typing && !document.querySelector(".sheet-scrim:not(.leaving)")) { e.preventDefault(); showKeys(); }
    // cinema: the take alone, full window; C again or Escape returns
    if ((e.key === "c" || e.key === "C") && !typing && !e.ctrlKey && !e.metaKey && !e.altKey && ["direct", "reshoot"].includes(store.get().route)) ui.set({ cinema: !ui.get().cinema });
    if (e.key === "Escape" && ui.get().cinema && !document.querySelector(".sheet-scrim:not(.leaving)")) ui.set({ cinema: false });
    // up and down walk the filmstrip: the previous or next take on the wall
    if ((e.key === "ArrowUp" || e.key === "ArrowDown") && !e.defaultPrevented && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const s = store.get();
      const kinds = { direct: ["direct", "transition", "extend", "upscale"], reshoot: ["reshoot"] }[s.route];
      const where = e.target;
      if (!kinds || (where !== document.body && !where.closest?.(".monitor, .filmstrip, .stage")) || where.closest?.("input,textarea,select,[role=radio],[role=slider],[contenteditable]")) return;
      if (where.closest?.("button, a") && !where.closest(".strip")) return; // a focused control keeps its keys; the filmstrip's own tiles walk
      const items = stripItems(s, kinds).slice(0, 30);
      const at = items.findIndex((t) => t.id === s.selected);
      const next = items[at < 0 ? 0 : at + (e.key === "ArrowDown" ? 1 : -1)];
      if (next) { e.preventDefault(); controller.select(next.id); }
    }
  });
  document.addEventListener("click", (e) => { // a floating dock closes when you click the workspace
    if (compact() && ui.get().dockOpen && !dock.contains(e.target) && !dockToggle.contains(e.target) && !e.target.closest(".notice")) ui.set({ dockOpen: false });
  });
  rail.addEventListener("click", (e) => {
    const a = e.target.closest("a");
    if (a) { e.preventDefault(); ui.go(a.dataset.route); stage.focus({ preventScroll: true }); }
  });
  ui.subscribe(paintDock);
  // a room change crossfades through a view transition that also carries the rail mark; the stage is named only while it runs
  // (.room-swap, layout.css). A quicker change skips the running one but still runs its callback, and the count keeps
  // .room-swap until the last has finished. Held still, or without View Transitions, the room cuts.
  const placeMark = () => rail.querySelector(`[data-route="${store.get().route}"]`)?.append(mark);
  // the arriving room's prop clicks into place; additive, so the stylesheet's hover transform is left alone
  const clickProp = () => {
    if (holdStill()) return;
    rail.querySelector('[aria-current="page"] .rail-art')?.animate([{ scale: "1.06" }, { scale: "0.97", offset: 0.6 }, { scale: "1" }], { duration: 180, easing: "cubic-bezier(0.16, 1, 0.3, 1)", composite: "add" });
  };
  let swaps = 0;
  const changeRoom = () => {
    paintRoute();
    play("room");
    if (!document.startViewTransition || holdStill()) return showRoom();
    const mine = ++swaps;
    const html = document.documentElement;
    html.classList.add("room-swap");
    // the stage is named for the capture of the old room only: once the new room is painted the name comes off, so the
    // new room is live and clickable at once while the old picture fades out over it (a named element is not hit-testable)
    const t = document.startViewTransition(() => { showRoom(); html.classList.remove("room-swap"); });
    t.ready.catch(() => {}); // a quicker change skips this one: ready rejects
    t.finished.catch(() => {}).then(() => { if (mine === swaps) html.classList.remove("room-swap"); });
  };
  store.subscribe((_, changed) => changed.includes("route") && changeRoom());

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
    if (!recording) return initialDirect(s.moves);
    const direct = { ...fromRecipe(recording.recipe, s.moves), heroMode: "prompt", castId: s.cast.find((c) => c.name === recording.recipe.cast_name)?.id ?? null };
    return s.status?.backend?.locked ? direct : { ...direct, line: "", language: "", action: "", quality: "standard" }; // Replay needs all of it to match
  };
  function seedForms() {
    const s = store.get();
    if (!s.moves || forms.get().direct) return;
    // the first view is never a blank form: in Replay the shot card carries the first recording (so Shoot
    // reads Recreate), with a backend it carries the latest finished Direct take, ready to shoot again
    const latest = s.takes.find((t) => t.kind === "direct" && t.status === "succeeded" && t.recipe?.subject);
    const hero = s.recorded.find((r) => r.id === s.status?.hero_take && r.kind === "direct");
    const seed = s.status?.backend?.locked ? hero ?? s.recorded.find((r) => r.kind === "direct") : latest ?? null;
    forms.set({ direct: directFrom(s, seed) });
  }
  // in Replay the form follows the recording you pick (or the one a replay came from), so Recreate names the take on screen
  function followSelection() {
    const s = store.get();
    if (!s.moves || !s.status?.backend?.locked) return;
    const chosen = s.takes.find((t) => t.id === s.selected);
    const recording = s.recorded.find((r) => r.id === (chosen?.replay_of ?? s.selected) && r.kind === "direct");
    if (recording) forms.set({ direct: directFrom(s, recording) });
  }
  // in Replay the footage follows the chosen move too: the wall shows the recorded take that made it, so the pad and
  // the wall never disagree. The exact recipe first (the sheet shares subject and seed), else the same move on the
  // same subject; a move nobody recorded leaves the wall alone (the plan line says so).
  function followMove() {
    const s = store.get();
    const direct = forms.get().direct;
    if (!s.loaded || !s.moves || !direct || !s.status?.backend?.locked) return;
    const subject = direct.subject.trim();
    const castName = s.cast.find((c) => c.id === direct.castId)?.name ?? null;
    const exact = s.recorded.find((r) => matchesRecording(direct, r, castName, s.moves));
    const chosen = s.takes.find((t) => t.id === s.selected);
    const shown = (chosen ?? s.recorded.find((r) => r.id === s.selected))?.recipe; // one already showing this move and subject stays
    if (!exact && shown?.rig?.movement === direct.rig.movement && (shown.subject ?? "").trim() === subject) return;
    const found = exact ?? sampleTake(s, direct.rig.movement, { subject });
    if (!found || (found.recipe?.subject ?? "").trim() !== subject) return;
    const id = found.replay_of ?? found.id;
    if (id === (chosen?.replay_of ?? s.selected)) return;
    ui.selectTake(id);
  }
  // the hosted copy and the demo open on the showcase's hero take, not merely the newest recording
  let heroShown = false;
  function showHero() {
    const s = store.get();
    const hero = s.status?.hero_take;
    if (heroShown || !s.loaded || !hero || !s.status?.backend?.locked) return;
    heroShown = true;
    const linked = parseHash(location.hash, ROUTES);
    if ((!linked.id || linked.route === "lobby") && !s.selected && s.recorded.some((r) => r.id === hero)) store.set({ selected: hero });
  }
  store.subscribe((_, changed) => {
    if (changed.some((k) => ["moves", "recorded", "status", "cast"].includes(k))) seedForms();
    if (changed.includes("selected")) followSelection();
    if (changed.some((k) => ["loaded", "status", "recorded"].includes(k))) showHero();
  });
  forms.subscribe((_, changed) => changed.includes("direct") && followMove());
  seedForms();
  paintRoute();
  showRoom({ focus: false });
  paintNotices();
  return { app, stage };
}
