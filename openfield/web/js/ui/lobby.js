// The Lobby: the first room. Every app hangs as a one-sheet whose key art our own GPU rendered (art/manifest.json
// keeps each picture's prompt, seed and model). A poster's proof is a recorded take: under the pointer the key art
// gives way to that take, playing, with its ticket stub. The marquee and the proof line say only what the data says.

import { h, icon } from "./dom.js";
import { claimSlot, freeSlot, liveClip, previewOf } from "./wall.js";
import { pinLive, unpinLive } from "./hoverplay.js";
import { fileOf, titleOf } from "../lib/stages.js";
import { billing, takeCount } from "../lib/billing.js";
import { marqueeCounts } from "../lib/deck.js";
import { createQuiz } from "./quiz.js";
import { openMakeSheet } from "./make.js";
import { createScreen } from "./screen.js";
import { createEffectShow, createMoveShow } from "./shows.js";
import { openMoveSheet } from "./movesheet.js";
import { rise } from "./reveal.js";
import { holdStill, onMotionChange } from "../lib/motion.js";

const ART = "art/";

const QWEN = "Qwen-Image 2.1";
const LTX = "LTX 2.5";
const WAN = "Wan Animate 2";
const rig = (t) => t.recipe?.rig ?? {};
const edit = (preset) => (t) => t.kind === "edit" && t.recipe?.preset === preset;
const move = (id) => (s) => Boolean(s.moves?.moves.find((m) => m.id === id)?.validated);
const presetTested = (id) => (s) => Boolean(s.moves?.edits?.presets.find((p) => p.id === id)?.tested);

/** The posters, in the order they hang: the words, the key art, the models, the take that proves it, its status.
    Titles are the app's own labels (the edit presets, the moves, the sheets), never another product's names. The
    models are the ones each kind's receipts name: an edit is one Qwen-Image 2.1 run. */
