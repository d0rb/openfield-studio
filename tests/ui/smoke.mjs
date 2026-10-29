// Drives the real interface in a real browser. Usage:
//   node tests/ui/smoke.mjs live   http://127.0.0.1:PORT/   (the app on the offline fake of the Comfy API)
//   node tests/ui/smoke.mjs static http://127.0.0.1:PORT/   (the hosted Replay: plain files, no server)
// Exits 1 if any check fails. tests/test_ui_smoke.py starts the servers and calls this.
// OPENFIELD_LIVING=1 adds the round-14 checks (hover to play, the path chips, the decoder budget): living() below.

import { launch } from "../../scripts/ui/browser.mjs";

const [mode, url] = process.argv.slice(2);
if (!["live", "static"].includes(mode) || !url) {
  console.error("usage: node tests/ui/smoke.mjs <live|static> <url>");
  process.exit(2);
}

const LIVING = process.env.OPENFIELD_LIVING === "1";
let failures = 0;
const check = (name, ok, detail = "") => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
  if (!ok) failures += 1;
};

/** What a keyboard or screen-reader user needs: names, unique ids, targets big enough to hit. */
const AUDIT = `(() => {
  const problems = [];
  const shown = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && !el.closest("[hidden]"); };
  const labelled = (el) => (el.getAttribute("aria-labelledby") ?? "").split(" ").map((id) => document.getElementById(id)?.textContent ?? "").join(" ").trim();
  const name = (el) => el.getAttribute("aria-label") || labelled(el) || (el.labels?.length ? [...el.labels].map((l) => l.textContent).join(" ") : "") || el.getAttribute("title") || el.textContent.trim() || el.querySelector("img[alt]")?.alt || "";
  for (const el of document.querySelectorAll("button, a[href], input:not([type=hidden]), select, textarea, [role=radio], [role=switch], [role=tab]")) {
    if (el.type !== "file" && !shown(el)) continue;
    if (!name(el)) problems.push("no accessible name: " + el.outerHTML.slice(0, 80));
  }
  const ids = new Map();
  for (const el of document.querySelectorAll("[id]")) ids.set(el.id, (ids.get(el.id) ?? 0) + 1);
  for (const [id, n] of ids) if (n > 1) problems.push("duplicate id: " + id);
  for (const el of document.querySelectorAll("button, a[href], [role=radio], [role=switch], [role=tab], select")) {
    if (!shown(el) || el.closest(".chat-text")) continue; // a link inside a sentence is sized by its line (WCAG 2.5.8)
    const r = el.getBoundingClientRect();
    if (r.width < 24 || r.height < 24) problems.push("target under 24px: " + el.outerHTML.slice(0, 70) + " " + Math.round(r.width) + "x" + Math.round(r.height));
  }
  for (const img of document.querySelectorAll("img")) if (!img.hasAttribute("alt")) problems.push("image without alt");
  return problems;
})()`;

/** Run before the page's own scripts: what the Takes head looks like the moment the app is built, before the status has come. */
const FIRST_PAINT = `(() => {
  window.__first = null;
  const watch = new MutationObserver(() => {
    const head = document.querySelector("[data-station=takes] .station-head");
    if (!head) return;
    watch.disconnect();
    const line = head.querySelector(".takes-ledger");
    window.__first = { ledger: Boolean(line), hidden: line ? line.hidden : null, statusIn: Boolean(window.openfield?.store.get().status), route: window.openfield?.store.get().route ?? null };
  });
  watch.observe(document, { childList: true, subtree: true });
})()`;

/** The elements that carry the rail mark's view-transition name (shell.js): exactly one, and the page itself carries none. */
const MARKS = "[...document.querySelectorAll('*')].filter((e) => getComputedStyle(e).viewTransitionName === 'rail-mark')";
const MADE_HERE = "tk_20261025_135037_c07b"; // the take the hosted Chat card plays (ui/chat.js)

/** Round 14, the living cinema: a tile that shows a take plays it under the pointer or keyboard focus, in a pinned slot; a
    Direct take's wall tile draws its camera's path, lit as far as the footage has run; the wall keeps to its decoder budget
    while it scrolls, on a wide screen and a phone; Save-Data and reduced motion get none of it. It leaves the page at
    1440x900 with motion and Save-Data as it found them. */
async function living() {
  const boxOf = (selector, i = 0) => ev(`(() => { const e = document.querySelectorAll(${JSON.stringify(selector)})[${i}]; if (!e) return null; e.scrollIntoView({ block: "center" }); const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; })()`);
  const point = (box, across = 0.5) => b.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: box.x + box.w * across, y: box.y + box.h / 2 });
  const hover = async (selector) => { const box = await boxOf(selector); if (box) await point(box); return box; };
  const away = () => b.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 1, y: 1 });
  const plays = (selector) => `(() => { const v = document.querySelector(${JSON.stringify(selector)}); return Boolean(v && !v.paused && v.currentTime > 0 && v.muted); })()`;
  const byKey = (selector, i = 0) => ev(`(() => { const e = document.querySelectorAll(${JSON.stringify(selector)})[${i}]; e.scrollIntoView({ block: "center" }); e.focus({ focusVisible: true }); return true; })()`); // focus as Tab gives it
  const blur = () => ev("(() => { document.activeElement?.blur(); return true; })()");
  const fresh = async (room) => { await b.goto(`${url}#/${room}`); await b.waitFor("window.openfield?.store.get().loaded", { label: `the app loads on ${room}` }); await b.sleep(400); };
  const offset = () => ev("document.querySelector('.wall-tile .path-chip .g-lit')?.getAttribute('stroke-dashoffset') ?? null");
  /** Scroll the Takes room in steps; at each, the slots and every video playing anywhere in the page. */
  const scrolled = async () => {
    const seen = [];
    for (let step = 0; step < 6; step += 1) {
      await ev("(() => { document.querySelector('.stage').scrollBy(0, 360); return true; })()");
      await b.sleep(450);
      seen.push(await ev("({ ...window.openfield.slots(), unpaused: [...document.querySelectorAll('video')].filter((v) => !v.paused).length })"));
    }
    return seen;
  };

  await b.emulate([{ name: "prefers-reduced-motion", value: "no-preference" }]);
  await b.send("Emulation.setFocusEmulationEnabled", { enabled: true }); // a headless page has no focus until input comes: :focus-visible needs it
  await fresh("cast");
  if (await ev("Boolean(document.querySelector('.cast-take'))")) {
    await hover(".cast-take");
    const played = await within(plays(".cast-take video.hover-clip"), 8000);
    const held = await ev("window.openfield.slots()");
    check("living: a cast take thumb plays its take under the pointer, muted, in a pinned slot", played && held.pinned >= 1, JSON.stringify(held));
    await away();
    check("living: and lets it go when the pointer leaves", await within("!document.querySelector('.cast-take video')", 2000));
    await byKey(".cast-take");
    check("living: keyboard focus on the thumb plays it as the pointer does", await within(plays(".cast-take video.hover-clip"), 8000));
    await blur();
    check("living: and blur lets it go", await within("!document.querySelector('.cast-take video')", 2000));
  } else check("living: with no cast member in a take there is no thumb to hover", true);

  await route("direct");
  const frame = "[data-station=direct] .strip .tile[data-status=succeeded]";
  if (await ev(`Boolean(document.querySelector(${JSON.stringify(frame)}))`)) {
    await byKey(frame);
    check("living: keyboard focus on a filmstrip frame plays its take inside it", await within(plays(`${frame}:focus video.hover-clip`), 8000));
    await blur();
    check("living: and blur lets it go", await within(`!document.querySelector(${JSON.stringify(`${frame} video`)})`, 2000));
  }

  await route("takes");
  await within("document.querySelectorAll('.wall .wall-tile').length > 0", 8000);
  const tiles = ".wall-tile[data-kind=direct]";
  let found = -1;
  for (let i = 0; found < 0 && i < Math.min(10, await ev(`document.querySelectorAll(${JSON.stringify(tiles)}).length`)); i += 1) {
    await point(await boxOf(tiles, i));
    if (await within("Boolean(document.querySelector('.wall-tile .path-chip .g-lit'))", 600)) found = i; // a zoom or a still draws no track
  }
  if (found >= 0) {
    const box = await boxOf(tiles, found);
    // the mouse scrubs the loop and the lit track follows the hand, where the server lets a video seek (a plain file server may not)
    if (await ev(`(() => { const v = document.querySelectorAll(${JSON.stringify(tiles)})[${found}].querySelector("video"); return v.seekable.length > 0 && v.seekable.end(0) > 0; })()`)) {
      await point(box, 0.25);
      await b.sleep(400);
      const early = await offset();
      await point(box, 0.75);
      await b.sleep(400);
      const late = await offset();
      check("living: a Direct take's wall tile lights its camera's path as far as the mouse has run the take", early !== null && late !== null && early !== late, `${early} then ${late}`);
    }
    await away();
    check("living: and the chip comes down when the pointer leaves", await within("!document.querySelector('.path-chip')", 2000));
    await byKey(tiles, found);
    const first = (await within("Boolean(document.querySelector('.wall-tile .path-chip .g-lit'))", 2000)) && (await offset());
    await b.sleep(400);
    const then = await offset();
    check("living: with keyboard focus the playing loop drives it", Boolean(first) && first !== then, `${first} then ${then}`);
    await blur();
    await b.emulate([{ name: "prefers-reduced-motion", value: "reduce" }]);
    await point(await boxOf(tiles, found));
    await b.sleep(300);
    check("living: under reduced motion no chip follows the footage", await ev("!document.querySelector('.path-chip')"));
    await away();
    await b.emulate([{ name: "prefers-reduced-motion", value: "no-preference" }]);
  } else check("living: with no travelling Direct take on the wall there is no path to draw", true);

  await fresh("takes");
  await within("window.openfield.slots().playing >= Math.min(12, document.querySelectorAll('.wall video.live-clip').length)", 15000);
  const wide = await scrolled();
  check("living: while the wall scrolls at most twelve loops play, and nothing plays outside the count", wide.every((x) => x.cap === 12 && x.playing - x.pinned <= 12 && x.unpaused <= 12 + x.pinned), JSON.stringify(wide));
  await ev("(() => { document.querySelector('.stage').scrollTo(0, 0); return true; })()");
  if (await within("window.openfield.slots().playing === 12", 12000)) {
    await hover(".wall .wall-tile");
    await b.sleep(300);
    const under = await ev("window.openfield.slots()");
    check("living: a tile under the hand while twelve play takes the one pinned slot", under.pinned === 1 && under.playing <= 13, JSON.stringify(under));
    await away();
  }
  await b.viewport(390, 844, true, 2);
  await fresh("takes");
  await b.sleep(1200);
  const phone = await scrolled();
  check("living: on a phone at most four loops play while the wall scrolls", phone.every((x) => x.cap === 4 && x.playing - x.pinned <= 4 && x.unpaused <= 4 + x.pinned), JSON.stringify(phone));
  await b.viewport(1440, 900, false, 1);

  const saver = await b.send("Page.addScriptToEvaluateOnNewDocument", { source: "Object.defineProperty(navigator, 'connection', { value: { saveData: true }, configurable: true });" });
  try {
    const hovered = [];
    await fresh("cast");
    if (await hover(".cast-take")) hovered.push("a cast thumb");
    await b.sleep(400);
    await route("takes");
    if (await hover(".wall .wall-tile")) hovered.push("a wall tile");
    await b.sleep(400);
    await ev("(() => { [...document.querySelectorAll('.takes-tools [role=radio]')].find((x) => x.textContent.trim() === 'All')?.click(); return true; })()");
    await b.sleep(300);
    if (await hover(".take-row-main")) hovered.push("a Takes row");
    await b.sleep(400);
    await route("lobby");
    if (await hover(".show-card")) hovered.push("a show card");
    await b.sleep(400);
    const asked = await ev("[...performance.getEntriesByType('resource').filter((e) => /[.]mp4/.test(e.name)).map((e) => e.name), ...[...document.querySelectorAll('video[src]:not(.player, .player-out)')].map((v) => v.className + ' ' + v.getAttribute('src'))]");
    check("living: under Save-Data the pointer on a cast thumb, a wall tile, a Takes row and a show card loads no video", hovered.length > 0 && asked.length === 0, `${hovered.join(", ")}; ${asked.join(" | ").slice(0, 200)}`);
    await away();
  } finally {
    await b.send("Page.removeScriptToEvaluateOnNewDocument", { identifier: saver.identifier });
  }
  await b.emulate([{ name: "prefers-reduced-motion", value: "" }]);
  await b.send("Emulation.setFocusEmulationEnabled", { enabled: false });
}

