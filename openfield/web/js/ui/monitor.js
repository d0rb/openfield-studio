// The Monitor: the largest thing on screen. It plays a take, shows a render in progress with its steps,
// asks for approval of the stills, and says plainly when something failed.

import { timecode, ago } from "../lib/format.js";
import { emptyLive } from "../lib/live.js";
import { GPU_RATE, gpuCost } from "../lib/billing.js";
import { overall, formatScore } from "../lib/identity.js";
import { clock, fileOf, focusTake, monitorMode, railStates, runDetail, stageList, stepName, titleOf } from "../lib/stages.js";
import { h, icon, setText, svg } from "./dom.js";
import { pill, segmented } from "./controls.js";
import { MODES, compareLayout } from "../lib/compare.js";
import { holdStill } from "../lib/motion.js";
import { loadTake } from "./actions.js";
import { createStageView } from "./stageview.js";
import { angleGeometry, describeAngle, describeEffect } from "../lib/direct.js";
import { withAngle } from "../lib/pathview.js";

/** The face check's verdict as a chip. `compact`: the score with its dot only (a tile's bezel has no room for the words),
    the full reading as its tooltip and accessible name. */
export function identityPill(identity, { compact = false } = {}) {
  const o = overall(identity);
  const score = formatScore(o.score);
  const words = o.status === "pass" ? `Same person ${score}` : o.status === "drift" ? `Drifted ${score}` : null;
  if (!words) return null;
  const tone = o.status === "pass" ? "green" : "amber";
  if (!compact) return pill(words, tone);
  const chip = pill(score, tone, { dot: true });
  chip.title = words;
  chip.setAttribute("aria-label", words);
  return chip;
}

