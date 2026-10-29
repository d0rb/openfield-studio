// What a first visitor meets: one card that says what this is and offers the tour, and the tour itself, which walks the
// rooms in this same window rather than sending anyone to a video.
//
// The card's second choice depends on where the app is running. On a machine it opens the real Connect sheet, where a
// Comfy Cloud key or a GPU box turns rendering on. On the hosted Replay it cannot: the page is a folder of static files
// with no studio behind it, and cloud.comfy.org sends no Access-Control-Allow-Origin, so a key pasted into the page
// would be both useless and public. There it shows the three commands that put the studio on your own machine instead.

import { h, icon, copyText } from "./dom.js";
import { openSheet } from "./sheet.js";
import { openConnectSheet } from "./connect.js";
import { notify } from "./actions.js";

const SEEN = "openfield.welcomed";
const RUN_IT = "pip install -e . && openfield demo";
const CLONE = "git clone https://github.com/d0rb/openfield-studio && cd openfield-studio";

/** Each step names a room and what to point at. The first selector that is on the page wins; if none is, the step still
 *  runs and its card simply stands on its own, so a room that changes shape can never strand the tour. */
const STOPS = [
  {
    route: "lobby", at: [".lobby-screen .screen-frame", ".lobby-screen"],
    title: "Nothing here was filmed",
    text: "Every frame in this studio came out of an open-weights model. The trailer on this screen is cut from takes that ship with the repo — click any second of it to open the take it came from.",
  },
  {
    route: "lobby", at: [".moves-show", ".poster-wall"],
    title: "The camera is the instrument",
    text: "Forty-four camera moves, each one a real shot you can play. A move is a recipe, not a prompt trick: pick one and the studio writes the shot for it.",
  },
  {
    route: "cast", at: [".cast-grid", ".cast-take"],
    title: "Cast holds the people",
    text: "A face you bring once can be directed again and again. The studio keeps the likeness steady across takes so a cut holds together.",
  },
  {
    route: "direct", at: [".prompt-fields", ".prompt"],
    title: "Direct is where you shoot",
    text: "Say who is in the shot and what happens, choose a move and a lens, and shoot. With a backend connected this renders; on the Replay it opens what the same words already made.",
  },
  {
    route: "takes", at: [".takes-ledger", ".take-row"],
    title: "Every take keeps its receipt",
    text: "The ledger counts what the work actually cost in GPU time. Open a take and its receipt names the models, the seed and the hash of the file it produced — enough to check the claim rather than trust it.",
  },
  {
    route: "chat", at: [".callsheet", ".chat-log"],
    title: "Or just ask",
    text: "The same studio takes direction in words, here or from any MCP client. The clip on this page was shot by the room itself.",
  },
];

function stepCard(stop, index, total, { onBack, onNext, onClose }) {
  const back = h("button", { type: "button", class: "btn ghost sm" }, "Back");
  const next = h("button", { type: "button", class: "btn primary sm" }, index === total - 1 ? "Done" : "Next");
  const skip = h("button", { type: "button", class: "btn ghost sm icon-only", "aria-label": "End the tour" }, icon("x", "sm"));
  back.disabled = index === 0;
  back.addEventListener("click", onBack);
  next.addEventListener("click", onNext);
  skip.addEventListener("click", onClose);
  return h("div", {
    class: "tour-card on-stock", role: "dialog", "aria-modal": "false",
    "aria-label": `${stop.title} — step ${index + 1} of ${total}`,
  },
  h("div", { class: "tour-card-head" }, h("span", { class: "tour-count" }, `${index + 1} / ${total}`), skip),
  h("h3", null, stop.title),
  h("p", null, stop.text),
  h("div", { class: "tour-card-foot" }, back, next));
}