export const POSTERS = [
  { id: "direct", title: "Direct", tagline: "A camera you move around a virtual set.", models: [QWEN, LTX], go: "direct",
    proof: (t, s) => t.kind === "direct" && t.id === s.status?.hero_take, status: (s) => s.moves?.moves.some((m) => m.validated) },
  { id: "transitions", title: "Transition", tagline: "One take flies straight into the next.", models: [LTX],
    proof: (t) => t.kind === "transition" && t.recipe?.style === "push", status: (s) => Boolean(s.moves?.transitions?.styles.some((x) => x.tested)) },
  { id: "face-swap", title: "Swap the face", tagline: "A cast member's face on the take.", models: [QWEN], proof: edit("face_swap"), status: presetTested("face_swap") },
  { id: "relight", title: "Relight", tagline: "Move the light after the shoot.", models: [QWEN], proof: edit("relight"), status: presetTested("relight") },
  { id: "reshoot", title: "Re-shoot", tagline: "Your dance, a new dancer.", models: [WAN], go: "reshoot",
    proof: (t) => t.kind === "reshoot" && !t.recipe?.face_only, status: () => null },
  { id: "orbit", title: "Orbit", tagline: "The camera circles to the far side.", models: [QWEN, LTX],
    // the measured proof (the previews' choice) once it has loaded, else the newest plain orbit 180
    proof: (t, s) => (s.previews?.moves?.orbit_180 ? t.id === s.previews.moves.orbit_180
      : t.kind === "direct" && rig(t).movement === "orbit_180" && !rig(t).effect), status: move("orbit_180") },
  { id: "bts", title: "Behind the scenes", tagline: "Pull back to reveal the set.", models: [QWEN, LTX],
    proof: (t) => t.kind === "direct" && rig(t).effect === "bts", status: (s) => Boolean(s.moves?.effects?.find((e) => e.id === "bts")?.tested) },
  { id: "shots", title: "Shots", tagline: "One still, nine setups.", models: [QWEN], go: "shots",
    proof: (t) => t.kind === "shots", status: (s) => Boolean(s.moves?.shots?.tested) },
  { id: "dub", title: "Dub", tagline: "The same shot in another language.", models: [LTX],
    proof: (t) => t.kind === "direct" && Boolean(t.recipe?.language && t.recipe?.line), status: (s) => Boolean(s.moves?.dialogue?.dub_tested) },
  { id: "outfit", title: "Change the outfit", tagline: "New wardrobe, same person.", models: [QWEN], proof: edit("outfit"), status: presetTested("outfit") },
  { id: "person-swap", title: "Swap the person", tagline: "Someone else in the same scene.", models: [QWEN], proof: edit("character_swap"), status: presetTested("character_swap") },
  { id: "cast", title: "Cast", tagline: "Invent someone once. Keep the face in every shot.", models: [QWEN], go: "cast",
    proof: (t) => t.kind === "direct" && Boolean(t.recipe?.cast_name), status: () => null },
  { id: "extend", title: "Extend", tagline: "Keep the camera rolling.", models: [LTX], proof: (t) => t.kind === "extend", status: (s) => Boolean(s.moves?.extend?.tested) },
  { id: "loop", title: "Loop", tagline: "Ends exactly where it began.", models: [QWEN, LTX],
    proof: (t) => t.kind === "direct" && rig(t).movement === "loop", status: move("loop") },
  { id: "upscale", title: "Upscale", tagline: "Sharper, up to 4K.", models: ["Real-ESRGAN"], proof: (t) => t.kind === "upscale", status: (s) => Boolean(s.moves?.upscale?.tested) },
  { id: "remove", title: "Remove something", tagline: "Take out what does not belong.", models: [QWEN], proof: edit("remove"), status: presetTested("remove") },
  { id: "own-words", title: "Your words", tagline: "Say the change in your own words.", models: [QWEN], proof: edit("custom"), status: presetTested("custom") },
  { id: "reshoot-face", title: "Face only", tagline: "Your clip, performed by a cast member.", models: [QWEN, WAN],
    proof: (t) => t.kind === "reshoot" && Boolean(t.recipe?.face_only), status: (s) => Boolean(s.moves?.face_only_tested) },
  { id: "bullet-time", title: "Bullet time", tagline: "Freeze the moment, circle the camera.", models: [QWEN, LTX],
    proof: (t) => t.kind === "direct" && rig(t).movement === "bullet_time", status: move("bullet_time") },
];

/** The recorded take that proves a poster: the showcase reel's choice first (its curated order), else the newest. */
export function proofFor(poster, state) {
  const hits = (state.recorded ?? []).filter((t) => poster.proof(t, state));
  const reel = state.status?.hero_reel ?? [];
  const rank = (t) => { const i = reel.indexOf(t.id); return i < 0 ? Infinity : i; };
  return hits.sort((a, b) => rank(a) - rank(b) || (b.created_at ?? "").localeCompare(a.created_at ?? ""))[0] ?? null;
}

/** Whether a poster hangs: its feature's flag says a real render held. A poster with no flag (a room of its own, like
    Re-shoot or Cast) always hangs; one whose render has not held yet waits off the wall until it does. */
export function onWall(poster, state) {
  const flag = poster.status(state);
  return flag === null || Boolean(flag);
}
const day = (iso) => (iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }) : null);

/** The marquee's letters, hung one by one: letters for the eye; the marquee's own sentence is for every reader. The
    board hangs once a visit; a row whose count changes later (`hang`) is hung on its own. */
function marqueeRow(words, delay, hang = false) {
  const letters = [...words].map((c, i) => h("span", { class: c === " " ? "gap" : "letter", style: `--i:${delay + i}` }, c === " " ? "" : c));
  return h("p", { class: hang ? "marquee-row hanging" : "marquee-row", "aria-hidden": "true" }, h("span", { class: "letters" }, letters)); // the marquee's one sentence speaks for it
}

