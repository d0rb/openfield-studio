// The Lobby's screen: a trailer cut from recorded takes, shown in the takes' own frame. art/trailer.json says which take
// each second comes from: the chip on the screen names it and opens it, and the reel under the screen lists every
// segment (a click plays from there). The Sound pill is the studio's one sound switch (ui/sound.js): it turns the takes'
// own sound on together with the studio's clicks, and the choice is remembered in this browser. The trailer is silent
// while its room is not on screen, and after a reload until the first press or key (a browser allows sound only after
// one). On the first visit of a session the screen's masking opens before the picture comes up.

import { h, icon } from "./dom.js";
import { printKeykode } from "./keykode.js";
import { claimSlot, freeSlot, liveClip } from "./wall.js";
import { play as cue, setSound, soundOn } from "./sound.js";
import { reelAt, trailerReel } from "../lib/deck.js";
import { holdStill } from "../lib/motion.js";

const ART = "art/";
const OPENED = "openfield.screen-opened";

const seenThisVisit = () => { try { return sessionStorage.getItem(OPENED) === "1"; } catch { return true; } };
const markSeen = () => { try { sessionStorage.setItem(OPENED, "1"); } catch { /* private window: it opens again next time */ } };
// has the person pressed or typed on this page yet? A browser will not unmute a video before that. Chrome, Safari 16.4 and
// Firefox 120 can say; an older one counts as "not yet" and waits for the first press.
const activated = () => Boolean(globalThis.navigator?.userActivation?.hasBeenActive);

