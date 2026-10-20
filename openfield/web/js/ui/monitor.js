// The Monitor: the largest thing on screen. It plays a take, shows a render in progress with its steps,
// asks for approval of the stills, and says plainly when something failed.

import { timecode, ago } from "../lib/format.js";
import { emptyLive } from "../lib/live.js";
import { overall, formatScore } from "../lib/identity.js";
import { clock, fileOf, focusTake, monitorMode, railStates, runDetail, stageList, stepName, titleOf } from "../lib/stages.js";
import { h, icon, setText } from "./dom.js";
import { pill } from "./controls.js";
import { loadTake } from "./actions.js";

const reduced = () => globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
const KIND = { direct: "Direct", reshoot: "Re-shoot", export: "Export", portrait: "Character" };

export function identityPill(identity) {
  const o = overall(identity);
  if (o.status === "pass") return pill(`Same person ${formatScore(o.score)}`, "green");
  if (o.status === "drift") return pill(`Drifted ${formatScore(o.score)}`, "amber");
  return null;
}

export function createMonitor(ctx) {
  const { api, store, forms, controller, ui, scope, empty } = ctx;
  const kinds = scope === "reshoot" ? ["reshoot"] : ["direct"];
  const title = h("h2", { class: "monitor-title" });
  const pills = h("div", { class: "pills" });
  const labelled = (name, text, tone, title) => h("button", { type: "button", class: `btn ${tone} sm`, "aria-label": text, title: title ?? text }, icon(name, "sm"), h("span", { class: "btn-label" }, text));
  const recreateBtn = labelled("circle-play", "Recreate (replay)", "secondary", "Plays back the recorded run. Nothing is rendered.");
  const useBtn = labelled("undo-2", "Use settings", "ghost", "Put this take's settings back in the form");
  const detailsBtn = labelled("shield-check", "Receipt", "ghost", "How this take was made: identity, open-weights audit, receipt");
  const head = h("div", { class: "monitor-head" }, title, pills, h("span", { class: "grow" }), recreateBtn, useBtn, detailsBtn);
  const screen = h("div", { class: "screen" });
  const transport = h("div", { class: "transport", hidden: true });
  const el = h("section", { class: "monitor", "aria-label": "Monitor" }, head, h("div", { class: "screen-wrap" }, screen), transport);

  let shown = { key: null, tick: null };
  let player = null; // { video, before? } while a finished take is on screen
  let focus = { take: null, recorded: false };
  const rerolls = new Set();

  // -- transport ---------------------------------------------------------------------------------
  const playBtn = h("button", { type: "button", class: "btn ghost icon-only", "aria-label": "Play" }, icon("play"));
  const cur = h("span", { class: "tc num" }, "00:00:00:00");
  const scrub = h("input", { type: "range", class: "range scrub", min: 0, max: 1000, step: 1, value: 0, "aria-label": "Position" });
  const dur = h("span", { class: "tc num dim" }, "00:00:00:00");
  const muteBtn = h("button", { type: "button", class: "btn ghost icon-only", "aria-label": "Sound" }, icon("volume-2"));
  const loopBtn = h("button", { type: "button", class: "btn ghost icon-only", "aria-label": "Loop", "aria-pressed": "false" }, icon("repeat"));
  const fsBtn = h("button", { type: "button", class: "btn ghost icon-only", "aria-label": "Full screen" }, icon("maximize"));
  transport.append(playBtn, cur, scrub, dur, muteBtn, loopBtn, fsBtn);

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
    setText(cur, timecode(video.currentTime));
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
    if (e.key === " ") { e.preventDefault(); toggle(); }
    else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      const dir = e.key === "ArrowRight" ? 1 : -1;
      seek(video.currentTime + dir * (video.paused ? 1 / 24 : 1));
    } else if (e.key === "m") muteBtn.click();
    else if (e.key === "f") fsBtn.click();
  });

  // -- finished take -----------------------------------------------------------------------------
  function videoEl(take, { src, poster, autoplay }) {
    const video = h("video", { class: "player", playsinline: true, preload: "metadata", poster: poster ?? null, "aria-label": take.label });
    video.src = src;
    const bind = () => { if (!raf) raf = requestAnimationFrame(frame); paintTransport(); };
    for (const event of ["play", "pause", "ended", "seeked", "loadedmetadata", "volumechange", "timeupdate"]) video.addEventListener(event, bind);
    video.addEventListener("loadedmetadata", () => {
      screen.style.setProperty("--aw", video.videoWidth || 16);
      screen.style.setProperty("--ah", video.videoHeight || 9);
    });
    video.addEventListener("click", toggle);
    if (autoplay && !reduced()) { video.muted = true; video.loop = true; video.play().catch(() => {}); }
    return video;
  }

  function buildReady(take, recorded) {
    const file = fileOf(take, "video") ?? "take.mp4";
    const posterFile = fileOf(take, "poster");
    const video = videoEl(take, { src: api.media(take, file), poster: posterFile ? api.media(take, posterFile) : null, autoplay: recorded });
    player = { video };
    const nodes = [video, h("button", { type: "button", class: "big-play", "aria-label": "Play", onclick: toggle }, icon("play"))];
    if (take.kind === "reshoot") {
      const before = h("video", { class: "player before", muted: true, playsinline: true, preload: "auto", "aria-hidden": "true", loop: true, poster: api.media(take, "inputs/source_poster.png") });
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
        screen.style.setProperty("--split", `${p}%`);
        handle.setAttribute("aria-valuenow", String(Math.round(p)));
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
    const bar = h("div", { class: "bar" }, h("span"));
    const steps = h("ol", { class: "steps" }, ...list.map((s) => h("li", { "data-step": s.id }, h("span", { class: "mark" }), h("span", { class: "step-name" }, s.name))));
    const note = h("p", { class: "run-note" });
    const preview = h("img", { class: "run-preview", alt: "", hidden: true });
    preview.addEventListener("error", () => { preview.hidden = true; });
    const cancel = h("button", { type: "button", class: "btn secondary sm" }, icon("square", "sm"), "Cancel");
    cancel.addEventListener("click", () => controller.cancel(take.id));
    const shownStills = h("div", { class: "run-stills", hidden: true });
    const core = h("div", { class: "run-core" }, name, detail, bar, h("div", { class: "run-meta" }, h("span", null, elapsedLabel, elapsed), cancel), note);
    const nodes = [preview, core, shownStills, steps];
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
      setText(elapsed, clock((Date.now() - Date.parse(t.created_at)) / 1000));
      [...steps.children].forEach((li, i) => li.setAttribute("data-state", states[i]));
      const fraction = live.steps ? live.runValue ?? live.step / live.steps : null;
      bar.classList.toggle("indeterminate", fraction == null);
      bar.firstChild.style.setProperty("--p", fraction == null ? "0" : String(Math.min(1, fraction)));
      note.hidden = !t.replay;
      setText(note, t.replay ? "Replaying events recorded on a real render. Nothing is rendering now." : "");
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
    const names = (i) => (i === 0 ? "Hero still" : `Anchor ${i}`);
    const cards = anchors.map((a) => {
      const reportKey = a.index === 0 ? "hero" : `anchor_${a.index}`;
      const id = (take.identity ?? {})[reportKey];
      const o = id ? overall({ x: id }) : null;
      const check = h("input", { type: "checkbox", id: `rr-${a.index}` });
      check.addEventListener("change", () => { check.checked ? rerolls.add(a.index) : rerolls.delete(a.index); paint(); });
      return h("figure", { class: "still" }, h("img", { src: api.media(take, a.file), alt: `${names(a.index)} for approval` }),
        h("figcaption", null, h("span", null, names(a.index)), o && (o.status === "pass" || o.status === "drift") ? pill(`${formatScore(o.score)} ${o.status === "pass" ? "same" : "drifted"}`, o.status === "pass" ? "green" : "amber") : null),
        h("label", { class: "reroll", for: `rr-${a.index}` }, check, "Try again"));
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
    const nodes = [h("div", { class: "approve" }, h("div", { class: "approve-copy" }, h("h3", null, "Check the stills before the video renders"),
      h("p", null, "Stills are cheap; the video is not. These set the first and last frame of the shot. Pick any to redo, or approve to shoot.")),
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
        h("div", { class: "actions" }, retry, remove))],
      tick: () => {},
    };
  }

  function buildEmpty() {
    return { nodes: [empty(ctx)], tick: () => {} };
  }

  // -- put it together ---------------------------------------------------------------------------
  function show(key, build) {
    if (shown.key !== key) {
      if (player) { player.video.pause(); player.before?.pause(); }
      player = null;
      screen.className = "screen";
      screen.removeAttribute("style");
      const built = build();
      screen.replaceChildren(...built.nodes);
      shown = { key, tick: built.tick };
    }
    shown.tick?.();
  }

  function update() {
    const state = store.get();
    focus = focusTake(state, kinds);
    const { take, recorded } = focus;
    const mode = monitorMode(take);
    screen.dataset.mode = mode;
    transport.hidden = mode !== "ready";
    useBtn.hidden = !take || !["direct", "reshoot"].includes(take.kind);
    detailsBtn.hidden = mode !== "ready";
    const original = take && state.recorded.find((r) => r.id === (take.replay_of ?? take.id));
    recreateBtn.hidden = !(scope === "reshoot" && mode === "ready" && original && state.status?.backend?.locked); // Direct's prompt bar carries it
    recreateBtn.dataset.id = original?.id ?? "";
    pills.replaceChildren();
    head.hidden = !take;
    if (!take) return show(`empty|${scope}|${forms.get().reshoot?.clip?.name ?? ""}`, buildEmpty);
    setText(title, titleOf(take));
    title.title = titleOf(take);
    pills.append(pill(KIND[take.kind] ?? take.kind));
    const moveLabel = take.kind === "direct" ? state.moves?.moves.find((m) => m.id === take.recipe?.rig?.movement)?.label : null;
    if (moveLabel) pills.append(pill(moveLabel));
    if (take.replay) pills.append(Object.assign(pill("Replay", "amber"), { title: "A recorded run played back. Nothing was rendered just now." }));
    else if (recorded) pills.append(Object.assign(pill("Recorded take", "accent"), { title: "A real render, recorded with its receipt." }));
    const idp = mode === "ready" ? identityPill(take.identity) : null;
    if (idp) pills.append(idp);
    if (take.replay) pills.append(h("span", { class: "hint" }, "a recording played back"));
    else if (take.created_at && !recorded) pills.append(h("span", { class: "hint" }, ago(take.created_at)));

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
  forms.subscribe((_, changed) => changed.includes("reshoot") && scope === "reshoot" && !focus.take && update());
  setInterval(() => { if (shown.key?.startsWith("run|") && el.offsetParent) shown.tick(); }, 1000);
  update();
  return { el, update, current: () => focus };
}