export function createMonitor(ctx) {
  const { api, store, forms, controller, ui, scope, empty, playhead } = ctx;
  const kinds = scope === "reshoot" ? ["reshoot"] : ["direct", "transition", "extend", "upscale"]; // a bridge, an extension or an upscale plays beside the shots it comes from
  const title = h("h2", { class: "monitor-title" });
  const pills = h("div", { class: "pills" });
  const labelled = (name, text, tone, title) => h("button", { type: "button", class: `btn ${tone} sm`, "aria-label": text, title: title ?? text }, icon(name, "sm"), h("span", { class: "btn-label" }, text));
  const recreateBtn = labelled("circle-play", "Recreate (replay)", "secondary", "Plays the recorded take.");
  const useBtn = labelled("undo-2", "Use settings", "ghost", "Put this take's settings back in the form");
  const detailsBtn = labelled("shield-check", "Receipt", "ghost", "How this take was made");
  const head = h("div", { class: "monitor-head" }, title, pills, h("span", { class: "grow" }), recreateBtn, useBtn, detailsBtn);
  const screen = h("div", { class: "screen" });
  const transport = h("div", { class: "transport", hidden: true });
  const el = h("section", { class: "monitor", "aria-label": "Monitor" }, head, h("div", { class: "screen-wrap" }, screen), transport);

  let shown = { key: null, tick: null };
  let player = null; // { video, before? } while a finished take is on screen
  let focus = { take: null, recorded: false };
  let lead = null; // Direct hands its plan line here: it reads out over the wall in place of a repeated title
  const rerolls = new Set();

  // -- the wall's on-screen display, and the camera path drawn over the footage ----------------------
  const osdTc = h("span", { class: "osd-tc num", hidden: true }, "00:00:00:00");
  const osdTally = h("span", { class: "osd-tally" });
  let guide916 = null; // null follows the shot's format; the button pins it on or off
  const wantsGuide = () => guide916 ?? (scope === "direct" && forms.get().direct?.orientation === "portrait");
  function guides() {
    const g = svg("svg", { class: "osd-guides", viewBox: "0 0 160 90", preserveAspectRatio: "none", "aria-hidden": "true" });
    g.append(
      svg("rect", { x: 8, y: 4.5, width: 144, height: 81, class: "g-safe" }),
      svg("line", { x1: 76, y1: 45, x2: 84, y2: 45, class: "g-cross" }),
      svg("line", { x1: 80, y1: 41, x2: 80, y2: 49, class: "g-cross" }),
    );
    // the 9:16 crop a vertical export keeps, as two hairlines, when the wall is wider than that
    const aspect = (Number(screen.style.getPropertyValue("--aw")) || 16) / (Number(screen.style.getPropertyValue("--ah")) || 9);
    if (wantsGuide() && aspect > 9 / 16) {
      const w = 160 * (9 / 16) / aspect;
      g.append(svg("rect", { x: (160 - w) / 2, y: 0, width: w, height: 90, class: "g-vert" }));
    }
    return g;
  }
  const guideBtn = h("button", { type: "button", class: "btn ghost sm guide-btn", "aria-label": "Show the 9:16 crop", "aria-pressed": "false", title: "The part of the frame a vertical export keeps" }, icon("smartphone", "sm"), h("span", { class: "num" }, "9:16"));
  function paintGuide() {
    guideBtn.setAttribute("aria-pressed", String(wantsGuide()));
    const old = screen.querySelector(".osd-guides");
    if (old) old.replaceWith(guides());
  }
  guideBtn.addEventListener("click", () => { guide916 = !wantsGuide(); paintGuide(); });
  /** Frame guides, the timecode burn-in (while a take plays) and the tally. Never catches the pointer. */
  function osd({ state, text, tc = false }) {
    osdTally.dataset.state = state;
    setText(osdTally, text);
    osdTc.hidden = !tc;
    setText(osdTc, "00:00:00:00");
    return h("div", { class: "osd", "aria-hidden": "true" }, guides(), osdTc, osdTally);
  }
  /** The move's path pivoted to where the shot starts (an angle), or as planned. */
  const angledPoses = (move, angle) => {
    const g = angleGeometry(store.get().moves, angle);
    return g ? withAngle(move.path, g) : move.path;
  };
  /** The chosen move's stage over the empty wall: the standby picture while a shot is being set up. */
  function pathOverlay(movementId) {
    const move = store.get().moves?.moves.find((m) => m.id === movementId);
    if (!move?.path?.length) return null;
    const { quick, orientation, rig } = forms.get().direct ?? {};
    const view = createStageView(move, { hollow: move.mode !== "keyframed" || Boolean(quick), aspect: orientation === "portrait" ? 9 / 16 : 16 / 9, label: `Planned camera for ${move.label}`, poses: angledPoses(move, rig?.angle) });
    view.el.classList.add("screen-path", "stage-standby");
    return view.el;
  }
  /** Over a finished Direct take: the stage seen from above and to one side, its camera moving with the footage. */
  function stageInset(take) {
    const move = store.get().moves?.moves.find((m) => m.id === take.recipe?.rig?.movement);
    if (!move?.path?.length) return null;
    const view = createStageView(move, {
      dense: true,
      hollow: move.mode !== "keyframed" || Boolean(take.recipe?.prompt_only),
      aspect: take.recipe?.orientation === "portrait" ? 9 / 16 : 16 / 9,
      label: `Planned camera for ${move.label}, moving with the footage`,
      poses: angledPoses(move, take.recipe?.rig?.angle),
    });
    view.el.classList.add("screen-path", "stage-inset");
    return view;
  }

  // -- transport ---------------------------------------------------------------------------------
  const playBtn = h("button", { type: "button", class: "btn ghost icon-only", "aria-label": "Play", title: "Play or pause (Space, K)" }, icon("play"));
  const cur = h("span", { class: "tc num" }, "00:00:00:00");
  const scrub = h("input", { type: "range", class: "range scrub", min: 0, max: 1000, step: 1, value: 0, "aria-label": "Position", title: "Step a frame with the arrow keys, a second with J and L" });
  // the approved stills of a keyframed take, marked where the shot reaches them (still k at k / (count - 1))
  const ticks = h("span", { class: "scrub-ticks", "aria-hidden": "true" });
  const scrubWrap = h("span", { class: "scrub-wrap" }, scrub, ticks);
  function setTicks(count) {
    ticks.replaceChildren(...Array.from({ length: count }, (_, i) => h("i", { style: { left: `calc(5px + (100% - 10px) * ${count > 1 ? i / (count - 1) : 0})` } })));
  }
  const dur = h("span", { class: "tc num dim" }, "00:00:00:00");
  const muteBtn = h("button", { type: "button", class: "btn ghost icon-only", "aria-label": "Sound" }, icon("volume-2"));
  const loopBtn = h("button", { type: "button", class: "btn ghost icon-only", "aria-label": "Loop", "aria-pressed": "false" }, icon("repeat"));
  const fsBtn = h("button", { type: "button", class: "btn ghost icon-only", "aria-label": "Full screen", title: "Full screen (F)" }, icon("maximize"));
  const keysBtn = h("button", { type: "button", class: "btn ghost sm keys-btn", "aria-label": "Keyboard shortcuts", title: "Keyboard shortcuts (?)" }, h("span", { class: "kbd" }, "?"));
  keysBtn.addEventListener("click", () => ui.showKeys?.());

  // -- compare modes: only a finished Re-shoot has a before and an after ---------------------------------
  let compareMode = "wipe";
  let compareSplit = 50;
  let compareShowing = "after";
  let compareParts = null; // { before, handle, tags, after } while a Re-shoot is on the wall
  const compareModes = segmented({
    label: "Compare",
    options: MODES.map((m) => ({ value: m, label: m[0].toUpperCase() + m.slice(1) })),
    value: compareMode,
    onChange: (mode) => { compareMode = mode; applyCompare(); },
  });
  compareModes.el.classList.add("compare-modes");
  compareModes.el.hidden = true;
  /** Apply the current mode to the wall. Safe to call before a Re-shoot is built. */
  function applyCompare() {
    if (!compareParts) return;
    const { before, after, handle, tags } = compareParts;
    const layout = compareLayout(compareMode, { split: compareSplit, showing: compareShowing });
    screen.classList.toggle("is-side", compareMode === "side");
    screen.classList.toggle("is-flip", compareMode === "flip");
    before.style.clipPath = layout.beforeClip;
    before.hidden = !layout.beforeVisible;
    after.hidden = !layout.afterVisible;
    handle.hidden = !layout.handle;
    const beforeTag = tags.children[0];
    const afterTag = tags.children[1];
    beforeTag.hidden = compareMode === "flip" && !layout.beforeVisible;
    afterTag.hidden = compareMode === "flip" && !layout.afterVisible;
  }
  const swapFlip = () => { compareShowing = compareShowing === "before" ? "after" : "before"; applyCompare(); };
  screen.addEventListener("click", (e) => {
    if (!compareParts || compareMode !== "flip" || e.target.closest("button, input, .split-handle")) return;
    swapFlip();
  });

  transport.append(playBtn, cur, scrubWrap, dur, muteBtn, loopBtn, guideBtn, compareModes.el, fsBtn, keysBtn);

  const v = () => player?.video;
  const toggle = () => { const video = v(); if (video) (video.paused ? video.play().catch(() => {}) : video.pause()); };
  const paintTransport = () => {
    const video = v();
    if (!video) return;
    const playing = !video.paused && !video.ended;
    playBtn.replaceChildren(icon(playing ? "pause" : "play"));
    playBtn.setAttribute("aria-label", playing ? "Pause" : "Play");
    muteBtn.replaceChildren(icon(video.muted || video.volume === 0 ? "volume-x" : "volume-2"));
    muteBtn.setAttribute("aria-label", video.muted ? "Unmute" : "Mute");
    loopBtn.setAttribute("aria-pressed", String(video.loop));
    screen.classList.toggle("is-playing", playing);
    const d = Number.isFinite(video.duration) ? video.duration : 0;
    const t = d ? Math.min(1, video.currentTime / d) : 0;
    player.inset?.seek(t);
    [...ticks.children].forEach((tick, i, all) => tick.classList.toggle("lit", all.length > 1 ? t + 1e-3 >= i / (all.length - 1) : true));
    if (scope === "direct") playhead?.set({ t, take: focus.take?.id ?? null, movement: focus.take?.recipe?.rig?.movement ?? null });
    setText(cur, timecode(video.currentTime));
    setText(osdTc, timecode(video.currentTime));
    setText(dur, timecode(d));
    if (document.activeElement !== scrub) scrub.value = d ? Math.round((video.currentTime / d) * 1000) : 0;
    scrub.style.setProperty("--fill", `${scrub.value / 10}%`);
  };
  const seek = (t) => { const video = v(); if (video && Number.isFinite(video.duration)) video.currentTime = Math.min(video.duration, Math.max(0, t)); };
  playBtn.addEventListener("click", toggle);
  scrub.addEventListener("input", () => { const video = v(); if (video?.duration) seek((scrub.value / 1000) * video.duration); paintTransport(); });
  muteBtn.addEventListener("click", () => { const video = v(); if (video) { video.muted = !video.muted; paintTransport(); } });
  loopBtn.addEventListener("click", () => { const video = v(); if (video) { video.loop = !video.loop; paintTransport(); } });
  fsBtn.addEventListener("click", () => v()?.requestFullscreen?.().catch(() => {}));
  let raf = 0;
  const frame = () => { paintTransport(); raf = player && !v().paused ? requestAnimationFrame(frame) : 0; };

  // keyboard: space plays, arrows step by a frame (paused) or a second (playing)
  document.addEventListener("keydown", (e) => {
    if (!v() || !el.offsetParent || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.target.closest?.("input,textarea,select,button,a,[role=radio],[role=switch],[contenteditable]")) return;
    const video = v();
    if (e.key === " " || e.key === "k") { e.preventDefault(); toggle(); }
    else if (e.key === "j" || e.key === "l") seek(video.currentTime + (e.key === "l" ? 1 : -1));
    else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      const dir = e.key === "ArrowRight" ? 1 : -1;
      seek(video.currentTime + dir * (video.paused ? 1 / 24 : 1));
    } else if (e.key === "m") muteBtn.click();
    else if (e.key === "f") fsBtn.click();
    else if (e.key === "x" && compareParts && compareMode === "flip") { e.preventDefault(); swapFlip(); }
  });

  // -- finished take -----------------------------------------------------------------------------
  /** This station's room on screen: a room nobody is looking at fetches nothing and plays nothing. */
  const onScreen = () => store.get().route === scope;

  function videoEl(take, { src, poster, autoplay }) {
    const shown = onScreen();
    // a hidden room fetches nothing, not even the poster (a 4K take's poster is several megabytes): it waits for reveal()
    const video = h("video", { class: "player", playsinline: true, preload: shown ? "metadata" : "none", poster: shown ? poster ?? null : null, "aria-label": take.label });
    if (poster) video.dataset.poster = poster;
    video.src = src;
    const bind = () => { if (!raf) raf = requestAnimationFrame(frame); paintTransport(); };
    for (const event of ["play", "pause", "ended", "seeked", "loadedmetadata", "volumechange", "timeupdate"]) video.addEventListener(event, bind);
    video.addEventListener("loadedmetadata", () => {
      screen.style.setProperty("--aw", video.videoWidth || 16);
      screen.style.setProperty("--ah", video.videoHeight || 9);
    });
    video.addEventListener("click", () => { if (!(compareParts && compareMode === "flip")) toggle(); });
    if (autoplay && shown && !holdStill()) { video.muted = true; video.loop = true; video.play().catch(() => {}); }
    return video;
  }

  /** The room comes on screen: the videos may fetch their metadata now, and the recorded take plays. */
  function reveal() {
    for (const video of [player?.video, player?.before]) {
      if (video && !video.getAttribute("poster") && video.dataset.poster) video.poster = video.dataset.poster;
      if (!video || video.preload === "metadata") continue;
      video.preload = "metadata";
      if (!video.readyState) video.load(); // the browser had not begun fetching while the room was hidden
    }
    const video = player?.video;
    if (!video || !player.autoplay || holdStill()) return;
    video.muted = true;
    video.loop = true;
    video.play().catch(() => {});
  }

  function buildReady(take, recorded) {
    compareParts = null;
    const file = fileOf(take, "video") ?? "take.mp4";
    const posterFile = fileOf(take, "poster");
    const video = videoEl(take, { src: api.media(take, file), poster: posterFile ? api.media(take, posterFile) : null, autoplay: recorded });
    const inset = take.kind === "direct" ? stageInset(take) : null;
    player = { video, inset, autoplay: recorded };
    const moved = store.get().moves?.moves.find((m) => m.id === take.recipe?.rig?.movement);
    setTicks(take.kind === "direct" && moved?.mode === "keyframed" && !take.recipe?.prompt_only ? Math.max(2, moved.anchors ?? 2) : 0);
    const tally = take.replay ? { state: "replay", text: "Replay" } : recorded ? { state: "ready", text: "Recorded" } : { state: "ready", text: "Take" };
    const nodes = [video, inset?.el, h("button", { type: "button", class: "big-play", "aria-label": "Play", onclick: toggle }, icon("play")), osd({ ...tally, tc: true })];
    if (take.kind === "reshoot") {
      const beforePoster = api.media(take, "inputs/source_poster.png");
      const before = h("video", { class: "player before", muted: true, playsinline: true, preload: onScreen() ? "metadata" : "none", "aria-hidden": "true", loop: true, poster: onScreen() ? beforePoster : null });
      before.dataset.poster = beforePoster;
      before.src = `${api.media(take, "inputs/source.mp4")}#t=0.001`;
      before.addEventListener("error", () => { before.remove(); handle.remove(); tags.remove(); }, { once: true });
      const sync = () => { if (Math.abs(before.currentTime - video.currentTime) > 0.08) before.currentTime = video.currentTime; };
      video.addEventListener("play", () => { sync(); before.play().catch(() => {}); });
      video.addEventListener("pause", () => { before.pause(); sync(); });
      video.addEventListener("seeked", sync);
      video.addEventListener("ratechange", () => { before.playbackRate = video.playbackRate; });
      const handle = h("div", { class: "split-handle", role: "slider", tabindex: "0", "aria-label": "Before and after", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": "50" }, icon("chevron-left", "sm"), icon("chevron-right", "sm"));
      const tags = h("div", { class: "split-tags" }, h("span", null, "Before"), h("span", null, "After"));
      const setSplit = (pct) => {
        const p = Math.min(98, Math.max(2, pct));
        compareSplit = p;
        screen.style.setProperty("--split", `${p}%`);
        handle.setAttribute("aria-valuenow", String(Math.round(p)));
        applyCompare();
      };
      setSplit(50);
      const drag = (e) => { const r = screen.getBoundingClientRect(); setSplit(((e.clientX - r.left) / r.width) * 100); };
      handle.addEventListener("pointerdown", (e) => { handle.setPointerCapture(e.pointerId); handle.addEventListener("pointermove", drag); });
      handle.addEventListener("pointerup", () => handle.removeEventListener("pointermove", drag));
      handle.addEventListener("keydown", (e) => {
        const step = { ArrowLeft: -5, ArrowRight: 5, Home: -100, End: 100 }[e.key];
        if (step) { e.preventDefault(); setSplit(Number(handle.getAttribute("aria-valuenow")) + step); }
      });
      player.before = before;
      nodes.splice(1, 0, before, tags, handle);
      screen.classList.add("is-compare");
      compareParts = { before, after: video, handle, tags };
      applyCompare();
    }
    return { nodes, tick: () => {} };
  }

  // -- a render in progress ----------------------------------------------------------------------
  function buildRunning(take) {
    const catalog = store.get().moves;
    const list = stageList(take, catalog);
    const name = h("div", { class: "run-name", role: "status" });
    const detail = h("div", { class: "run-detail" });
    const elapsed = h("span", { class: "num" });
    const elapsedLabel = h("span", null, "Elapsed ");
    // the meter: what this render has spent so far, counting up while it runs. The price every take carries is the one
    // its receipt records when the render ends; this is the card's time at its rate as it goes, and says so.
    const spend = h("span", { class: "run-spend num", hidden: true,
      title: `The card's time so far at about $${GPU_RATE.toFixed(2)} an hour. The take's receipt records what it actually cost.` });
    const bar = h("div", { class: "bar" }, h("span"));
    const steps = h("ol", { class: "steps" }, ...list.map((s) => h("li", { "data-step": s.id }, h("span", { class: "mark" }), h("span", { class: "step-name" }, s.name))));
    const note = h("p", { class: "run-note" });
    const preview = h("img", { class: "run-preview", alt: "", hidden: true });
    preview.addEventListener("error", () => { preview.hidden = true; });
    const cancel = h("button", { type: "button", class: "btn secondary sm" }, icon("square", "sm"), "Cancel");
    cancel.addEventListener("click", () => controller.cancel(take.id));
    const shownStills = h("div", { class: "run-stills", hidden: true });
    const core = h("div", { class: "run-core" }, name, detail, bar, h("div", { class: "run-meta" }, h("span", null, elapsedLabel, elapsed), spend, cancel), note);
    const nodes = [preview, core, shownStills, steps, osd(take.replay ? { state: "replay", text: "Replaying" } : { state: "running", text: "Rendering" })];
    let previewSrc = "";

    const tick = () => {
      const s = store.get();
      const t = s.takes.find((x) => x.id === take.id) ?? take;
      const live = s.live[take.id] ?? emptyLive();
      const states = railStates(list, t, live);
      const active = Math.max(0, states.findIndex((x) => x === "active" || x === "pending"));
      setText(name, t.status === "queued" && !live.stage ? "Queued" : list[active]?.name ?? "Working");
      const said = runDetail(live, t);
      setText(detail, t.replay ? `Recorded: ${said.charAt(0).toLowerCase()}${said.slice(1)}` : said); // a replay reports what happened, not what is happening
      setText(elapsedLabel, t.replay ? "Replaying " : "Elapsed ");
      const running = (Date.now() - Date.parse(t.created_at)) / 1000;
      setText(elapsed, clock(running));
      spend.hidden = Boolean(t.replay) || !(running > 0); // a replay spends nothing: it is a recording
      if (!spend.hidden) setText(spend, gpuCost(running) ?? "");
      [...steps.children].forEach((li, i) => li.setAttribute("data-state", states[i]));
      const fraction = live.steps ? live.runValue ?? live.step / live.steps : null;
      bar.classList.toggle("indeterminate", fraction == null);
      bar.firstChild.style.setProperty("--p", fraction == null ? "0" : String(Math.min(1, fraction)));
      note.hidden = !t.replay;
      setText(note, t.replay ? "Replaying a recorded take." : "");
      cancel.hidden = t.replay;
      if (live.preview) {
        const src = `${api.media(t, `runs/${live.preview.run}/preview.jpg`)}?n=${Date.now() >> 11}`;
        if (src !== previewSrc) { previewSrc = src; preview.src = src; }
        preview.hidden = false;
      } else preview.hidden = true;
      const stills = live.anchorsShown ?? [];
      if (stills.length && shownStills.children.length !== stills.length) {
        shownStills.replaceChildren(...stills.map((a) => h("img", { src: api.media(t, a.file), alt: `Approved still ${a.index + 1}` })));
        shownStills.hidden = false;
      }
    };
    return { nodes, tick };
  }

  // -- waiting for the person ---------------------------------------------------------------------
  function buildApproval(take) {
    const anchors = take.anchors ?? [];
    const row = h("div", { class: "approve-row", "data-orientation": take.recipe?.orientation ?? "landscape", style: { "--n": String(Math.max(1, anchors.length)) } });
    const go = h("button", { type: "button", class: "btn primary" });
    const cancel = h("button", { type: "button", class: "btn ghost" }, "Cancel");
    const own = Boolean(take.recipe?.source_sha256); // the hero is the person's photo: shown, never re-rolled
    // the server names each still's role; older recordings carry only the index (0 = the hero, the rest anchors)
    // what an angled still or an end state was made from: the role is named only with that evidence beside it
    const madeFrom = (a) => (a.role === "angle" ? describeAngle(store.get().moves, take.recipe?.rig?.angle)?.replace(/ · /g, ", ")
      : a.role === "transform" ? describeEffect(store.get().moves, take.recipe?.rig?.effect)?.label : null) ?? null;
    const names = (a) => {
      const made = madeFrom(a);
      if (a.role === "transform" && made) return "End state";
      if (a.role === "angle" && made) return "Angled still";
      return a.index === 0 ? (own ? "Your photo" : "Hero still") : `Anchor ${a.index}`;
    };
    const cards = anchors.map((a, i) => {
      const reportKey = a.role === "transform" ? `transform_${a.index}` : a.role === "angle" ? "angle" : a.index === 0 ? "hero" : `anchor_${a.index}`;
      const id = (take.identity ?? {})[reportKey];
      const o = id ? overall({ x: id }) : null;
      const check = h("input", { type: "checkbox", id: `rr-${a.index}` });
      check.addEventListener("change", () => { check.checked ? rerolls.add(a.index) : rerolls.delete(a.index); paint(); });
      const made = madeFrom(a);
      return h("figure", { class: "still", style: { "--i": String(i) } }, h("img", { src: api.media(take, a.file), alt: `${names(a)} for approval` }),
        h("figcaption", null, h("span", null, names(a)), made ? h("span", { class: "hint" }, made) : null, o && (o.status === "pass" || o.status === "drift") ? pill(`${formatScore(o.score)} ${o.status === "pass" ? "same" : "drifted"}`, o.status === "pass" ? "green" : "amber") : null),
        own && a.index === 0 ? h("span", { class: "hint" }, "Yours, as given") : h("label", { class: "reroll", for: `rr-${a.index}` }, check, "Try again"));
    });
    row.append(...cards);
    const paint = () => {
      const n = rerolls.size;
      go.replaceChildren(icon(n ? "refresh-cw" : "check"), n ? `Re-roll ${n} and review again` : "Approve and shoot");
      go.classList.toggle("secondary", n > 0);
      go.classList.toggle("primary", n === 0);
    };
    go.addEventListener("click", async () => { go.disabled = true; await controller.approve(take.id, [...rerolls]); rerolls.clear(); go.disabled = false; });
    cancel.addEventListener("click", () => controller.cancel(take.id));
    paint();
    const nodes = [h("div", { class: "approve" }, h("div", { class: "approve-copy" }, h("h3", null, "Check the stills"),
      h("p", null, "Redo any of them, or approve to shoot.")),
    row, h("div", { class: "approve-actions" }, go, cancel))];
    return { nodes, tick: () => {} };
  }

  // -- ended without a video -----------------------------------------------------------------------
  function buildFailed(take) {
    const canceled = take.status === "canceled";
    const refused = take.error?.code === "replay_unavailable"; // Replay was asked for a recipe nobody rendered: nothing was attempted
    const message = take.error?.message ?? (canceled ? "You canceled this take before it finished." : "Something went wrong and the take stopped.");
    const retry = h("button", { type: "button", class: "btn secondary" }, icon(refused ? "film" : "undo-2"), refused ? "Go to a recording" : "Edit and try again");
    retry.addEventListener("click", () => {
      const recording = store.get().recorded.find((r) => kinds.includes(r.kind));
      if (refused && recording) controller.select(recording.id);
      else loadTake(ctx, take);
    });
    const remove = h("button", { type: "button", class: "btn ghost quiet-danger" }, icon("trash-2"), "Remove");
    remove.addEventListener("click", () => controller.remove(take.id));
    return {
      nodes: [h("div", { class: "empty fail" }, icon(canceled ? "ban" : "triangle-alert", "lg"), h("h2", null, canceled ? "Canceled" : refused ? "Not in this recording" : "This take did not finish"),
        h("p", null, message), take.error?.code ? h("p", { class: "mono hint" }, take.error.code) : null,
        h("div", { class: "actions" }, retry, remove)), osd(canceled ? { state: "standby", text: "Canceled" } : { state: "failed", text: "Failed" })],
      tick: () => {},
    };
  }

  function buildEmpty() {
    const overlay = scope === "direct" ? pathOverlay(forms.get().direct?.rig?.movement) : null;
    return { nodes: [overlay, empty(ctx), osd({ state: "standby", text: "Standby" })], tick: () => {} };
  }

  // -- put it together ---------------------------------------------------------------------------
  function show(key, build) {
    if (shown.key !== key) {
      // a cut from one finished take to the next keeps the last frame up until the new one is ready: no flash of black (when the
      // page holds still the new poster shows at once instead: nothing plays, so "ready" could be 1.5 s away)
      const outgoing = !holdStill() && player && !compareParts && shown.key?.startsWith("ready|") && key.startsWith("ready|") ? player.video : null;
      if (player) { player.video.pause(); player.before?.pause(); }
      player = null;
      if (scope === "direct") playhead?.set({ t: 0, take: null, movement: null });
      compareParts = null;
      screen.className = "screen";
      screen.removeAttribute("style");
      setTicks(0);
      const built = build();
      screen.replaceChildren(...built.nodes.filter(Boolean)); // a build may leave out the overlay
      shown = { key, tick: built.tick };
      if (outgoing) crossfade(outgoing, player?.video);
    }
    shown.tick?.();
  }

  function crossfade(outgoing, incoming) {
    outgoing.classList.replace("player", "player-out"); // out of every `video.player` query at once
    outgoing.removeAttribute("aria-label");
    screen.append(outgoing);
    let gone = false;
    const drop = () => { outgoing.removeAttribute("src"); outgoing.load(); outgoing.remove(); };
    const leave = () => {
      if (gone) return;
      gone = true;
      if (holdStill()) return drop(); // a cut, not a fade: the old frame goes the moment the new one is ready
      outgoing.classList.add("leaving");
      setTimeout(drop, 260);
    };
    if (incoming && incoming.readyState < 2) incoming.addEventListener("loadeddata", leave, { once: true });
    else leave();
    setTimeout(leave, 1500); // never hold the old frame for long if the new one is slow
  }

  function update() {
    const state = store.get();
    focus = focusTake(state, kinds);
    const { take, recorded } = focus;
    const mode = monitorMode(take);
    screen.dataset.mode = mode;
    transport.hidden = mode !== "ready";
    compareModes.el.hidden = !(take?.kind === "reshoot" && mode === "ready");
    useBtn.hidden = !take || !["direct", "reshoot"].includes(take.kind);
    detailsBtn.hidden = mode !== "ready";
    const original = take && state.recorded.find((r) => r.id === (take.replay_of ?? take.id));
    recreateBtn.hidden = !(scope === "reshoot" && mode === "ready" && original && state.status?.backend?.locked); // Direct's prompt bar carries it
    recreateBtn.dataset.id = original?.id ?? "";
    pills.replaceChildren();
    head.hidden = !take && !lead;
    if (!take) return show(`empty|${scope}|${forms.get().reshoot?.clip?.name ?? ""}|${forms.get().direct?.rig?.movement ?? ""}`, buildEmpty);
    setText(title, titleOf(take));
    title.title = titleOf(take);
    const moveLabel = take.kind === "direct" && !lead ? state.moves?.moves.find((m) => m.id === take.recipe?.rig?.movement)?.label : null;
    if (moveLabel) pills.append(pill(moveLabel));
    if (take.replay) pills.append(Object.assign(pill("Replay", "amber"), { title: "A recorded run, played back." }));
    else if (recorded) pills.append(Object.assign(pill("Recorded take", null, { dot: true }), { title: "A real render, recorded with its receipt." }));
    const idp = mode === "ready" ? identityPill(take.identity) : null;
    if (idp) pills.append(idp);
    if (!lead) { // Direct's head is one line led by the plan: the chips say enough there
      if (take.replay) pills.append(h("span", { class: "hint" }, "a recording played back"));
      else if (take.created_at && !recorded) pills.append(h("span", { class: "hint" }, ago(take.created_at)));
    }

    if (mode === "ready") show(`ready|${take.id}|${fileOf(take, "video")}`, () => buildReady(take, recorded));
    else if (mode === "running") show(`run|${take.id}`, () => buildRunning(take));
    else if (mode === "approval") show(`approve|${take.id}|${(take.anchors ?? []).map((a) => a.file).join()}`, () => buildApproval(take));
    else show(`fail|${take.id}|${take.status}`, () => buildFailed(take));
    paintTransport();
  }

  recreateBtn.addEventListener("click", () => recreateBtn.dataset.id && controller.recreate(recreateBtn.dataset.id));
  useBtn.addEventListener("click", () => focus.take && loadTake(ctx, focus.take));
  detailsBtn.addEventListener("click", () => { ui.focusTake = focus.take; ui.openDock("take"); });

  store.subscribe((_, changed) => changed.some((k) => ["takes", "live", "selected", "recorded", "moves", "status"].includes(k)) && update());
  // a station that is not on screen does not keep playing (or sounding); one that comes on screen starts its take
  store.subscribe((state, changed) => {
    if (!changed.includes("route") || !player) return;
    if (state.route !== scope) { player.video.pause(); player.before?.pause(); }
    else reveal();
  });
  forms.subscribe((_, changed) => changed.includes("reshoot") && scope === "reshoot" && !focus.take && update());
  forms.subscribe((_, changed) => changed.includes("direct") && scope === "direct" && !focus.take && update()); // the path over an empty wall follows the chosen move
  forms.subscribe((_, changed) => changed.includes("direct") && scope === "direct" && paintGuide()); // the 9:16 guide follows the shot's format
  setInterval(() => { if (shown.key?.startsWith("run|") && el.offsetParent) shown.tick(); }, 1000);
  update();
  return { el, update, current: () => focus, lead: (node) => { lead = node; title.hidden = true; head.prepend(node); update(); } };
}