const b = await launch({ width: 1440, height: 900 });
const ev = (js) => b.eval(js);
const route = async (name) => { await ev(`location.hash = "#/${name}"`); await b.waitFor(`window.openfield.store.get().route === "${name}"`); await b.sleep(250); };
/** Whether `expression` comes true within `timeout` ms: a regression then fails its own check instead of stopping the run. */
const within = async (expression, timeout = 3000) => { try { return await b.waitFor(expression, { timeout }); } catch { return false; } };

try {
  // -- with motion allowed: the Lobby arms its lists to rise, and the rail's mark slides to the room you go to ---------------------
  // (a reload of its own: the page arms its lists as it is built, and this helper's browser holds motion still unless told otherwise)
  await b.emulate([{ name: "prefers-reduced-motion", value: "no-preference" }]);
  await b.goto(url);
  await b.waitFor("window.openfield?.store.get().loaded", { label: "the app loads with motion allowed" });
  check("with motion allowed the Lobby arms its wall to rise as it comes into view", await ev("!document.documentElement.classList.contains('hold-still') && Boolean(document.querySelector('.poster-wall.armed'))"));
  check("one element carries the rail mark's transition name, and the page itself carries none", await ev(`${MARKS}.length === 1 && getComputedStyle(document.documentElement).viewTransitionName === 'none'`), await ev(`${MARKS}.length + " marks, page: " + getComputedStyle(document.documentElement).viewTransitionName`));
  await ev("location.hash = '#/takes'");
  const slid = await within("document.querySelector('.rail-item[data-route=takes] .rail-mark')", 4000);
  check("going to the Takes room carries the rail mark into the Takes item, and it stays one mark", slid && (await ev(`${MARKS}.length === 1`)));
  // the room's light: on the Takes room, under the mouse; the Lobby keeps its own
  await within("!document.documentElement.classList.contains('room-swap')", 1000);
  check("the room's light shows on the Takes room", await ev("getComputedStyle(document.querySelector('.ambient')).display === 'block'"));
  const centre = await ev("(() => { const r = document.querySelector('.stage').getBoundingClientRect(); return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) }; })()");
  await b.send("Input.dispatchMouseEvent", { type: "mouseMoved", ...centre });
  // The light follows a mouse only where the app says it may: ui/ambient.js asks for (hover: hover) and a wide
  // screen, and a headless browser can report no hovering pointer at all. Where it reports one the light must
  // arrive; where it does not, the app is right to leave it alone, and the message says which case this was. The
  // glide is 0.18 of the way each frame, so the time it takes is a frame rate, not a behaviour: it gets room.
  const hovers = await ev(`matchMedia("(hover: hover) and (min-width: 900px)").matches`);
  const lit = hovers && await within(`(() => { const r = document.querySelector('.house-light').getBoundingClientRect(); return Math.hypot(r.x + r.width / 2 - ${centre.x}, r.y + r.height / 2 - ${centre.y}) <= 40; })()`, 4000);
  check("the house light comes up under the mouse, where the browser hovers", hovers ? lit : true,
    hovers ? "hovers" : "no hovering pointer here, so the light rightly stays put");
  await b.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 2, y: 2 }); // off the stage again
  // the room crossfade: named only while it runs, and the arriving room's prop clicks in
  // Both are read in the one step that starts the change, not polled after it: the prop's animation runs for --t-base
  // (180 ms), so a poll that loses a race with a loaded runner finds it already over and reports that it never ran.
  const swapped = await ev("(() => { window.openfield.ui.go('lobby'); return { swap: document.documentElement.classList.contains('room-swap'), prop: document.querySelector('.rail-item[aria-current=page] .rail-art').getAnimations().length }; })()");
  check("a room change crossfades: room-swap is on the page at once", swapped.swap);
  check("and the arriving room's prop animates", swapped.prop >= 1, JSON.stringify(swapped));
  // the crossfade is 320 ms; the ceiling is only here to catch one that sticks, so it is loose enough for a slow runner
  check("and room-swap clears when the crossfade ends", await within("!document.documentElement.classList.contains('room-swap')", 3000));
  check("the Lobby shows none of the room's light", await ev("getComputedStyle(document.querySelector('.ambient')).display === 'none'"));
  // the backend menu leaves the way it came
  await b.click(".backend-btn");
  check("the backend menu leaves: .leaving at once", await ev("(() => { document.body.click(); return document.querySelector('.menu').classList.contains('leaving'); })()"));
  check("and is hidden once it has left", await within("document.querySelector('.menu').hidden && !document.querySelector('.menu').classList.contains('leaving')", 3000));
  await b.emulate([{ name: "prefers-reduced-motion", value: "" }]);

  // -- the Takes head: the ledger line has its place from the first paint, and the head keeps its height when the ledger comes -----
  const painted = await b.send("Page.addScriptToEvaluateOnNewDocument", { source: FIRST_PAINT });
  await b.goto(`${url}#/takes`);
  await b.waitFor("window.openfield?.store.get().loaded", { label: "the app loads on the Takes room" });
  const first = await ev("window.__first");
  check("the Takes head holds the ledger line's place from the first paint, before the status has come", Boolean(first?.ledger) && first.statusIn === false && first.hidden === false && first.route === "takes", JSON.stringify(first));
  const ledger = JSON.parse(await ev(`(() => {
    const { store } = window.openfield;
    const head = document.querySelector("[data-station=takes] .station-head");
    const line = head.querySelector(".takes-ledger");
    const had = store.get().status?.gpu ?? null;
    const out = { text: line.textContent, takes: store.get().takes.length + store.get().recorded.length };
    store.set((s) => ({ status: { ...s.status, gpu: null } }));
    out.before = head.getBoundingClientRect().height;
    store.set((s) => ({ status: { ...s.status, gpu: { seconds: 19440, takes: 134 } } }));
    out.after = head.getBoundingClientRect().height;
    out.filled = line.textContent;
    store.set((s) => ({ status: { ...s.status, gpu: had } }));
    return JSON.stringify(out);
  })()`));
  check("the ledger line reads as a sentence about the recorded takes, or stays empty", ledger.text === "" || ledger.text.startsWith("the recorded takes took"), ledger.text);
  // at this width the line shares the heading's row, so its height cannot tell; on a phone it has a row of its own, and the
  // stylesheet must reserve that row (min-height 1lh) from the first paint so the head never grows when the ledger fills in
  const reserved = await ev(`(() => { for (const sheet of document.styleSheets) { let rules; try { rules = sheet.cssRules; } catch { continue; } for (const r of rules) { if (!r.media || !/max-width:\\s*719px/.test(r.conditionText ?? r.media.mediaText)) continue; for (const q of r.cssRules) if (q.selectorText === ".takes-ledger" && q.style.minHeight === "1lh" && q.style.flexBasis === "100%") return true; } } return false; })()`);
  if (ledger.takes > 0) check("on a phone the ledger line holds a row of its own from the first paint, and fills in as a sentence", reserved && ledger.filled.startsWith("the recorded takes took"), JSON.stringify({ reserved, filled: ledger.filled }));
  else check("with no takes on the list there is no ledger line to print", ledger.filled === "", JSON.stringify(ledger)); // the ledger sums the takes the list shows
  await b.send("Page.removeScriptToEvaluateOnNewDocument", { identifier: painted.identifier });

  await b.goto(url);
  await b.waitFor("window.openfield?.store.get().loaded", { label: "the app loads" });
  await b.sleep(400);

  // -- the shell ----------------------------------------------------------------------------------
  check("the page has a title", /OpenField Studio/.test(await ev("document.title")));
  check("seven rooms in the rail, the Lobby first and the Chat room last", (await ev("[...document.querySelectorAll('.rail-item')].map((a) => a.dataset.route).join()")) === "lobby,cast,direct,shots,reshoot,takes,chat");
  check("it runs on the " + mode + " api", (await ev("window.openfield.api.kind")) === (mode === "static" ? "static" : "http"));

  // -- the Lobby: the first room ---------------------------------------------------------------------------------
  check("the first room is the Lobby", (await ev("window.openfield.store.get().route")) === "lobby" && !(await ev("document.querySelector('[data-station=lobby]').hidden")));
  check("the marquee counts the moves that play and says nothing about testing", await ev("(() => { const t = document.querySelector('.marquee').innerText; const n = window.openfield.store.get().moves.moves.filter((m) => m.validated).length; return t.includes(n + ' CAMERA MOVES') && !/TESTED/.test(t); })()"), await ev("document.querySelector('.marquee').innerText"));
  check("the wall hangs the apps as one-sheets", (await ev("document.querySelectorAll('.poster-wall .one-sheet').length")) >= 18);
  check("no interface text talks about testing", !/not yet tested|untested/i.test(await ev("document.querySelector('.app').textContent")));
  check("a poster whose render has not held waits off the wall (bullet time follows its flag)", (await ev("Boolean(document.querySelector('.one-sheet[data-app=bullet-time]')) === Boolean(window.openfield.store.get().moves.moves.find((m) => m.id === 'bullet_time').validated)")));
  // the lobby moves on its own: the trailer of recorded takes, and posters waking on the wall, with no pointer at all
  await b.emulate([{ name: "prefers-reduced-motion", value: "no-preference" }]);
  await b.waitFor("(() => { const v = document.querySelector('.lobby-screen video.trailer'); return v && !v.paused && v.currentTime > 0.3 && v.muted; })()", { timeout: 15000, label: "the trailer plays" });
  check("the screen plays the trailer of recorded takes, muted", true);
  check("the reel under the screen lists the trailer's segments", (await ev("document.querySelectorAll('.screen-reel .reel-cut').length")) >= 4);
  await b.waitFor("!document.querySelector('.trailer-chip').hidden", { timeout: 8000, label: "the trailer names its take" });
  check("and names the take on screen", await ev("fetch('art/trailer.json').then((r) => r.json()).then((d) => d.segments.some((s) => s.label === document.querySelector('.trailer-chip').textContent.trim()))"), await ev("document.querySelector('.trailer-chip').textContent"));
  if (await ev("document.querySelectorAll('.poster-wall .one-sheet .real-stamp').length > 0")) { // a poster with a recorded take to play
    await ev("document.querySelector('.poster-wall').scrollIntoView({ block: 'start' })"); // the wall hangs under the screen: the display wakes only posters in view
    await b.waitFor("document.querySelectorAll('.poster-wall .one-sheet.live').length >= 1", { timeout: 9000, label: "a poster wakes on its own" });
    check("posters wake on the wall with no pointer on them", (await ev("document.querySelectorAll('.poster-wall .one-sheet.live').length")) <= 3);
    await ev("document.querySelector('.stage').scrollTo(0, 0)");
  }
  // -- one sound switch for the studio: the Lobby's pill, remembered, with the trailer silent outside its room ----------
  check("a fresh browser has the switch off", (await ev("localStorage.getItem('openfield.sound')")) === null && (await ev("document.querySelector('.trailer-sound').getAttribute('aria-pressed')")) === "false");
  await b.click(".trailer-sound");
  await b.sleep(200);
  check("the Sound pill turns the studio's sound on, remembers it, and the trailer plays with its sound",
    (await ev("localStorage.getItem('openfield.sound')")) === "on" && (await ev("document.querySelector('.trailer-sound').getAttribute('aria-pressed')")) === "true"
    && (await ev("document.querySelector('.lobby-screen video.trailer').muted")) === false && (await ev("window.openfield.slots().pinned")) >= 1);
  await ev("window.openfield.ui.go('direct')");
  await b.sleep(150);
  check("another room: the trailer is silent and the choice stands", (await ev("document.querySelector('.lobby-screen video.trailer').muted")) === true && (await ev("localStorage.getItem('openfield.sound')")) === "on");
  await ev("window.openfield.ui.go('lobby')");
  await b.click("[data-station=lobby] .lobby-headline");
  await b.sleep(200);
  check("back in the Lobby the trailer's sound is back", (await ev("document.querySelector('.lobby-screen video.trailer').muted")) === false);
  check("no audio element anywhere", (await ev("document.querySelectorAll('audio').length")) === 0);
  await b.click(".trailer-sound");
  await b.sleep(150);
  check("pressed again: off, muted, remembered as off", (await ev("localStorage.getItem('openfield.sound')")) === "off" && (await ev("document.querySelector('.lobby-screen video.trailer').muted")) === true);
  await b.emulate([{ name: "prefers-reduced-motion", value: "" }]);
  // -- the galleries: every camera move and effect whose render held, each frame playing its take ---------------------
  if (await ev("document.querySelectorAll('.move-grid .show-card').length > 0")) {
    check("the camera moves gallery plays only moves whose render held", await ev("(() => { const ok = new Set(window.openfield.store.get().moves.moves.filter((m) => m.validated).map((m) => m.id)); return [...document.querySelectorAll('.move-grid .show-card')].every((c) => ok.has(c.dataset.move)); })()"));
    await ev("(() => { const f = [...document.querySelectorAll('.show-filter')].find((x) => !['featured', 'all'].includes(x.dataset.filter)); f.click(); return true; })()");
    await b.sleep(150);
    check("a filter shows exactly the moves it counts", await ev("(() => { const f = document.querySelector('.show-filter[aria-pressed=true]'); return document.querySelectorAll('.move-grid > li:not([hidden])').length === Number(f.querySelector('.num').textContent); })()"));
    const first = await ev("document.querySelector('.move-grid > li:not([hidden]) .show-card').dataset.move");
    await ev("document.querySelector('.move-grid > li:not([hidden]) .show-card').click()");
    await b.waitFor("document.querySelector('.sheet-move video.move-take') && document.querySelector('.sheet-move .stage-view')", { timeout: 10000, label: "a move opens its own page" });
    check("a move's page plays its take beside the camera's path, and the address names the move", (await ev("location.hash")) === `#/lobby/${first}`, await ev("location.hash"));
    check("and says the words the video model reads", (await ev("document.querySelector('.sheet-move .move-phrase').textContent.length")) > 20);
    await b.key("ArrowRight");
    await b.sleep(250);
    check("the arrow keys walk to the next move", (await ev("location.hash")) !== `#/lobby/${first}`, await ev("location.hash"));
    // the take saved with its camera path: recorded in the page, a real video file
    if (await ev("Boolean(document.querySelector('.sheet-move .save-path'))")) {
      await ev(`(() => { window.__saved = null; const click = HTMLAnchorElement.prototype.click; HTMLAnchorElement.prototype.click = function () { if (this.download && this.href.startsWith("blob:")) { window.__saved = { name: this.download, href: this.href }; return; } return click.call(this); }; return true; })()`);
      await ev("document.querySelector('.sheet-move .save-path').click()"); // the test browser lets a take sound without a gesture
      await b.waitFor("window.__saved !== null", { timeout: 40000, label: "the take saved with its camera path" });
      const saved = JSON.parse(await ev("fetch(window.__saved.href).then((r) => r.blob()).then((x) => JSON.stringify({ name: window.__saved.name, size: x.size }))"));
      check("a move's take saves with its camera path, as a video file", /[.](mp4|webm)$/.test(saved.name) && saved.size > 20000, JSON.stringify(saved));
    }
    await b.key("Escape");
    await b.sleep(250);
    check("closing the move's page gives the address back to the Lobby", (await ev("location.hash")) === "#/lobby" && !(await ev("Boolean(document.querySelector('.sheet-move'))")));
    // -- the move page flies in from its card: the frame is named for the flight only, and held still it just opens ----------
    await b.emulate([{ name: "prefers-reduced-motion", value: "no-preference" }]);
    await ev("document.querySelector('.move-grid > li:not([hidden]) .show-card').scrollIntoView({ block: 'center' })");
    await b.sleep(200);
    const NAMED = "[...document.querySelectorAll('*')].filter((e) => getComputedStyle(e).viewTransitionName === 'move-frame').length";
    const flown = JSON.parse(await ev(`(() => { const card = document.querySelector(".move-grid > li:not([hidden]) .show-card"); const frame = card.querySelector(".show-frame"); card.click(); return JSON.stringify({ name: getComputedStyle(frame).viewTransitionName, carried: Boolean(document.querySelector(".sheet-scrim.carried")) }); })()`));
    check("a click on a camera-move card names its frame move-frame at once, and the page's scrim is carried", flown.name === "move-frame" && flown.carried, JSON.stringify(flown));
    check("and both names are gone when the change ends", await within(`${NAMED} === 0 && getComputedStyle(document.querySelector('.move-grid > li:not([hidden]) .show-frame')).viewTransitionName === 'none'`, 3000));
    check("the page is up with its take", await within("document.querySelector('.sheet-move video.move-take')", 3000));
    await b.key("Escape");
    check("Escape closes it", await within("!document.querySelector('.sheet-scrim')", 600));
    await ev("document.querySelector('.move-grid > li:not([hidden]) .show-card').focus()");
    await b.key("Enter");
    check("Enter on a focused card opens the page the same way", await within("document.querySelector('.sheet-scrim.carried') && document.querySelector('.sheet-move video.move-take')", 3000));
    await b.key("Escape");
    check("and Escape gives focus back to that card", await within("document.activeElement?.classList.contains('show-card')", 600));
    await within("!document.querySelector('.sheet-scrim')", 600);
    await b.emulate([{ name: "prefers-reduced-motion", value: "reduce" }]);
    await ev("document.querySelector('.move-grid > li:not([hidden]) .show-card').click()");
    check("held still, the same click opens the page with no carried class and no name", await ev(`!document.querySelector('.sheet-scrim.carried') && Boolean(document.querySelector('.sheet-move')) && ${NAMED} === 0`));
    await b.key("Escape");
    await b.sleep(100);
    await b.emulate([{ name: "prefers-reduced-motion", value: "" }]);
    check("the effects rail plays only effects whose render held", await ev("(() => { const ok = new Set(window.openfield.store.get().moves.effects.filter((e) => e.tested).map((e) => e.id)); const cards = [...document.querySelectorAll('.effect-rail .show-card')]; return cards.length > 0 && cards.every((c) => ok.has(c.dataset.effect)); })()"));
  } else check("with no recorded move loops the galleries stay hidden", await ev("document.querySelector('.moves-show').hidden && document.querySelector('.effects-show').hidden"));
  // -- a move's own address: its page opens, the arrows say which way they walk, and an address with no move goes home ---------------
  await ev(`location.hash = "#/lobby/bullet_time"`);
  const named = await within("document.querySelector('.sheet-move')", 5000) && (await ev("document.querySelector('.sheet-move .sheet-head h3').textContent"));
  check("an address like #/lobby/bullet_time opens that move's page, and its head names the move", /Bullet time/.test(named), named);
  if (named && (await ev("document.querySelectorAll('.move-grid > li').length >= 2"))) { // a copy with recorded move loops has another move to walk to
    await b.key("ArrowRight");
    await b.sleep(250);
    const walked = await ev("location.hash");
    check("the right arrow walks to another move and says it came in from the right", /^#\/lobby\/[a-z0-9_]+$/.test(walked) && walked !== "#/lobby/bullet_time" && (await ev("document.body.dataset.dir")) === "next", `${walked}, from the ${await ev("document.body.dataset.dir")}`);
  }
  await b.key("Escape");
  await b.sleep(250);
  await ev(`location.hash = "#/lobby/not-a-move"`);
  const told = await within("document.querySelector('.notice')", 1500);
  const home = await within("location.hash === '#/lobby' && !document.querySelector('.sheet-move')", 1500);
  // among the notices: a save that finished a moment ago may have left its own "Saved." line first
  check("an address with no such move says so, and the address goes back to the Lobby", told && home && (await ev("[...document.querySelectorAll('.notice')].some((n) => /No such camera move/.test(n.textContent))")), `${await ev("[...document.querySelectorAll('.notice')].map((n) => n.textContent).join(' | ') || 'no notice'")}, ${await ev("location.hash")}`);
  await ev("document.querySelectorAll('.notice').forEach((n) => n.querySelector('button')?.click())");
  if (mode === "live") {
    // the live app carries the bundled showcase, so the Relight poster has a recorded take to prove it
    await b.emulate([{ name: "prefers-reduced-motion", value: "no-preference" }]);
    const relight = await ev("(() => { const p = document.querySelector('.one-sheet[data-app=relight]'); p.scrollIntoView({ block: 'center' }); const r = p.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()");
    await b.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: relight.x, y: relight.y });
    await b.waitFor("(() => { const v = document.querySelector('.one-sheet[data-app=relight] video.sheet-take'); return v && !v.paused && v.currentTime > 0 && v.muted; })()", { timeout: 10000, label: "a poster plays its recorded take" });
    check("a poster plays its recorded take under the pointer, muted, with its ticket", await ev("document.querySelector('.one-sheet[data-app=relight]').classList.contains('live') && /Open weights/.test(document.querySelector('.one-sheet[data-app=relight] .ticket').textContent)"));
    await b.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 4, y: 4 });
    await b.sleep(150);
    check("and lets it go when the pointer leaves", await ev("document.querySelector('.one-sheet[data-app=relight] video.sheet-take') === null"));
    await b.emulate([{ name: "prefers-reduced-motion", value: "" }]);
    // a take link from the Lobby walks the browser's history: the address names the take it opened
    const card = await ev("document.querySelector('.card-row .lobby-card')?.getAttribute('href') ?? ''");
    if (card) {
      await ev("document.querySelector('.card-row .lobby-card').click()");
      await b.sleep(400);
      check("a Lobby take link puts the take in the address bar", (await ev("location.hash")) === card, await ev("location.hash"));
      await route("lobby");
    }
  } else {
    // this hosted copy holds only the takes the live run made: a poster with no recorded take shows no ticket
    check("a poster without a recorded take promises no ticket", await ev("(() => { const ids = new Set(window.openfield.store.get().recorded.map((r) => r.id)); return [...document.querySelectorAll('.poster-wall .one-sheet')].every((p) => !p.querySelector('.ticket') || ids.has(p.querySelector('.ticket-id').textContent.replace(/^/, 'tk_'))); })()"));
  }
  await ev("document.querySelector('.lobby-actions .btn.primary').click()");
  await b.waitFor("window.openfield.store.get().route === 'direct'", { label: "Start directing leads to Direct" });
  check("Start directing leads into the Direct room", (await ev("location.hash")) === "#/direct");
  check("the rail mark lies in the item of the room you are in", (await within("document.querySelector('.rail-item[data-route=direct] .rail-mark')")) && (await ev(`${MARKS}.length === 1`)));
  await b.sleep(300);
  // the skip link is a place on the page, not a room: it keeps you where you are
  await ev("location.hash = '#main'");
  await b.sleep(300);
  check("the skip link keeps the room", (await ev("window.openfield.store.get().route")) === "direct");
  await route("direct");

  if (mode === "live") {
    // -- the Move Pad ---------------------------------------------------------------------------------
    await ev("document.querySelector('.move-tile[aria-checked=true]').focus()");
    await b.key("ArrowRight");
    check("arrow keys move along the Move Pad", (await ev("window.openfield.forms.get().direct.rig.movement")) === "dolly_out");
    await ev("[...document.querySelectorAll('.move-tile')].find((t) => t.textContent.includes('Orbit 180')).click()");
    await b.sleep(150);
    check("the plan line counts the renders for the move", /1 still, 1 shot/i.test(await ev("document.querySelector('.plan').innerText")), await ev("document.querySelector('.plan').innerText"));
    await ev("[...document.querySelectorAll('.move-tile')].find((t) => t.textContent.includes('Dolly in')).click()");

    // -- validation ------------------------------------------------------------------------------------
    await ev("document.querySelectorAll('.section-head').forEach((h) => h.getAttribute('aria-expanded') === 'false' && h.click())");
    await b.type("#seed", "-5");
    await b.sleep(200);
    check("a bad seed is explained and blocks Shoot", /whole number/.test(await ev("document.querySelector('#seed').closest('.field').innerText")) && (await ev("document.querySelector('.prompt .btn.primary').disabled")));
    await ev("const s = document.querySelector('#seed'); s.value = ''; s.dispatchEvent(new Event('input', { bubbles: true }))");

    // -- a move played backwards takes no action, line or effect: the form names what would run backwards ---------------------------------
    // (the form paints on set, so one evaluate sets, reads and sets back: the page's estimate debounce never meets the shape the
    // server refuses, whatever the runner's speed)
    const backwards = JSON.parse(await ev(`(() => {
      const read = () => ({
        errors: [...document.querySelectorAll(".field-error:not([hidden])")].map((e) => e.textContent.trim()),
        hint: [...document.querySelectorAll(".dock-pane[data-pane=settings] .hint")].map((p) => p.textContent).find((t) => /played backwards, so it takes no effect/.test(t)) ?? "",
        plan: document.querySelector("[data-station=direct] .plan").innerText });
      window.openfield.forms.set((s) => ({ direct: { ...s.direct, rig: { ...s.direct.rig, movement: "through_object", effect: "rain" }, action: "He waves" } }));
      const refused = read();
      window.openfield.forms.set((s) => ({ direct: { ...s.direct, rig: { ...s.direct.rig, effect: "none" }, action: "" } }));
      const clean = read();
      window.openfield.forms.set((s) => ({ direct: { ...s.direct, rig: { ...s.direct.rig, movement: "dolly_in" } } }));
      return JSON.stringify({ ...refused, after: clean.errors });
    })()`));
    check("a move played backwards names the action that would run backwards", backwards.errors.some((t) => /leave What happens empty/.test(t)), JSON.stringify(backwards.errors));
    check("and the effect that would, with the way out", backwards.errors.some((t) => /set Effect to None/.test(t)), JSON.stringify(backwards.errors));
    check("its plan line says the move is rendered as its reverse", /played backwards/i.test(backwards.plan), backwards.plan);
    check("and the effect hint says it is played backwards", backwards.hint.includes("played backwards"), backwards.hint);
    check("with the effect None and no action the problems are gone", !backwards.after.some((t) => /backwards/.test(t)), JSON.stringify(backwards.after));

    // -- a whole Direct take: stills, approval, shot, receipt ---------------------------------------------
    check("Shoot waits for a subject", await ev("document.querySelector('.prompt .btn.primary').disabled"));
    await b.type("#subject", "A white lighthouse on a cliff at dusk, waves breaking below");
    await b.click(".prompt .btn.primary");
    await b.waitFor("document.querySelector('.screen[data-mode=approval]')", { timeout: 60000, label: "the stills wait for approval" });
    check("the stills stop for approval before any video", (await ev("document.querySelectorAll('.approve-row .still').length")) === 2);
    check("the approval stills carry their place in the row, 0 and 1", (await ev("[...document.querySelectorAll('.approve-row .still')].map((s) => s.style.getPropertyValue('--i').trim()).join()")) === "0,1");
    await b.click(".approve-actions .btn.primary");
    await b.waitFor("document.querySelector('.screen[data-mode=running]')", { label: "the render shows its progress" });
    check("a render shows its steps", (await ev("document.querySelectorAll('.steps li').length")) >= 4);
    await b.waitFor("document.querySelector('[data-station=direct] .screen[data-mode=ready] video.player')", { timeout: 90000, label: "the take is ready" }); // scoped: the Re-shoot wall shows a recorded take too
    check("the finished take plays in the Monitor", /^blob:|\/media\/take\.mp4/.test(await ev("document.querySelector('[data-station=direct] video.player').src")));
    check("with a transport bar", /\d\d:\d\d:\d\d:\d\d/.test(await ev("document.querySelector('.transport').innerText")));
    check("the planned camera rides on the wall", await ev("document.querySelector('[data-station=direct] .stage-inset') !== null"));
    check("and the dock shows the same stage", await ev("document.querySelector('.dock-pane[data-pane=settings] .stage-view') !== null"));
    await b.waitFor("document.querySelector('[data-station=direct] video.player')?.readyState >= 1", { label: "the take's length is known" });
    await ev("(() => { const v = document.querySelector('[data-station=direct] video.player'); v.pause(); v.currentTime = v.duration / 2; })()");
    await b.waitFor("Number(document.querySelector('[data-station=direct] .stage-inset')?.dataset.t) > 0.4", { label: "the planned camera follows the footage" });
    await b.click("[data-station=direct] .monitor-head .btn:last-child");
    await b.waitFor("document.querySelector('.audit-head .pill')", { label: "the receipt loads" });
    check("its audit says open weights only", /Open weights only/i.test(await ev("document.querySelector('.audit-head').innerText")));
    check("and its workflow can be downloaded for ComfyUI", await ev("[...document.querySelectorAll('.dock-actions a')].some((a) => /Download workflow/.test(a.textContent) && a.href.endsWith('workflows.zip'))"));

    // -- a tile plays its real render on hover ------------------------------------------------------------------
    await b.emulate([{ name: "prefers-reduced-motion", value: "no-preference" }]);
    await ev("document.querySelector('#tab-settings').click()");
    await b.sleep(200);
    // a move checked by eye plays its recorded loop while its tile is on screen, muted, with no pointer on it
    await ev("document.querySelector('.move-tile[data-move=dolly_in]').scrollIntoView({ block: 'center' })");
    await b.waitFor("(() => { const v = document.querySelector('.move-tile[data-move=dolly_in] video.live-clip'); return v && !v.paused && v.currentTime > 0 && v.muted; })()", { timeout: 10000, label: "a tested move's tile plays its loop" });
    check("a checked move's tile plays its recorded loop on screen", await ev("document.querySelector('.move-tile[data-move=dolly_in]').classList.contains('live')"));
    check("a move with no checked render keeps its track drawing, even under the pointer", await ev("!document.querySelector('.move-tile[data-move=rack_focus] video')"));

    // -- the keyboard sheet ------------------------------------------------------------------------------------------
    await ev("document.activeElement?.blur?.()");
    await b.key("?");
    await b.waitFor("document.querySelector('.sheet-keys')", { label: "? opens the keyboard sheet" });
    check("? lists the keyboard shortcuts", /Previous or next take/i.test(await ev("document.querySelector('.sheet-keys').innerText")));
    await b.key("Escape");
    check("and Escape closes it", await within("!document.querySelector('.sheet-keys')", 600)); // it fades for 120 ms
    check("a sheet closed twice leaves once: ui.showKeys() then two close() calls throw nothing", await ev("(() => { try { const s = window.openfield.ui.showKeys(); s.close(); s.close(); return true; } catch { return false; } })()"));
    check("and its scrim is gone when it has left", await within("!document.querySelector('.sheet-scrim')", 3000));
    await b.emulate([{ name: "prefers-reduced-motion", value: "" }]);

    // -- start from your own image: the control, the drop zone, and Shoot waiting for a file ----------------------
    await ev("document.querySelector('#tab-settings').click()");
    await ev("document.querySelectorAll('.section-head').forEach((h) => h.getAttribute('aria-expanded') === 'false' && h.click())");
    await ev("[...document.querySelectorAll('[role=radio]')].find((x) => x.textContent.trim() === 'My image').click()");
    await b.sleep(200);
    check("My image shows a named drop zone", /Add your image/.test(await ev("document.querySelector('.dock-pane[data-pane=settings] .drop')?.innerText ?? ''")));
    check("and says what the result is checked against", /checked against/i.test(await ev("document.querySelector('.dock-pane[data-pane=settings]').innerText")));
    check("Shoot waits for the image", await ev("document.querySelector('.prompt .btn.primary').disabled"));
    await ev("[...document.querySelectorAll('[role=radio]')].find((x) => x.textContent.trim() === 'Prompt').click()");
    await b.sleep(150);
    check("and is back once the prompt is the start", !(await ev("document.querySelector('.prompt .btn.primary').disabled")));

    // -- quality: three tiers, honest about what was checked, a measured time once something rendered here -------
    check("Quality has three tiers", (await ev("document.querySelectorAll('.dock-pane[data-pane=settings] .seg[aria-label=Quality] [role=radio]').length")) === 3);
    await ev("[...document.querySelectorAll('.dock-pane[data-pane=settings] .seg[aria-label=Quality] [role=radio]')].find((x) => x.textContent.trim() === 'Fine').click()");
    await b.sleep(150);
    check("Fine says what it changes", /30 still steps/.test(await ev("document.querySelector('.dock-pane[data-pane=settings]').innerText")));
    await ev("[...document.querySelectorAll('.dock-pane[data-pane=settings] .seg[aria-label=Quality] [role=radio]')].find((x) => x.textContent.trim() === 'Standard').click()");
    await b.sleep(600);
    check("the plan line carries a time measured on this backend after a take rendered here", /measured here|No time measured yet/.test(await ev("document.querySelector('[data-station=direct] .plan').innerText")), await ev("document.querySelector('[data-station=direct] .plan').innerText"));

    // -- round 5: where the camera starts (three dials, a readout that stays honest), the two kinds of effect ----------
    check("the stage has three dials for where the camera starts", (await ev("document.querySelectorAll('.dock-pane[data-pane=settings] .angle-dials .seg').length")) === 3);
    await ev("document.querySelector('.angle-dials [aria-label=\"Low angle\"]').click()");
    await b.sleep(300);
    check("a dial pivots the camera and the readout says the hero is re-shot from there", /Low angle/.test(await ev("document.querySelector('.angle-readout').innerText")) && /re-shot from here/.test(await ev("document.querySelector('.angle-readout').innerText")), await ev("document.querySelector('.angle-readout').innerText"));
    await ev("document.querySelector('.angle-dials [aria-label=\"Wide\"]').click()");
    await b.sleep(300);
    check("a second dial reaches any position, with nothing said about testing", /Low angle · Wide/.test(await ev("document.querySelector('.angle-readout').innerText")) && !/tested/i.test(await ev("document.querySelector('.angle-readout').innerText")), await ev("document.querySelector('.angle-readout').innerText"));
    check("and the plan line counts the angled still", /angled still/i.test(await ev("document.querySelector('[data-station=direct] .plan').innerText")), await ev("document.querySelector('[data-station=direct] .plan').innerText"));
    await ev("[...document.querySelectorAll('.angle-line .btn')].find((x) => x.textContent.includes('As shot'))?.click()");
    await b.sleep(200);
    check("As shot puts the camera back where the hero was shot", (await ev("window.openfield.forms.get().direct.rig.angle")) === "front/eye/medium");
    check("the Effect select groups weather and transformations", (await ev("document.querySelectorAll('.dock-pane[data-pane=settings] #effect optgroup').length")) === 2);

    // -- the Connect sheet: a target typed in, tested honestly, never switched by a test --------------------------
    await b.click(".backend-btn");
    await b.click(".menu .connect-btn");
    await b.waitFor("document.querySelector('.sheet-connect #connect-url')", { label: "the Connect sheet opens" });
    const current = await ev("window.openfield.store.get().status.backend.target?.url ?? ''");
    await ev(`const u = document.querySelector('#connect-url'); u.value = ${JSON.stringify(current)}; u.dispatchEvent(new Event('input', { bubbles: true }))`);
    check("Use waits for a passing test", await ev("document.querySelector('.sheet-connect .btn.primary').disabled"));
    await ev("[...document.querySelectorAll('.sheet-connect .connect-actions .btn')].find((x) => /^Test/.test(x.textContent)).click()");
    await b.waitFor("document.querySelector('.sheet-connect .connect-result')", { timeout: 15000, label: "the test answers" });
    check("a reachable proxy says so", /Reachable/.test(await ev("document.querySelector('.sheet-connect .connect-result').innerText")), await ev("document.querySelector('.sheet-connect .connect-result').innerText"));
    check("without a ComfyUI address the model files are honestly unchecked", /not checked/i.test(await ev("document.querySelector('.sheet-connect .connect-result').innerText")));
    check("and Use is enabled only now", !(await ev("document.querySelector('.sheet-connect .btn.primary').disabled")));
    check("the sheet is accessible", (await ev(AUDIT)).length === 0, (await ev(AUDIT)).join("; "));
    await b.key("Escape");
    check("Escape closes the sheet", await within("document.querySelector('.sheet-connect') === null", 2000));  // a sheet leaves on a transition, so give it the time that takes
    check("and nothing switched", !(await ev("window.openfield.store.get().status.backend.locked")));

    // -- keyboard and the dock -------------------------------------------------------------------------------
    await b.key("[");
    check("[ hides the settings panel", (await ev("document.querySelector('.app').dataset.dock")) === "closed");
    await b.key("[");

    // -- the other stations ----------------------------------------------------------------------------------
    for (const name of ["takes", "cast", "reshoot"]) {
      await route(name);
      check(`the ${name} station opens`, await ev(`!document.querySelector('[data-station=${name}]').hidden`));
    }
    await route("takes");
    check("Takes lists the take with its receipt one click away", (await ev("document.querySelectorAll('.take-row').length")) >= 1);
  } else {
    // -- the hosted Replay ----------------------------------------------------------------------------------------
    await b.sleep(600);
    check("the first screen shows a recorded take", /Recorded take/i.test(await ev("document.querySelector('.monitor-head').innerText")));
    check("with Recreate (replay) in the prompt bar", /Recreate \(replay\)/i.test(await ev("document.querySelector('.prompt .btn.primary').innerText")));
    await b.click(".prompt .btn.primary");
    await b.waitFor("document.querySelector('.screen[data-mode=running]')", { label: "the recording plays back" });
    check("a replay says it is a recording", /Replaying a recorded take/.test(await ev("document.querySelector('.run-note').innerText")));
    await b.waitFor("window.openfield.store.get().takes.some((t) => t.replay && t.status === 'succeeded')", { timeout: 40000, label: "the replay finishes" });
    await b.waitFor("document.querySelector('.screen[data-mode=ready] video.player')", { label: "the replayed take plays" });
    check("the replayed take carries the Replay pill", /Replay/i.test(await ev("document.querySelector('.monitor-head').innerText")));
    // a plain file server may not answer range requests, so play rather than seek
    await ev("(() => { const v = document.querySelector('[data-station=direct] video.player'); v.muted = true; v.play().catch(() => {}); })()");
    await b.waitFor("Number(document.querySelector('[data-station=direct] .stage-inset')?.dataset.t) > 0.1", { label: "the planned camera moves with the recorded footage" });
    // anything that was not recorded cannot be shot
    await ev("window.openfield.forms.set((s) => ({ direct: { ...s.direct, subject: 'Something that was never recorded' } }))");
    await b.sleep(250);
    check("an edited recipe says Needs a backend", /Needs a backend/i.test(await ev("document.querySelector('[data-station=direct] .prompt .btn.primary').innerText")));
    check("and the plan line explains why", /Recorded takes only/.test(await ev("document.querySelector('[data-station=direct] .plan').innerText")));
    await ev("window.openfield.forms.set((s) => ({ direct: { ...s.direct, heroMode: 'image', sourceFile: { name: 'me.png', size: 10 } } }))");
    await b.sleep(250);
    check("a shot from your image needs a backend on the hosted copy", /Replay cannot start from your image/.test(await ev("document.querySelector('[data-station=direct] .plan').innerText")));
    await ev("window.openfield.forms.set((s) => ({ direct: { ...s.direct, heroMode: 'prompt', sourceFile: null } }))");
    await ev("window.openfield.ui.openDock('take')");
    await b.waitFor("document.querySelector('.audit-head .pill')", { label: "a recorded receipt loads" });
    check("a recorded take shows its audit and licences", /Open weights only/i.test(await ev("document.querySelector('.audit-head').innerText")));
    // a take link opens that take, playing, with its receipt open: the address the hosted copy shares
    const shared = await ev("window.openfield.store.get().recorded.find((r) => r.kind === 'direct')?.id ?? ''");
    await ev(`location.hash = "#/takes/${shared}"`);
    await b.waitFor(`window.openfield.store.get().selected === "${shared}"`, { label: "the take link selects the take" });
    await b.sleep(300);
    check("a take link lands on the take with its receipt open", await ev("document.querySelector('[data-station=direct] .screen[data-mode=ready] video.player') !== null && window.openfield.ui.get().dockTab === 'take'"));
    // the hosted copy cannot connect anything: the sheet says how to run the app instead
    await b.click(".backend-btn");
    await b.click(".menu .connect-btn");
    await b.waitFor("document.querySelector('.sheet-connect')", { label: "the Connect sheet opens on the hosted copy" });
    check("the hosted copy points at installing the app", /pip install/.test(await ev("document.querySelector('.sheet-connect').innerText")));
    check("and has no address field", await ev("document.querySelector('.sheet-connect #connect-url') === null"));
    await b.key("Escape");
  }

  // -- the Chat room: the person's own agent (here the tests' stand-in) working the studio through its MCP tools -----------
  await route("chat");
  if (mode === "live") {
    await b.waitFor("!document.querySelector('.chat-compose').hidden", { label: "the Chat room finds its agent" });
    check("the Chat room names its agent and the render cap", /Claude Code on this computer .* 6 of 6 renders left in this chat/.test(await ev("document.querySelector('.chat-lane').textContent")), await ev("document.querySelector('.chat-lane').textContent"));
    check("and offers a few things to ask", (await ev("document.querySelectorAll('.callsheet-lines button').length")) === 4); // round 17: the asks are ruled lines on the call sheet, not chips
    check("beside the take an agent made in this room, looping", await ev("Boolean(document.querySelector('.chat-made-fig video'))"));
    // the agent's words are drawn into one element from the first word to the last: mark each message as it first appears
    await ev(`(() => { window.__agentNodes = []; new MutationObserver((records) => { for (const r of records) for (const n of r.addedNodes) if (n.classList?.contains("chat-msg") && n.classList.contains("agent")) window.__agentNodes.push(n); }).observe(document.querySelector(".chat-log"), { childList: true }); return true; })()`);
    await b.type(".chat-input", "shoot a lighthouse at dusk");
    await b.key("Enter");
    await b.waitFor("[...document.querySelectorAll('.chat-msg.agent')].some((m) => m.textContent.includes('stills come first')) && document.querySelector('.chat-status').textContent === ''", { timeout: 20000, label: "the agent answers" });
    const answered = Date.now();
    check("the agent's words stay one element from their first word to their last", await ev("window.__agentNodes.length >= 1 && window.__agentNodes.every((n) => n.isConnected) && window.__agentNodes.length === document.querySelectorAll('.chat-msg.agent').length && window.__agentNodes.at(-1).textContent.includes('stills come first')"), await ev("window.__agentNodes.length + ' marked, ' + document.querySelectorAll('.chat-msg.agent').length + ' on the page'"));
    check("the person's line, the agent's words and the tool it used are on the page", (await ev("[...document.querySelectorAll('.chat-log > *')].map((n) => n.className.split(' ')[0]).join()")) === "chat-msg,chat-msg,chat-tool,chat-msg");
    check("the tool reads in the room's words, with the take it started as a link", /Started a shot/.test(await ev("document.querySelector('.chat-tool').textContent")) && (await ev("document.querySelector('.chat-tool .take-link')?.getAttribute('href')")) === "#/takes/tk_20261025_120000_abcd");
    check("a take id in the agent's words is a link too", (await ev("document.querySelectorAll('.chat-msg.agent .take-link').length")) === 1);
    const problems = await ev(AUDIT);
    check("chat: names, unique ids and target sizes", problems.length === 0, problems.slice(0, 3).join("; "));
    await b.sleep(Math.max(0, 2000 - (Date.now() - answered))); // two seconds after the turn ended
    check("nothing is marked as still arriving two seconds after the turn", await ev("document.querySelectorAll('.chat-msg.agent.live').length === 0"));
    await b.click(".chat-bar .btn");
    await b.waitFor("document.querySelectorAll('.chat-log > *').length === 0 && !document.querySelector('.chat-intro').hidden", { label: "New chat clears the conversation" });
    check("New chat clears the conversation", true);
  } else {
    await b.waitFor("!document.querySelector('.chat-off').hidden", { label: "the hosted Chat room explains itself" });
    check("the hosted copy cannot open the Chat room and says how to get one", /pip install/.test(await ev("document.querySelector('.chat-off').innerText")) && (await ev("document.querySelector('.chat-compose').hidden")));
    // the card plays the take an open-weights agent made here, when this copy holds that take and its loop
    await b.waitFor("window.openfield.store.get().previews !== null", { label: "the previews are answered" });
    if (await ev(`(() => { const s = window.openfield.store.get(); return s.recorded.some((r) => r.id === "${MADE_HERE}") && Boolean(s.previews?.takes?.["${MADE_HERE}"]); })()`)) {
      const clip = await within("document.querySelector('.chat-off video.live-clip')") && (await ev("document.querySelector('.chat-off video.live-clip').dataset.src"));
      check("the hosted Chat card plays the take an open-weights agent made here, on a loop", Boolean(clip) && clip.includes(MADE_HERE), clip);
      await ev("[...document.querySelectorAll('.chat-off button')].find((x) => x.textContent.trim() === 'Open the take')?.click()");
      check("and Open the take opens that take", await within(`location.hash === "#/takes/${MADE_HERE}" && window.openfield.store.get().selected === "${MADE_HERE}"`));
    } else check("without that take the Chat card is a plain notice with its icon and no video", await ev("Boolean(document.querySelector('.chat-off .icon')) && !document.querySelector('.chat-off video')"));
  }

  // -- the Shots board: choosing a setup moves the pressed mark and rebuilds nothing --------------------------------------------------
  await route("shots");
  if (await ev("document.querySelectorAll('.shots-board button.shots-tile').length >= 2")) { // a copy with a recorded board (the bundled showcase has them)
    await ev("document.querySelectorAll('.shots-board button.shots-tile')[0].click()");
    await ev("document.querySelectorAll('.shots-board img').forEach((img) => { img.__kept = true; })");
    const pictures = await ev("document.querySelectorAll('.shots-board img').length");
    await ev("document.querySelectorAll('.shots-board button.shots-tile')[1].click()");
    await b.sleep(250);
    const pressed = await ev("[...document.querySelectorAll('.shots-board button.shots-tile')].map((t) => t.getAttribute('aria-pressed')).join()");
    check("choosing a second setup moves the pressed mark to it", pressed.startsWith("false,true,false"), pressed);
    check("and rebuilds nothing: the stills on the board are the same elements", pictures >= 2 && (await ev("[...document.querySelectorAll('.shots-board img')].filter((img) => img.__kept).length")) === pictures, `${pictures} stills`);
  } else check("with no recorded board the nine setups wait as empty frames", await ev("document.querySelector('.shots-board').dataset.state === 'empty' && document.querySelectorAll('.shots-board .pending').length === 9"));

  // -- sharing: a take's Share sheet, with its caption, the five places, and the page that unfurls on the hosted copy ------
  await route("takes");
  await ev("window.openfield.ui.openTake(window.openfield.store.get().status.hero_take ?? window.openfield.store.get().recorded[0].id)");
  await b.waitFor("[...document.querySelectorAll('.dock-actions .btn')].some((x) => x.textContent.includes('Share'))", { timeout: 10000, label: "the take's Share button" });
  await ev("[...document.querySelectorAll('.dock-actions .btn')].find((x) => x.textContent.includes('Share')).click()");
  await b.waitFor("document.querySelector('.sheet-share') !== null", { label: "the Share sheet opens" });
  check("the Share sheet offers X, Reddit, LinkedIn, WhatsApp and Telegram", (await ev("[...document.querySelectorAll('.sheet-share .share-links a')].map((a) => new URL(a.href).hostname).join()")) === "x.com,www.reddit.com,www.linkedin.com,wa.me,t.me");
  check("its caption carries the take's link and the contest tag", /#OpenSourceHiggsfield/.test(await ev("document.querySelector('.sheet-share pre').textContent")) && (mode === "static" ? /\/t\/tk_\w+\.html/ : /#\/takes\/tk_/).test(await ev("document.querySelector('.sheet-share pre').textContent")), await ev("document.querySelector('.sheet-share pre').textContent"));
  check("and a download of the video itself", await ev("Boolean(document.querySelector('.sheet-share a[download]'))"));
  // a Direct take's shot sheet: its frames, the camera's path, the words and the receipt, drawn in the page as a PNG
  if (await ev("Boolean(document.querySelector('.sheet-share .save-sheet'))")) {
    await ev(`(() => { window.__sheet = null; const click = HTMLAnchorElement.prototype.click; HTMLAnchorElement.prototype.click = function () { if (this.download && this.href.startsWith("blob:") && this.download.endsWith(".png")) { window.__sheet = { name: this.download, href: this.href }; return; } return click.call(this); }; return true; })()`);
    await ev("document.querySelector('.sheet-share .save-sheet').click()");
    await b.waitFor("window.__sheet !== null", { timeout: 20000, label: "the shot sheet" });
    const sheet = JSON.parse(await ev("fetch(window.__sheet.href).then((r) => r.blob()).then((x) => JSON.stringify({ name: window.__sheet.name, size: x.size, type: x.type }))"));
    check("a Direct take saves its shot sheet as a picture", /^shot-sheet-tk_\w+[.]png$/.test(sheet.name) && sheet.type === "image/png" && sheet.size > 100000, JSON.stringify(sheet));
  }
  check("the address bar carries the opened take", /#\/takes\/tk_/.test(await ev("location.hash")));
  await b.key("Escape");
  await b.sleep(200);
  // anyone can check a receipt themselves: the browser hashes receipt.json the way openfield verify does
  if (await ev("Boolean(document.querySelector('.verdict .seal-check'))")) {
    await ev("document.querySelector('.verdict .seal-check').click()");
    await b.waitFor("document.querySelector('.verdict [data-result]')", { timeout: 10000, label: "the seal check" });
    check("a receipt's seal checks out in the browser itself", (await ev("document.querySelector('.verdict [data-result]').dataset.result")) === "pass", await ev("document.querySelector('.verdict [data-result]').textContent"));
    // what the browser cannot read is an error, never a fail; a receipt changed by one byte is a fail
    await ev(`(() => { const real = window.fetch; window.__realFetch = real; window.__seal = null; window.fetch = async (input, init) => { const address = typeof input === "string" ? input : input.url; if (!/receipt[.]json/.test(address) || !window.__seal) return real(input, init); if (window.__seal === "gone") return new Response("not found", { status: 404 }); const text = await (await real(input, init)).text(); return new Response(text.replace(/[0-9]/, (d) => (d === "9" ? "8" : String(Number(d) + 1))), { status: 200 }); }; return true; })()`);
    const sealAs = async (how) => {
      await ev(`window.__seal = ${JSON.stringify(how)}`);
      await ev("document.querySelector('.verdict .seal-check').click()");
      return (await within("document.querySelector('.verdict [data-result]')", 10000)) ? ev("document.querySelector('.verdict [data-result]').dataset.result") : "no answer";
    };
    check("a receipt the browser cannot fetch is an error, not a fail", (await sealAs("gone")) === "error");
    check("a receipt changed by one byte fails its seal", (await sealAs("changed")) === "fail");
    await ev("window.fetch = window.__realFetch");
  }
  // two takes side by side, over what their receipts say differently (a copy holding one take offers no Compare)
  if (!(await ev("[...document.querySelectorAll('.dock-actions .btn')].some((x) => x.textContent.includes('Compare'))"))) {
    check("a copy with a single take offers nothing to compare", (await ev("new Set([...window.openfield.store.get().takes, ...window.openfield.store.get().recorded].filter((t) => t.status === 'succeeded').map((t) => t.replay_of ?? t.id)).size")) <= 1);
  } else {
    await ev("window.__opener = [...document.querySelectorAll('.dock-actions .btn')].find((x) => x.textContent.includes('Compare')); window.__opener.focus(); window.__opener.click(); true"); // opened from the keyboard's place: the button has focus
    await b.waitFor("document.querySelector('.sheet-compare') && (document.querySelector('.compare-row') || /no other finished take|same way|no receipt/i.test(document.querySelector('.sheet-compare').innerText))", { timeout: 10000, label: "the Compare sheet reads both receipts" });
    if (await ev("Boolean(document.querySelector('.compare-row'))")) {
      check("Compare plays both takes and says how many things differ", (await ev("document.querySelectorAll('.sheet-compare video.compare-video').length")) === 2 && /\d+ of \d+ things differ/.test(await ev("document.querySelector('.compare-summary').textContent")), await ev("document.querySelector('.compare-summary').textContent"));
      const first = await ev("document.querySelector('.compare-option[aria-checked=true]')?.title ?? ''");
      await ev("document.querySelectorAll('.compare-option')[1]?.click()");
      await b.waitFor(`document.querySelector('.compare-option[aria-checked=true]')?.title !== ${JSON.stringify(first)} && document.querySelector('.compare-row') !== null`, { timeout: 8000, label: "another take to compare" });
      check("picking another take compares that one", true);
      // a take someone paused stays paused when the tab comes back; one that was playing plays again (motion allowed)
      await b.emulate([{ name: "prefers-reduced-motion", value: "no-preference" }]);
      const tab = (hidden) => `(() => { Object.defineProperty(document, "hidden", { value: ${hidden}, configurable: true }); document.dispatchEvent(new Event("visibilitychange")); return true; })()`;
      if (!(await ev("document.querySelector('.compare-video').paused"))) await ev("document.querySelector('.compare-play').click()");
      await b.waitFor("[...document.querySelectorAll('.compare-video')].every((v) => v.paused)", { timeout: 4000, label: "the compared takes pause" });
      await ev(tab(true));
      await ev(tab(false));
      await b.sleep(400);
      check("a paused take stays paused when the tab comes back", await ev("[...document.querySelectorAll('.compare-video')].every((v) => v.paused)"));
      await ev("document.querySelector('.compare-play').click()");
      await b.waitFor("!document.querySelector('.compare-video').paused", { timeout: 6000, label: "Play both" });
      await ev(tab(true));
      await b.sleep(150);
      const restedWithTab = await ev("[...document.querySelectorAll('.compare-video')].every((v) => v.paused)");
      await ev(tab(false));
      await b.waitFor("!document.querySelector('.compare-video').paused", { timeout: 4000, label: "the take plays again with the tab" });
      check("a playing take rests with the tab and plays again when it comes back", restedWithTab);
      await ev("(() => { delete document.hidden; return true; })()");
      await b.emulate([{ name: "prefers-reduced-motion", value: "reduce" }]);
      await b.sleep(300);
      check("reduced motion turned on mid-play stops the compared takes", await ev("[...document.querySelectorAll('.compare-video')].every((v) => v.paused)"));
      await b.emulate([{ name: "prefers-reduced-motion", value: "" }]);
      const problems = await ev(AUDIT);
      check("compare: names, unique ids and target sizes", problems.length === 0, problems.slice(0, 3).join("; "));
      // the keyboard: one tab stop in the picker with the arrows moving it, and a Tab that never reaches the rooms behind the sheet
      check("the compare picker is one radio group with a single tab stop, on the chosen take", await ev(`(() => { const stops = [...document.querySelectorAll('.compare-pick [role=radio][tabindex="0"]')]; return stops.length === 1 && stops[0].getAttribute('aria-checked') === 'true'; })()`));
      const radios = await ev("document.querySelectorAll('.compare-option').length");
      if (radios >= 2) {
        const at = await ev("[...document.querySelectorAll('.compare-option')].findIndex((x) => x.getAttribute('aria-checked') === 'true')");
        const to = (at + 1) % radios;
        await ev("document.querySelector('.compare-option[aria-checked=true]').focus()");
        await b.key("ArrowRight");
        const moved = await within(`[...document.querySelectorAll('.compare-option')].findIndex((x) => x.getAttribute('aria-checked') === 'true') === ${to}`, 4000);
        check("the right arrow moves the choice, and the tab stop with it", moved && (await ev(`(() => { const all = [...document.querySelectorAll('.compare-option')]; const stops = all.filter((x) => x.tabIndex === 0); return stops.length === 1 && stops[0] === all[${to}] && document.activeElement === all[${to}]; })()`)));
      }
      let behind = 0;
      let inside = 0;
      for (let i = 0; i < 10; i += 1) {
        await b.key("Tab");
        await b.sleep(30);
        const where = await ev("document.activeElement.closest('.sheet-compare') ? 'sheet' : document.activeElement.closest('.app') ? 'room' : 'page'");
        if (where === "room") behind += 1;
        if (where === "sheet") inside += 1;
      }
      check("ten Tabs never reach the rooms behind the sheet", behind === 0 && inside > 0, `${inside} in the sheet, ${behind} behind it`);
      check("the rooms behind the open sheet are inert", await ev("document.querySelector('.app').hasAttribute('inert')"));
    }
    await b.emulate([{ name: "prefers-reduced-motion", value: "no-preference" }]);
    await b.key("Escape"); // no sleep: the sheet starts leaving at once, and the page behind is live again
    check("Escape starts the Compare sheet's leave at once (leaving, or already gone)", await ev("Boolean(document.querySelector('.sheet-scrim.leaving')) || !document.querySelector('.sheet-scrim')"));
    check("and focus is back on the button that opened it, with the rooms live again, within 600 ms", await within("document.activeElement === window.__opener && !document.querySelector('.app').hasAttribute('inert')", 600));
    check("and the sheet is gone when it has left", await within("!document.querySelector('.sheet-scrim') && !document.querySelector('.sheet-compare')", 3000));
    await b.emulate([{ name: "prefers-reduced-motion", value: "" }]);
  }

  // -- the Lobby's quiz and Make your own --------------------------------------------------------------------------------
  await route("lobby");
  await ev("document.querySelector('.lobby-quiz').click()");
  await b.waitFor("document.querySelectorAll('.quiz-choices button').length === 4 || /no recorded camera moves/i.test(document.querySelector('.quiz')?.innerText ?? '')", { timeout: 8000, label: "the quiz opens" });
  if (await ev("document.querySelectorAll('.quiz-choices button').length === 4")) { // a copy with recorded move loops (the bundled showcase)
    check("the quiz plays a recorded move and offers four names", await ev("Boolean(document.querySelector('[class*=quiz] video, [class*=quiz] img'))"));
    check("the clip sits on a stage of its own", await ev("Boolean(document.querySelector('.quiz .quiz-stage'))"));
    check("it deals today's five, the same five clips for everyone", /Today's five · 1 of 5/.test(await ev("document.querySelector('.quiz-count')?.textContent ?? ''")), await ev("document.querySelector('.quiz-count')?.textContent ?? ''"));
    await ev("document.querySelector('.quiz-choices button').click()");
    await b.sleep(200);
    check("an answer is marked in words as well as colour", /correct|not this one/i.test(await ev("document.querySelector('.quiz')?.innerText ?? ''")), await ev("document.querySelector('.quiz')?.innerText.slice(0, 120) ?? 'no quiz'"));
    // play it through: the first name each round, then Next (the last round's button is See the score)
    const rounds = Number((await ev("document.querySelector('.quiz-count')?.textContent ?? ''")).match(/of (\d+)/)?.[1] ?? 0);
    await ev(`(() => { for (let i = 0; i < 12 && !document.querySelector(".quiz-score"); i += 1) { const choice = document.querySelector(".quiz-choices button:not([disabled])"); if (choice) choice.click(); const next = document.querySelector(".quiz-reveal:not([hidden]) .quiz-actions .btn.primary"); if (!next) break; next.click(); } return true; })()`);
    const score = await ev(`(() => { const q = document.querySelector(".quiz-score"); if (!q) return null; const letters = [...q.querySelectorAll(".quiz-ch")]; return { say: [...q.querySelectorAll(":scope > .sr-only")].map((x) => x.textContent), letters: letters.length, aria: letters.every((x) => x.getAttribute("aria-hidden") === "true"), shown: letters.map((x) => x.textContent).join("") }; })()`);
    check("the rounds end on a score: letters for the eye and one line for a screen reader", score !== null && score.say.length === 1 && /^\d+\/\d+$/.test(score.say[0]) && score.say[0].endsWith(`/${rounds}`) && score.letters >= score.say[0].length && score.aria && score.shown.startsWith(score.say[0]), JSON.stringify(score));
  } else check("with no recorded moves the quiz says so instead of a score", true);
  await b.key("Escape");
  await b.sleep(200);
  await ev("document.querySelector('.lobby-make').click()");
  await b.waitFor("document.querySelector('.sheet-make') !== null", { label: "Make your own opens" });
  check("Make your own gives three ways in, each with commands to copy", (await ev("document.querySelectorAll('.sheet-make pre').length")) === 3 && /pip install/.test(await ev("document.querySelector('.sheet-make').innerText")));
  check("and the measured cost of a shot", /2 to 3 cents/.test(await ev("document.querySelector('.sheet-make').innerText")));
  await b.key("Escape");
  await b.sleep(200);

  // -- accessibility basics on every station ------------------------------------------------------------------------
  for (const name of ["lobby", "direct", "reshoot", "cast", "takes", "chat"]) {
    await route(name);
    await ev("document.querySelectorAll('.section-head').forEach((h) => h.getAttribute('aria-expanded') === 'false' && h.click())");
    await b.sleep(150);
    const problems = await ev(AUDIT);
    check(`${name}: names, unique ids and target sizes`, problems.length === 0, problems.slice(0, 3).join("; "));
  }
  check("the start-up watchdog stays quiet on a good load", await ev("document.getElementById('boot-fail') === null"));
  if (LIVING) await living();

  // -- a phone ---------------------------------------------------------------------------------------------------------
  await b.viewport(390, 844, true, 2);
  await b.goto(url);
  await b.waitFor("window.openfield?.store.get().loaded");
  await b.sleep(500);
  const width = await ev("({ inner: innerWidth, scroll: document.documentElement.scrollWidth })");
  check("a phone gets no sideways scroll", width.scroll <= width.inner, JSON.stringify(width));
  check("and a bottom station bar", (await ev("getComputedStyle(document.querySelector('.rail')).flexDirection")) === "row");

  // -- reduced motion -----------------------------------------------------------------------------------------------------
  await b.viewport(1440, 900, false, 1);
  await b.emulate([{ name: "prefers-reduced-motion", value: "reduce" }]);
  await b.goto(url);
  await b.waitFor("window.openfield?.store.get().loaded");
  check("reduced motion is honoured (no animation runs)", await ev("[...document.querySelectorAll('*')].every((e) => parseFloat(getComputedStyle(e).animationDuration) < 0.01)"));
  check("under reduced motion nothing is armed to rise, and every poster on the wall shows", await ev("document.documentElement.classList.contains('hold-still') && document.querySelectorAll('.armed, .armed-self').length === 0 && [...document.querySelectorAll('.poster-wall > *')].every((e) => getComputedStyle(e).opacity === '1')"));
  // the root's class must not be a component's: under "still" the approval stills' rules styled every image on the page
  check("the page holds still under its own class, and other components keep their look", await ev(
    "document.documentElement.classList.contains('hold-still') && !document.documentElement.classList.contains('still') && [...document.querySelectorAll('.rail-art')].every((i) => i.getBoundingClientRect().width <= 48)"));
  const held = await ev("(() => { window.openfield.ui.go('takes'); return { swap: document.documentElement.classList.contains('room-swap'), prop: document.querySelector('.rail-item[aria-current=page] .rail-art').getAnimations().length }; })()");
  check("under reduced motion a room change is a cut: no room-swap, and the arriving prop does not animate", !held.swap && held.prop === 0, JSON.stringify(held));

  // -- a data saver: the same stillness with no setting asked for (motion is allowed, the browser says Save-Data) -------------------------
  await b.emulate([{ name: "prefers-reduced-motion", value: "no-preference" }]);
  const saver = await b.send("Page.addScriptToEvaluateOnNewDocument", { source: "Object.defineProperty(navigator, 'connection', { value: { saveData: true }, configurable: true });" });
  await b.goto(url);
  await b.waitFor("window.openfield?.store.get().loaded", { label: "the app loads with Save-Data on" });
  await b.sleep(1000);
  check("a browser that saves data holds the page still, with motion otherwise allowed", await ev("navigator.connection.saveData === true && !matchMedia('(prefers-reduced-motion: reduce)').matches && document.documentElement.classList.contains('hold-still')"));
  // finished requests (Resource Timing), and any loop clip given an address at all, fetched or not (a player someone opened
  // may hold its address: it waits for a press, and Chrome drops its preload under Save-Data)
  const videos = await ev("[...performance.getEntriesByType('resource').filter((e) => /[.]mp4/.test(e.name)).map((e) => e.name), ...[...document.querySelectorAll('video.live-clip[src]')].map((v) => 'loop ' + v.getAttribute('src'))]");
  check("and asks for no video", videos.length === 0, videos.join(" | ").slice(0, 200));
  const moving = await ev("document.getAnimations().length");
  check("and runs no animation", moving === 0, `${moving} animations`);
  await ev("window.openfield.ui.go('takes')");
  await b.sleep(300);
  check("and on a room with the light: the beam stands still and nothing animates", await ev("getComputedStyle(document.querySelector('.ambient')).display === 'block' && !document.documentElement.classList.contains('room-swap') && document.getAnimations().length === 0"), String(await ev("document.getAnimations().length")));
  await b.send("Page.removeScriptToEvaluateOnNewDocument", { identifier: saver.identifier });
  await b.emulate([{ name: "prefers-reduced-motion", value: "" }]);

  check("the page raised no script errors", b.log.errors.length === 0, b.log.errors.join(" | ").slice(0, 200));
  check("and no console errors", b.log.console.length === 0, b.log.console.join(" | ").slice(0, 200));
  const bad = b.log.bad.filter((u) => !u.includes("preview.jpg"));
  check("and no failed requests", bad.length === 0, bad.join(" | ").slice(0, 200));
} catch (error) {
  console.log(`FAIL  the run stopped: ${error.message}`);
  failures += 1;
} finally {
  await b.close();
}

console.log(failures ? `\n${failures} check(s) failed` : "\nall checks passed");
process.exit(failures ? 1 : 0);