/** The tour: it moves the app from room to room and stands a card beside the thing it is talking about. */
export function startTour(ctx) {
  const { ui } = ctx;
  if (document.querySelector(".tour")) return null;
  const spot = h("div", { class: "tour-spot", "aria-hidden": "true" });
  const slot = h("div", { class: "tour-slot" });
  const layer = h("div", { class: "tour" }, spot, slot);
  document.body.append(layer);
  document.documentElement.classList.add("touring");

  let at = 0;
  let timer = 0;

  const end = () => {
    window.clearTimeout(timer);
    window.removeEventListener("resize", place);
    window.removeEventListener("scroll", place, { capture: true });
    document.removeEventListener("keydown", onKey, true);
    document.documentElement.classList.remove("touring");
    layer.remove();
  };
  const onKey = (e) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); end(); return; }
    if (e.key === "ArrowRight") { e.preventDefault(); go(at + 1); }
    if (e.key === "ArrowLeft") { e.preventDefault(); go(at - 1); }
  };

  function target() {
    for (const sel of STOPS[at].at) {
      const el = document.querySelector(sel);
      if (el && el.getBoundingClientRect().width > 0) return el;
    }
    return null;
  }
  /** Put the halo on the thing and the card where it does not cover it: beside it with room, under it otherwise. */
  function place() {
    const el = target();
    if (!el) { spot.hidden = true; slot.dataset.free = "true"; slot.style.cssText = ""; return; }
    spot.hidden = false;
    const r = el.getBoundingClientRect();
    const pad = 8;
    Object.assign(spot.style, {
      left: `${Math.max(0, r.left - pad)}px`, top: `${Math.max(0, r.top - pad)}px`,
      width: `${r.width + pad * 2}px`, height: `${r.height + pad * 2}px`,
    });
    delete slot.dataset.free;
    const card = slot.firstElementChild;
    const cw = card ? card.getBoundingClientRect().width : 340;
    const ch = card ? card.getBoundingClientRect().height : 200;
    const gapRight = window.innerWidth - r.right;
    let left = gapRight > cw + 32 ? r.right + 16 : Math.max(16, r.left - cw - 16);
    if (left < 16 || left + cw > window.innerWidth - 16) left = Math.max(16, Math.min(window.innerWidth - cw - 16, r.left));
    let top = Math.max(16, Math.min(window.innerHeight - ch - 16, r.top));
    if (gapRight <= cw + 32 && r.left < cw + 32) top = r.bottom + 16 > window.innerHeight - ch - 16 ? Math.max(16, r.top - ch - 16) : r.bottom + 16;
    Object.assign(slot.style, { left: `${left}px`, top: `${top}px` });
  }

  function go(to) {
    if (to < 0) return;
    if (to >= STOPS.length) { end(); return; }
    at = to;
    const stop = STOPS[at];
    slot.replaceChildren(stepCard(stop, at, STOPS.length, { onBack: () => go(at - 1), onNext: () => go(at + 1), onClose: end }));
    if (ui?.go) ui.go(stop.route);
    // the room arrives behind a crossfade, so the halo waits for it rather than landing over the room that is leaving,
    // and what the stop points at is brought into view first: a target below the fold would otherwise be haloed
    // off-screen and the tour would read as a page that has merely gone dark.
    window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      target()?.scrollIntoView({ block: "center", inline: "nearest" });
      window.setTimeout(() => { place(); slot.querySelector(".btn.primary")?.focus(); }, 160);
    }, 380);
  }

  window.addEventListener("resize", place);
  window.addEventListener("scroll", place, { passive: true, capture: true });
  document.addEventListener("keydown", onKey, true);
  go(0);
  return { end };
}

function commands(ctx, lines) {
  return lines.map(([what, code]) => {
    const copy = h("button", { type: "button", class: "btn ghost sm", "aria-label": `Copy: ${what}` }, "Copy");
    copy.addEventListener("click", async () => notify(ctx, (await copyText(code)) ? "Copied." : "Could not copy.", "", "info"));
    return h("div", { class: "guide-step" }, h("b", null, what), h("div", { class: "guide-code" }, h("code", null, code), copy));
  });
}

/** The card a first visitor meets. It says what this is, offers the tour, and offers the one way to render that works
 *  from where the app is actually running. */
export function openWelcome(ctx) {
  const { store } = ctx;
  const locked = Boolean(store.get().status?.backend?.locked);
  const tour = h("button", { type: "button", class: "btn primary" }, icon("chevrons-right"), "Take the tour");
  const second = h("button", { type: "button", class: "btn secondary" }, icon("cloud"), locked ? "Render your own" : "Connect a backend");
  const look = h("button", { type: "button", class: "btn ghost" }, "Look around");

  const render = h("div", { class: "welcome-render", hidden: true },
    h("p", { class: "hint" }, "This page is a folder of static files — the takes and their receipts, with no studio behind it. Put the studio on your own machine and a Comfy Cloud key or a rented GPU box renders new takes from the app's header:"),
    ...commands(ctx, [["Get it", CLONE], ["Run it", RUN_IT]]),
    h("p", { class: "hint" }, "It opens on these same takes with no key and no GPU. The key goes in Connect, in the header, and is never written to disk."));

  const body = h("div", { class: "stack welcome" },
    h("p", { class: "welcome-lede" }, "A film studio on open weights. Every take here was rendered by one, and keeps the receipt that proves it."),
    h("div", { class: "welcome-actions" }, tour, second, look),
    render);

  const sheet = openSheet({ title: "Welcome to OpenField Studio", body, className: "sheet-welcome", focusSheet: true });
  try { window.localStorage?.setItem(SEEN, "1"); } catch { /* a browser that keeps nothing still gets the card */ }

  tour.addEventListener("click", () => { sheet?.close?.(); window.setTimeout(() => startTour(ctx), 220); });
  look.addEventListener("click", () => sheet?.close?.());
  second.addEventListener("click", () => {
    if (!locked) { sheet?.close?.(); openConnectSheet(ctx); return; }
    render.hidden = !render.hidden;
    second.textContent = "";
    second.append(icon("cloud"), render.hidden ? "Render your own" : "Hide");
  });
  return sheet;
}

/** Once per browser, and never over a link that was sent to someone: a shared take opens on that take. */
export function maybeWelcome(ctx) {
  let seen = false;
  try { seen = window.localStorage?.getItem(SEEN) === "1"; } catch { seen = false; }
  if (seen || location.hash.replace(/^#\/?/, "")) return false;
  openWelcome(ctx);
  return true;
}