function ticketStub(take, state) {
  return h("span", { class: "ticket", "aria-hidden": "true" },
    h("span", { class: "ticket-admit" }, "Take"),
    h("span", { class: "ticket-id num" }, take.id.replace(/^tk_/, "")),
    h("span", { class: "ticket-grid" }, billing(take, state.moves).map(([label, value, pass]) =>
      h("span", null, h("i", null, label), h("b", { class: label === "Audit" ? null : "num" },
        label === "Audit" ? icon(pass ? "check" : "x", "sm") : null, value)))));
}

/** One poster in its case: the key art at rest; under the pointer or focus, its recorded take and ticket. The loop is
    looked up when the poster comes alive, so a preview list that arrives late never needs the wall rebuilt. */
function oneSheet(poster, state, api, store) {
  const take = proofFor(poster, state);
  const since = day(take?.created_at);
  // a station's own poster leads into that station; an app started from a take leads to the take that proves it
  const href = poster.go ? `#/${poster.go}` : take ? `#/takes/${take.id}` : "#/takes";
  const art = h("img", { class: "sheet-key", src: `${ART}poster-${poster.id}.webp`, alt: "", loading: "lazy", decoding: "async", draggable: "false",
    srcset: `${ART}poster-${poster.id}-360.webp 360w, ${ART}poster-${poster.id}.webp 720w`, sizes: "(max-width: 719px) 46vw, (max-width: 899px) 30vw, (max-width: 1179px) 23vw, 17vw" });
  // the ticket lives inside the art, which clips it: it waits below the art's bottom edge
  const sheet = h("a", { class: "one-sheet", href, "data-app": poster.id },
    h("span", { class: "sheet-art" }, art,
      take ? h("span", { class: "real-stamp", "aria-hidden": "true" }, "Recorded take") : null, take ? ticketStub(take, state) : null),
    h("span", { class: "sheet-type" },
      h("span", { class: "sheet-title" }, poster.title),
      h("span", { class: "sheet-tagline" }, poster.tagline),
      since ? h("span", { class: "billing" }, h("span", { class: "billing-run" }, `showing since ${since}`)) : null));
  if (take) {
    sheet.title = `${poster.title}: ${titleOf(take)}`;
    let video = null;
    const enter = (e) => {
      sheet.classList.add("live");
      const clip = previewOf(store.get(), take, api, { width: sheet.clientWidth * 2.63 });
      const person = Boolean(e); // a pointer or focus; the rotating display calls enter() with nothing
      if (video && person) claimSlot(video, { pin: true }); // someone points at a poster the wall woke: it keeps playing
      if (!clip || video || holdStill()) return; // the stamp and the ticket only; the key art stays
      video = h("video", { class: "sheet-take", muted: true, loop: true, playsinline: true, poster: clip.poster, src: clip.video, "aria-hidden": "true", disablepictureinpicture: true, tabindex: "-1" });
      video.muted = true;
      sheet.querySelector(".sheet-art").append(video);
      sheet.classList.add("playing");
      claimSlot(video, { pin: person }); // a shared decoder: the oldest loop yields; one someone points at never does
      video.play().catch(() => {});
    };
    const leave = (force = false) => {
      if (!force && (sheet.matches(":hover") || sheet.contains(document.activeElement))) return;
      sheet.classList.remove("live", "playing");
      if (video) { // released, not just removed: a phone has few decoders
        freeSlot(video);
        video.pause();
        video.removeAttribute("src");
        video.load();
        video.remove();
      }
      video = null;
    };
    sheet.addEventListener("pointerenter", enter);
    sheet.addEventListener("focusin", enter);
    sheet.addEventListener("pointerleave", () => leave());
    sheet.addEventListener("focusout", () => setTimeout(() => leave(), 0));
    sheet.alive = { enter, leave }; // the lobby's rotating display wakes one poster at a time with these
  }
  return h("li", null, sheet);
}

const KINDS = { direct: "Direct", reshoot: "Re-shoot", transition: "Transition", shots: "Shots", edit: "Edit", extend: "Extend", upscale: "Upscale" };