export function createScreen(ui, { billing }) {
  const phone = globalThis.matchMedia?.("(max-width: 719px)").matches;
  // the sharp 1280 px copy wherever the screen is drawn wide enough to show it (from 1100 px the trailer runs across the
  // room, over a thousand pixels wide at any density), on a connection that is not saving data
  const connection = globalThis.navigator?.connection;
  const sharp = !phone && Boolean(globalThis.matchMedia?.("(min-width: 1100px)").matches)
    && !connection?.saveData && (connection?.effectiveType ?? "4g") === "4g";
  const clip = liveClip({ video: `${ART}${phone ? "trailer-640.mp4" : sharp ? "trailer-hd.mp4" : "trailer.mp4"}`, poster: `${ART}trailer.webp` });
  clip.classList.add("trailer");
  const chip = h("button", { type: "button", class: "trailer-chip", hidden: true });
  const sound = h("button", { type: "button", class: "trailer-sound", title: "Sound: the takes' own sound and the studio's clicks, remembered in this browser",
    "aria-label": "Sound: the takes' own sound and the studio's clicks" });
  const paintSound = () => { // the pill shows the studio's choice, whether or not this room is on screen
    const on = soundOn();
    sound.setAttribute("aria-pressed", String(on));
    sound.replaceChildren(icon(on ? "volume-2" : "volume-x", "sm"), h("span", { class: "label-text" }, on ? "Sound on" : "Sound"));
  };
  paintSound();
  const reelList = h("ol", { class: "screen-reel", "aria-label": "In this trailer" });
  const frame = h("div", { class: "screen-frame" }, clip, chip, sound);
  const el = h("figure", { class: "lobby-screen" }, frame, reelList, h("figcaption", { class: "screen-billing billing" }, billing));

  let reel = [];
  let shown = null;
  let raf = 0;
  const play = () => {
    if (!clip.getAttribute("src")) clip.src = clip.dataset.src; // a click is the person's own choice, even under reduced motion
    claimSlot(clip, { pin: !clip.muted }); // an audible trailer is not a loop another may take the decoder from
    clip.play().catch(() => {});
  };
  const paintReel = () => {
    const { index, through } = reelAt(reel, clip.currentTime);
    reelList.querySelectorAll("button").forEach((b, i) => b.style.setProperty("--through", i === index ? through.toFixed(3) : i < index ? "1" : "0"));
    return index;
  };
  const tick = () => {
    raf = 0;
    if (clip.paused || document.hidden) return;
    paintReel();
    raf = requestAnimationFrame(tick);
  };
  clip.addEventListener("play", () => { raf ||= requestAnimationFrame(tick); });
  // a trailer that is heard keeps its decoder however it came to play or to be heard (the wall's watcher starting it, a press unmuting it)
  const keep = () => { if (!clip.muted && !clip.paused) claimSlot(clip, { pin: true }); };
  clip.addEventListener("play", keep);
  clip.addEventListener("volumechange", keep);
  clip.addEventListener("timeupdate", () => {
    const index = paintReel();
    const s = reel[index] ?? null;
    if (s === shown) return;
    shown = s;
    chip.hidden = !s;
    printKeykode(frame, s ? { id: s.take } : null, { full: true }); // the cut's own serial, printed up the frame's edge as the trailer cuts
    chip.replaceChildren(...(s ? [h("span", null, s.label), icon("chevron-right", "sm")] : []));
    chip.title = s ? `Open this take: ${s.label}` : "";
  });
  globalThis.fetch?.(`${ART}trailer.json`).then((r) => (r.ok ? r.json() : null)).then((d) => {
    reel = trailerReel(d?.segments ?? []);
    reelList.replaceChildren(...reel.map((s) => h("li", { style: `--share:${s.share.toFixed(4)}` },
      h("button", { type: "button", class: "reel-cut", "aria-label": `Play from ${s.label}`, title: s.label,
        onclick: () => { clip.currentTime = s.start + 0.01; play(); } },
      h("span", { class: "reel-fill", "aria-hidden": "true" })))));
    paintReel();
  }).catch(() => {});

  const open = (e) => {
    const s = reel[reelAt(reel, clip.currentTime).index];
    if (!s) return;
    e.preventDefault();
    history.pushState(null, "", `#/takes/${s.take}`); // Back returns to the Lobby
    ui.openTake(s.take);
  };
  chip.addEventListener("click", open);
  clip.addEventListener("click", open);
  // a remembered "on": a browser keeps the trailer silent until the person has pressed or typed on the page, so the first
  // press or key on the Lobby unmutes it (a touch counts as it lifts; the pill and the presses in another room do not)
  let armed = null;
  const disarm = () => { armed?.abort(); armed = null; };
  const arm = () => {
    if (armed) return;
    armed = new AbortController();
    const first = (e) => {
      if ((e.type === "pointerdown" && e.pointerType !== "mouse") || e.key === "Escape") return;
      if (e.target?.closest?.(".trailer-sound") || el.closest("[hidden]")) return;
      disarm();
      if (soundOn()) clip.muted = false;
    };
    for (const type of ["pointerdown", "pointerup", "keydown"]) document.addEventListener(type, first, { capture: true, signal: armed.signal });
  };
  const hear = () => { clip.muted = false; play(); }; // play() pins a trailer that is heard
  const unpin = () => { freeSlot(clip); if (!clip.paused) claimSlot(clip); }; // muted again: an ordinary loop, no pin
  sound.addEventListener("click", () => {
    disarm(); // the pill is the person's own choice: no first press is waited for
    setSound(!soundOn());
    paintSound();
    if (soundOn()) { cue("tick"); hear(); } else { clip.muted = true; unpin(); } // the document's tick for this press came before the switch was on
  });
  if (soundOn()) arm();

  // the first visit of a session: the masking parts, then the picture is there (never under reduced motion)
  if (!holdStill() && !seenThisVisit()) {
    frame.append(h("span", { class: "screen-mask", "aria-hidden": "true" }));
    markSeen();
    setTimeout(() => frame.querySelector(".screen-mask")?.remove(), 1500);
  }
  // resolved at the trailer's first frame, after 2.5 s, or at once when motion is held
  const ready = new Promise((resolve) => {
    if (holdStill()) { resolve(); return; }
    let timer = 0;
    const done = () => { clearTimeout(timer); clip.removeEventListener?.("loadeddata", done); clip.removeEventListener?.("playing", done); resolve(); };
    clip.addEventListener("loadeddata", done);
    clip.addEventListener("playing", done);
    timer = setTimeout(done, 2500);
    timer.unref?.(); // Node's timer only: the tests' fake screens must not keep the process alive
  });
  return {
    el,
    ready,
    // the room was left: the trailer is silent again, and the studio's choice stands (the pill still reads it)
    stop: () => {
      clip.muted = true;
      unpin();
      cancelAnimationFrame(raf);
      raf = 0;
    },
    // the room was entered again by a click: sound on is heard at once when the browser allows it, else after the first press
    wake: () => { if (soundOn()) { if (activated()) { disarm(); clip.muted = false; } else arm(); } },
  };
}