/** A lobby card's short title: the move, the edit or the kind, and the cast member in it ("Dolly in · Tomas"). */
export function cardTitle(take, state) {
  const what = take.kind === "direct" ? state.moves?.moves.find((m) => m.id === take.recipe?.rig?.movement)?.label
    : take.kind === "edit" ? state.moves?.edits?.presets.find((p) => p.id === take.recipe?.preset)?.label : null;
  const who = take.recipe?.cast_name;
  return [what ?? KINDS[take.kind] ?? take.kind, who].filter(Boolean).join(" · ");
}

/** A take as a lobby card: its loop (or still) in a printed border, its title band and its card number. */
function lobbyCard(take, number, state, api) {
  const clip = previewOf(state, take, api, { width: 320 });
  const still = fileOf(take, "poster");
  const picture = clip ? liveClip(clip)
    : still ? h("img", { class: "live-clip", src: api.media(take, still), alt: "", loading: "lazy", draggable: "false" })
      : h("span", { class: "live-clip blank" });
  return h("li", null, h("a", { class: "lobby-card", href: `#/takes/${take.id}`, title: titleOf(take) },
    h("span", { class: "card-picture" }, picture),
    h("span", { class: "card-band" },
      h("span", { class: "card-title" }, cardTitle(take, state)),
      h("span", { class: "card-no num" }, `No. ${number}`))));
}

/** The lobby is alive: like a lobby's rotating display, one poster on screen at a time comes alive on its own and
    plays its recorded take. The pointer always wins (a hovered poster pauses the display for a while), and nothing
    moves under reduced motion, in a hidden tab, or while the Lobby is not the room on screen. */
function rotatingDisplay(wall, room, { after = Promise.resolve() } = {}) {
  const awake = []; // the posters playing now, oldest first
  let last = null;
  let restUntil = 0;
  const many = () => (globalThis.matchMedia?.("(max-width: 719px)").matches ? 1 : 3); // a phone has few decoders
  const onScreen = (el) => { // in the rooms' own scroller, at least 40% in view: a first row peeking in counts
    const r = el.getBoundingClientRect();
    const v = room.closest(".stage")?.getBoundingClientRect() ?? { top: 0, bottom: innerHeight };
    const seen = Math.min(r.bottom, v.bottom) - Math.max(r.top, v.top);
    return r.width > 0 && seen >= r.height * 0.4;
  };
  const sleep = (el, force = false) => { el.alive.leave(force); awake.splice(awake.indexOf(el), 1); };
  const rest = (force = false) => { for (const el of [...awake]) sleep(el, force); };
  const tick = () => {
    if (holdStill() || document.hidden || room.closest("[hidden]")) { rest(true); return; }
    if (Date.now() < restUntil) return;
    if (wall.querySelector(".one-sheet:hover, .one-sheet:focus-within")) { rest(); return; }
    const sheets = [...wall.querySelectorAll(".one-sheet")].filter((el) => el.alive && onScreen(el));
    for (const el of [...awake]) if (!sheets.includes(el)) sleep(el, true); // scrolled away or rebuilt
    if (!sheets.length) return;
    const from = sheets.indexOf(last);
    const next = [...sheets.slice(from + 1), ...sheets.slice(0, from + 1)].find((el) => !awake.includes(el));
    if (!next) return;
    next.alive.enter();
    awake.push(next);
    last = next;
    while (awake.length > many()) sleep(awake[0], true); // the oldest hands over: the motion travels along the wall
  };
  // a person's pointer takes over: the display steps aside and waits before it starts again
  wall.addEventListener("pointerover", () => { rest(); restUntil = Date.now() + 9000; });
  wall.addEventListener("focusin", () => { rest(); restUntil = Date.now() + 9000; });
  after.then(() => { setTimeout(tick, 600); setInterval(tick, 3000); });
  return { stop: () => rest(true) };
}

/** A card under the hand plays its loop even while every decoder is busy: pinned, so no loop that wakes on its own can
    take the slot. When the hand leaves, the pin goes and the loop plays on as any other, one that may rest again. */
function playUnderHand(room) {
  const crossed = (e) => { // the card the pointer or focus just crossed into or out of, never a move inside it
    const card = e.pointerType === "touch" ? null : e.target.closest?.("a.lobby-card, a.show-card");
    return card && !card.contains(e.relatedTarget) ? card : null;
  };
  const wake = (e) => {
    const video = crossed(e)?.querySelector("video.live-clip");
    if (!video || holdStill()) return;
    pinLive(video); // a pinned slot, its address back if it rested, and play (ui/hoverplay.js)
  };
  const rest = (e) => {
    const card = crossed(e);
    const video = card?.querySelector("video.live-clip");
    if (!video || card.matches(":hover") || (e.type === "pointerout" && card === document.activeElement)) return;
    unpinLive(video); // the pin goes; still on screen, it counts again as an ordinary loop
  };
  room.addEventListener("pointerover", wake);
  room.addEventListener("focusin", (e) => { if (e.target.matches?.(":focus-visible")) wake(e); }); // a tap focuses too; only focus that shows plays
  room.addEventListener("pointerout", rest);
  room.addEventListener("focusout", rest);
}

const STEPS = [
  { art: "art-cast", title: "Cast", go: "cast", text: "Invent a character, or bring your own." },
  { art: "art-direct", title: "Direct", go: "direct", text: "Pick a camera move and watch it ride the set." },
  { art: "art-shots", title: "The stills", go: "direct", text: "Approve the stills, then shoot." },
  { art: "art-takes", title: "The take", go: "takes", text: "Every take keeps its receipt." },
];

/** The marquee's middle line changes count every few seconds, once the board has hung: the old letters drop and the new
    ones are hung (not in a room left meanwhile: it shows the new count as it stands). */
function marqueeCycle(rows, counts) {
  let at = 0;
  const swap = () => {
    if (counts.length < 2 || holdStill() || document.hidden || rows.closest("[hidden]") || !rows.closest(".entered")) return;
    const row = rows.children[1];
    if (!row) return;
    at = (at + 1) % counts.length;
    row.classList.add("dropping");
    setTimeout(() => row.isConnected && row.replaceWith(marqueeRow(counts[at], 0, !rows.closest("[hidden]"))), 460);
  };
  const timer = setInterval(swap, 5600);
  return () => clearInterval(timer);
}

/** The latest takes drift past like a film running through a gate; the pointer or focus holds them still. A second run
    of the same cards (hidden from readers and the keyboard) makes the loop seamless. Never under reduced motion. */
function drift(row) {
  row.classList.remove("drifting");
  row.querySelectorAll("[data-copy]").forEach((li) => li.remove());
  if (holdStill() || row.children.length < 4) return;
  for (const li of [...row.children]) {
    const copy = li.cloneNode(true);
    copy.dataset.copy = "";
    copy.setAttribute("aria-hidden", "true");
    copy.querySelectorAll("a, button").forEach((a) => a.setAttribute("tabindex", "-1"));
    copy.querySelectorAll("video.live-clip").forEach((v) => {
      const clip = liveClip({ video: v.dataset.src, poster: v.getAttribute("poster") ?? v.dataset.poster });
      v.replaceWith(clip);
    });
    row.append(copy);
  }
  row.style.setProperty("--drift", `${Math.max(40, row.children.length * 4.5)}s`);
  row.classList.add("drifting");
  // one loop is exactly the first run of cards and its gaps, so the second run lands where the first began
  requestAnimationFrame(() => {
    const first = row.firstElementChild;
    const copy = row.querySelector("[data-copy]");
    if (first && copy) row.style.setProperty("--loop", `${copy.offsetLeft - first.offsetLeft}px`);
  });
}

export function createLobby(ctx) {
  const { api, store, ui } = ctx;
  const screen = createScreen(ui, {
    billing: [h("span", { class: "billing-name" }, h("small", null, "starring "), `${QWEN} · ${LTX} · ${WAN}`)],
  });
  const marqueeText = h("span", { class: "sr-only" });
  const marqueeRows = h("div", { class: "marquee-rows" });
  const marquee = h("div", { class: "marquee" }, marqueeText, h("img", { class: "marquee-board", src: `${ART}marquee.webp`, alt: "", decoding: "async" }), marqueeRows,
    h("span", { class: "marquee-chase", "aria-hidden": "true" })); // the bulbs' chasing light (lobby.css)
  const takesLink = h("a", { class: "btn secondary lg", href: "#/takes" }, icon("film"), h("span", null, "Watch the takes"));
  const proof = h("p", { class: "lobby-proof num" });
  const wall = h("ul", { class: "poster-wall", "aria-labelledby": "now-showing" });
  const cards = h("ul", { class: "card-row", "aria-labelledby": "lobby-latest" });
  const openMove = (id, from = null) => openMoveSheet(ctx, id, { ids: moves.all(), from }); // from: the card's frame, when a card opened it
  const moves = createMoveShow(ctx, { onOpen: openMove });
  const effects = createEffectShow(ctx);
  const quiz = createQuiz(ctx);
  const quizShow = h("section", { class: "quiz-show", id: "name-the-move", "aria-labelledby": "lobby-quiz" },
    h("div", { class: "show-head" },
      h("h2", { id: "lobby-quiz", class: "lobby-h2" }, "Name the move"),
      h("p", { class: "show-lede" }, "Five clips a day. Name the camera move.")),
    quiz.el);
  let quizStarted = false;
  let quizNear = false; // the quiz has come near the view: it deals as soon as the loops are known
  // dealt once the loops are known; a person asking for it (force) gets it at once, or its "no loops here" note
  const startQuiz = (force = false) => { if (!quizStarted && (force || store.get().previews)) { quizStarted = true; quiz.start(); } };
  const toQuiz = () => {
    startQuiz(true);
    quizShow.scrollIntoView({ behavior: holdStill() ? "auto" : "smooth", block: "center" });
    setTimeout(() => quiz.el.querySelector("button:not([disabled])")?.focus({ preventScroll: true }), holdStill() ? 0 : 500);
  };
  // the front: the trailer across the room, then the pitch on the floor under it with the marquee beside it. lobby.css lays
  // the grid: on a wide screen the actions stand on the screen's foot at the right, clear of the trailer's own titles
  const el = h("div", { class: "lobby" },
    h("section", { class: "lobby-front" },
      screen.el,
      h("h1", { class: "lobby-headline" }, "Direct the shot. Keep the receipt."),
      h("p", { class: "lobby-lede" }, "Pick a camera move. Approve the stills. Shoot."),
      h("div", { class: "lobby-actions" }, h("a", { class: "btn primary lg", href: "#/direct" }, icon("clapperboard"), h("span", null, "Start directing")), takesLink),
      h("div", { class: "lobby-links" }, // the two quiet links keep a row of their own, at every width
        h("button", { type: "button", class: "btn ghost lg lobby-quiz", onclick: toQuiz }, icon("dices"), h("span", null, "Name the move")),
        h("button", { type: "button", class: "btn ghost lg lobby-make", onclick: () => openMakeSheet(ctx) }, icon("package"), h("span", null, "Make your own"))),
      marquee,
      proof,
      h("span", { class: "front-light", "aria-hidden": "true" }, h("span", { class: "lobby-dust" }))), // the beam and the dust on the floor (lobby.css)
    h("section", { class: "showing" }, h("h2", { id: "now-showing", class: "lobby-h2" }, "Now showing"), wall),
    moves.el,
    effects.el,
    quizShow,
    h("section", { class: "programme" }, h("h2", { class: "lobby-h2" }, "How a take is made"),
      h("ol", { class: "programme-cards" }, STEPS.map((s, i) => h("li", null, h("a", { class: "programme-card", href: `#/${s.go}` },
        h("img", { src: `${ART}${s.art}.webp`, alt: "", loading: "lazy", decoding: "async",
          srcset: `${ART}${s.art}-480.webp 480w, ${ART}${s.art}.webp 960w`, sizes: "(max-width: 719px) 92vw, 300px" }),
        h("span", { class: "programme-band" }, h("span", { class: "card-no num" }, `No. ${i + 1}`), h("span", { class: "programme-title" }, s.title)),
        h("span", { class: "programme-text" }, s.text)))))),
    h("section", { class: "latest" }, h("h2", { id: "lobby-latest", class: "lobby-h2" }, "Latest takes"), h("div", { class: "card-gate" }, cards)),
    h("footer", { class: "lobby-credits" },
      h("p", null, "Open weights · MIT licence · Built with Qwen · ", h("a", { href: `${ART}manifest.json` }, "The pictures' receipt"))));

  let wallKey = "";
  let cardsKey = "";
  let stopCycle = () => {};
  const cardTakes = new Map(); // card element -> the take it shows
  /** A late preview list: each card keeps its place and swaps its poster for the loop it can now play. */
  function upgradeCards(s) {
    for (const [card, take] of cardTakes) {
      const fallback = card.querySelector(".card-picture > .live-clip");
      if (!fallback || fallback.tagName === "VIDEO") continue; // already a loop
      const clip = previewOf(s, take, api, { width: 320 });
      if (clip) fallback.replaceWith(liveClip(clip));
    }
  }
  function paint() {
    const s = store.get();
    if (!s.loaded || !s.moves) return;
    const recorded = s.recorded ?? [];
    const reel = s.status?.hero_reel ?? [];
    // the wall is rebuilt only when what it shows changes (a hovered poster survives a late preview list); the cards
    // below are built once and upgraded in place when the previews arrive, so they can play their loops on screen
    const nextCards = `${recorded.length}|${reel.length}|${Boolean(s.previews)}`;
    if (nextCards !== cardsKey) {
      cardsKey = nextCards;
      const latest = reel.map((id) => recorded.find((t) => t.id === id)).filter(Boolean).slice(0, 8);
      const shown = latest.length ? latest : recorded.slice(0, 8);
      cardTakes.clear();
      cards.replaceChildren(...shown.map((t, i) => { const card = lobbyCard(t, i + 1, s, api); cardTakes.set(card, t); return card; }));
      if (s.previews) upgradeCards(s);
      drift(cards);
    } else if (s.previews) upgradeCards(s);
    if (s.previews) {
      moves.paint(s);
      effects.paint(s);
      if (quizNear) startQuiz();
    }
    const next = `${takeCount(s)}|${s.takes.length}|${s.status?.backend?.locked}|${s.moves.moves.filter((m) => m.validated).length}`;
    if (next === wallKey) return;
    wallKey = next;
    const count = takeCount(s); // each take once: the hosted copy lists its takes as recorded and as its own
    // the marquee counts what the room can play: the moves and effects whose render held, the takes on file
    const counts = marqueeCounts({ moves: s.moves.moves.filter((m) => m.validated).length,
      effects: (s.moves.effects ?? []).filter((e) => e.id !== "none" && e.tested).length, takes: count });
    // the letters are hung once: a later paint with the same counts (more data arriving) leaves the board alone
    const sentence = `NOW SHOWING: ${counts.join(", ")}. OPEN WEIGHTS ONLY.`;
    if (sentence !== marqueeText.textContent) {
      marqueeText.textContent = sentence;
      const hung = el.classList.contains("entered"); // after the visit's first hang, only the count that changed is hung
      marqueeRows.replaceChildren(marqueeRow("NOW SHOWING", 0), marqueeRow(counts[0] ?? "", hung ? 0 : 11, hung), marqueeRow("OPEN WEIGHTS ONLY", 40));
      stopCycle();
      stopCycle = marqueeCycle(marqueeRows, counts);
    }
    takesLink.querySelector("span").textContent = count ? `Watch the ${count} takes` : "Watch the takes";
    proof.textContent = count ? `${count} recorded takes` : "";
    for (const sheet of el.querySelectorAll(".one-sheet")) sheet.alive?.leave(true); // nothing keeps playing detached
    wall.replaceChildren(...POSTERS.filter((p) => onWall(p, s)).map((p) => oneSheet(p, s, api, store)));
  }
  store.subscribe((_, changed) => changed.some((k) => ["loaded", "moves", "recorded", "takes", "previews", "status"].includes(k)) && paint());
  paint();
  const display = rotatingDisplay(wall, el, { after: screen.ready });
  playUnderHand(el);
  // what comes into view rises (reveal.js): the wall, the galleries, the quiz and the programme item by item, in the order
  // they come into view, and each sign on its own
  for (const list of el.querySelectorAll(".poster-wall, .move-grid, .effect-rail, .quiz, .programme-cards")) rise(list);
  for (const head of el.querySelectorAll(".lobby-h2")) rise(head, { self: true });
  // the pitch's entrance and the board's first hang play once a visit: the board's last letter landing ends them, so a
  // return to the room plays neither again; a count that changes later hangs its own row (.hanging) and nothing else
  marquee.addEventListener("animationend", (e) => {
    const row = e.target.closest(".marquee-row");
    const letters = row?.querySelectorAll(".letter") ?? [];
    if (e.animationName !== "marquee-hang" || e.target !== letters[letters.length - 1]) return;
    row.classList.remove("hanging");
    if (row === marqueeRows.lastElementChild) el.classList.add("entered");
  });
  // while motion is held nothing plays: the front stands as it is, and stays so if motion is allowed again
  const still = () => holdStill() && el.classList.add("entered");
  still();
  onMotionChange(still);
  // the quiz deals its first round when it first comes into view, so its loop never loads with the page
  if (globalThis.IntersectionObserver) {
    const watch = new IntersectionObserver((entries) => { if (entries.some((e) => e.isIntersecting)) { quizNear = true; startQuiz(); watch.disconnect(); } }, { rootMargin: "200px 0px" });
    watch.observe(quizShow);
  } else startQuiz();
  // a move's own page: the gallery opens it, and so does an address like #/lobby/dolly_in
  ui.openMove = (id) => {
    const s = store.get();
    if (!s.moves) return false; // an unknown id still opens the sheet, which says so and goes back to the Lobby
    if (s.route !== "lobby") ui.go("lobby");
    openMove(id);
    return true;
  };
  // leaving the Lobby stops whatever it was playing at once, and ends the visit's entrance: back in the room, the front
  // and the marquee stand as they were left (a hidden room restarts every CSS animation it shows again)
  let here = store.get().route === "lobby";
  store.subscribe((state, changed) => {
    if (!changed.includes("route")) return;
    const left = here;
    here = state.route === "lobby";
    if (here) { screen.wake(); return; } // entered again: the trailer's sound returns when the studio's choice is on
    display.stop();
    screen.stop(); // the trailer is silent in another room; the studio's choice stands
    quiz.stop();
    for (const sheet of el.querySelectorAll(".one-sheet.live")) sheet.alive?.leave(true);
    if (!left) return;
    el.classList.add("entered");
    for (const row of marqueeRows.querySelectorAll(".hanging")) row.classList.remove("hanging");
  });
  // a link inside the lobby walks the app's own routes, so the address bar and the rail stay in step
  el.addEventListener("click", (e) => {
    if (e.defaultPrevented) return; // a gallery card handled its own click
    const a = e.target.closest("a[href^='#/']");
    if (!a || e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
    const [, route, id] = /^#\/([a-z]+)(?:\/(.+))?$/.exec(a.getAttribute("href")) ?? [];
    if (!route) return;
    e.preventDefault();
    if (id && route === "lobby") ui.openMove(id);
    else if (id) {
      history.pushState(null, "", a.getAttribute("href")); // Back returns to the Lobby; a reload reopens the take
      ui.openTake(id);
    } else ui.go(route);
    if (route !== "lobby") document.getElementById("main")?.focus({ preventScroll: true }); // the link itself is now in a hidden room
  });
  return { el };
}
