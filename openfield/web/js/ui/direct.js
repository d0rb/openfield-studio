// The Direct station's form: the prompt bar with its plan line and Shoot button, and the settings dock.

import { ANGLE_DEFAULT, DELIVERY_DEFAULT, IMAGE_MB, IMAGE_TYPES, LIMITS, QUALITY_DEFAULT, actionMax, actionNote, describeAngle, describeDialogue, describeEffect, describeQuality, effectKind, estimateLine, estimatePlan, fromImage, matchesRecording, onePass, optionLabel, planSummary, requestBody, toImageForm, validate } from "../lib/direct.js";
import { describeMove } from "../lib/movepad.js";
import { dropZone, field, fileChip, segmented, section, selectField, sliderField, switchRow, textField } from "./controls.js";
import { createMovePad } from "./movepad.js";
import { debounce, fill, h, icon, setText } from "./dom.js";
import { focusTake, monitorMode } from "../lib/stages.js";

/** While the station's take waits for approval or renders, the shot card's button steps back to grey: the wall holds
 * the one orange action then (Approve and shoot), or none. It stays a working button. */
export function quietWhileBusy(button, state, kinds) {
  const mode = monitorMode(focusTake(state, kinds).take);
  button.classList.toggle("is-quiet", mode === "running" || mode === "approval");
}

const KEYS = (e) => (e.ctrlKey || e.metaKey) && e.key === "Enter";
const SHORTCUT = /Mac|iPhone|iPad/.test(globalThis.navigator?.platform ?? "") ? "⌘ Return" : "Ctrl+Enter";

/** Update the Direct form: forms.direct is replaced, never edited in place. */
export const setDirect = (forms, patch) => forms.set((s) => ({ direct: { ...s.direct, ...patch } }));
export const setRig = (forms, patch) => forms.set((s) => ({ direct: { ...s.direct, rig: { ...s.direct.rig, ...patch } } }));

export function castNameOf(store, castId) {
  return castId ? store.get().cast.find((c) => c.id === castId)?.name ?? null : null;
}

/** What the Shoot button should do right now. */
export function shootState({ store, forms }) {
  const { status, moves, recorded } = store.get();
  const state = forms.get().direct;
  if (!state || !moves) return { kind: "loading" };
  const locked = Boolean(status?.backend?.locked);
  const problems = validate(state, moves);
  if (locked) {
    const match = recorded.find((r) => matchesRecording(state, r, castNameOf(store, state.castId), moves));
    return match ? { kind: "recreate", recorded: match, problems } : { kind: "locked", problems, why: fromImage(state) ? "image" : "recipe" };
  }
  return { kind: problems.length ? "invalid" : "ready", problems };
}

export function createPrompt({ forms, store, controller, ui, api }) {
  const subject = textField({
    id: "subject", multiline: true, rows: 1, grow: 132, maxlength: LIMITS.subject[1],
    placeholder: "Describe the shot: who or what is in it, where, and what happens.",
    onInput: (v) => setDirect(forms, { subject: v }),
  });
  subject.el.classList.add("prompt-text");
  subject.el.setAttribute("aria-label", "Describe the shot");
  // what happens: only the video prompt carries it
  const action = textField({ id: "action", multiline: true, rows: 1, grow: 72, maxlength: LIMITS.action[1], placeholder: "He draws the katana and raises the blade.", onInput: (v) => setDirect(forms, { action: v }) });
  action.el.classList.add("prompt-text");
  const actionField = field("What happens", action.el, { id: "action" });
  actionField.el.classList.add("prompt-action");
  const plan = h("p", { class: "plan", id: "plan-line" });
  const shoot = h("button", { type: "button", class: "btn primary lg", "aria-describedby": "plan-line" });
  const el = h("div", { class: "prompt" }, h("div", { class: "prompt-fields" }, subject.el, actionField.el), shoot); // the plan line lives in the monitor head (see shell.js)
  let busy = false;
  // the measured time for a shot of this shape on this backend: asked for after the form settles, never guessed
  let estimate = null;
  let estimateKey = "";
  // the shape of the shot the server measures: a transformation adds a still and changes the template, so it is part of it
  const estimateParams = (d) => ({ quality: d.quality ?? QUALITY_DEFAULT, movement: d.rig.movement, duration_seconds: d.rig.duration_seconds, prompt_only: d.quick, orientation: d.orientation, source: fromImage(d), effect: d.rig.effect ?? "none", angle: d.rig.angle ?? ANGLE_DEFAULT });
  const askEstimate = debounce(async () => {
    const state = forms.get().direct;
    const locked = Boolean(store.get().status?.backend?.locked);
    if (!state || locked || !api?.estimate) { estimate = null; estimateKey = ""; paint(); return; }
    // a shape the form already refuses (an action, line or effect on a move played backwards) is not sent: the server would
    // say the same with a 422, and the plan line already says it
    const moves = store.get().moves;
    if (moves?.moves.find((m) => m.id === state.rig.movement)?.reversed && validate(state, moves).some((p) => ["action", "line", "effect"].includes(p.field))) {
      estimate = null; estimateKey = ""; paint(); return;
    }
    const params = estimateParams(state);
    const key = JSON.stringify(params);
    if (key === estimateKey) return;
    try {
      const answer = await api.estimate(params);
      const now = forms.get().direct;
      if (JSON.stringify(params) === JSON.stringify(estimateParams(now))) {
        estimate = answer;
        estimateKey = key;
        paint();
      }
    } catch {
      estimate = null; // the plan line simply shows no time
    }
  }, 350);

  async function go() {
    const s = shootState({ store, forms });
    if (busy || !["ready", "recreate"].includes(s.kind)) return;
    busy = true;
    paint();
    try {
      const state = forms.get().direct;
      if (s.kind === "recreate") await controller.recreate(s.recorded.id);
      else if (fromImage(state)) await controller.startDirectFromImage(toImageForm(state));
      else await controller.startDirect(requestBody(state));
    } finally {
      busy = false;
      paint();
    }
  }
  shoot.addEventListener("click", go);
  for (const box of [subject.el, action.el]) box.addEventListener("keydown", (e) => KEYS(e) && (e.preventDefault(), go()));
  ui.shoot = go;

  function paint() {
    const { moves } = store.get();
    const state = forms.get().direct;
    if (!state || !moves) return;
    subject.set(state.subject);
    action.set(state.action ?? "");
    action.el.maxLength = actionMax(moves);
    const s = shootState({ store, forms });
    actionField.setError(s.problems?.find((p) => p.field === "action")?.message);
    const move = moves.moves.find((m) => m.id === state.rig.movement);
    const estimate = move ? estimatePlan(move, state.rig.duration_seconds, state.quick, { effectKind: effectKind(moves, state.rig.effect), singlePass: onePass(state, moves) }) : null;
    const parts = [];
    if (move) parts.push(h("b", null, move.label), describeMove(move, { quick: state.quick }).modeLabel);
    const fx = describeEffect(moves, state.rig.effect);
    if (fx) parts.push(fx.kind === "keyframed" ? `${fx.label} (end state)` : fx.label);
    const angled = describeAngle(moves, state.rig.angle);
    if (angled) parts.push(`from ${angled.replace(/ · /g, ", ").toLowerCase()}`);
    if (estimate) {
      parts.push(angled ? `${planSummary(estimate)} + 1 angled still` : planSummary(estimate));
      if (estimate.total_seconds !== state.rig.duration_seconds) parts.push(`${state.rig.duration_seconds} s asked`);
    }
    if (state.quality && state.quality !== QUALITY_DEFAULT) parts.push(describeQuality(moves, state.quality)?.label ?? state.quality);
    const measured = s.kind === "locked" || s.kind === "recreate" ? null : estimateLine(estimateFor());
    if (measured) parts.push(h("span", { class: "measured" }, measured));
    let line = h("span", null, parts.flatMap((p, i) => (i ? [h("span", { class: "sep" }, "·"), p] : [p])));
    const subjectProblem = s.problems?.find((p) => p.field === "subject");
    if (s.kind === "locked") {
      const [short, full] = s.why === "image"
        ? ["Replay cannot start from your image.", "Connect a backend to start from an image."]
        : ["Recorded takes only.", "Recorded takes only. Connect a backend to render."];
      line = h("span", { class: "plan-note", title: full }, icon("lock", "sm"), short);
    }
    else if (subjectProblem && state.subject.trim()) line = h("span", { class: "plan-note" }, icon("circle-alert", "sm"), subjectProblem.message);
    const note = actionNote(state, moves);
    const nodes = [line, note && h("span", { class: "plan-note quiet", title: note }, note)].filter(Boolean);
    if (plan.innerHTML !== nodes.map((n) => n.outerHTML).join("")) plan.replaceChildren(...nodes);

    const labels = { recreate: ["circle-play", "Recreate (replay)"], locked: ["lock", "Needs a backend"], loading: ["clapperboard", "Shoot"] };
    const [name, text] = labels[s.kind] ?? ["clapperboard", "Shoot"];
    shoot.disabled = !["ready", "recreate"].includes(s.kind);
    const hint = s.kind === "recreate" ? "Plays the recorded take." : s.kind === "locked" ? "Recorded takes only. Connect a backend to render." : !state.subject.trim() ? "Describe the shot to begin" : "Shoot";
    shoot.title = ["ready", "recreate"].includes(s.kind) ? `${hint} (${SHORTCUT})` : hint; // the shortcut lives in the tooltip, not on the strip of orange
    shoot.setAttribute("aria-busy", String(busy));
    const key = `${name}|${text}|${busy}`;
    if (shoot.dataset.key !== key) {
      shoot.dataset.key = key;
      fill(shoot, icon(name), h("span", null, busy ? "Starting…" : text));
    }
  }

  const estimateFor = () => estimate;
  forms.subscribe(paint);
  forms.subscribe(askEstimate);
  store.subscribe((_, changed) => changed.some((k) => ["moves", "status", "recorded", "cast"].includes(k)) && paint());
  store.subscribe((state, changed) => changed.some((k) => ["takes", "selected", "recorded"].includes(k)) && quietWhileBusy(shoot, state, ["direct"]));
  store.subscribe((_, changed) => { if (changed.includes("status")) { estimateKey = ""; askEstimate(); } });
  store.subscribe((_, changed) => { if (changed.includes("takes") && store.get().takes.some((t) => t.status === "succeeded")) { estimateKey = ""; askEstimate(); } });
  paint();
  askEstimate();
  return { el, plan, focus: () => subject.el.focus() };
}

export function createDirectDock({ forms, store, api, playhead }) {
  const el = h("div", { class: "dock-pane", "data-pane": "settings" });
  const bound = [];
  const bind = (control, read) => (bound.push(() => control.set(read(forms.get().direct))), control);
  const errors = {};

  function build(catalog) {
    const opts = (key) => catalog.options[key].map((value) => ({ value, label: optionLabel(value) }));
    const withLabel = (label, ctl, extra) => {
      const f = field(label, ctl.el, { id: ctl.id, ...extra });
      return f;
    };

    const pad = createMovePad({ forms, store, api, playhead });
    const moveSection = section("Camera move", pad.el);

    const sensor = bind(selectField({ id: "sensor", options: opts("sensor"), value: forms.get().direct.rig.sensor, onChange: (v) => setRig(forms, { sensor: v }) }), (d) => d.rig.sensor);
    const lens = bind(selectField({ id: "lens", options: opts("lens"), value: forms.get().direct.rig.lens, onChange: (v) => setRig(forms, { lens: v }) }), (d) => d.rig.lens);
    const lighting = bind(selectField({ id: "lighting", options: opts("lighting"), value: forms.get().direct.rig.lighting, onChange: (v) => setRig(forms, { lighting: v }) }), (d) => d.rig.lighting);
    const aperture = bind(segmented({ label: "Aperture", options: opts("aperture"), value: forms.get().direct.rig.aperture, onChange: (v) => setRig(forms, { aperture: v }) }), (d) => d.rig.aperture);
    // a colour grade: one phrase in the still's and the shot's look sentence, a prompt word like the lens
    const gradeOptions = (catalog.options.grade ?? ["none"]).map((value) => ({ value, label: value === "none" ? "None" : optionLabel(value) }));
    const grade = bind(selectField({ id: "grade", options: gradeOptions, value: forms.get().direct.rig.grade ?? "none", onChange: (v) => setRig(forms, { grade: v }) }), (d) => d.rig.grade ?? "none");
    const look = section("Look", h("div", { class: "stack" },
      withLabel("Camera", sensor).el, withLabel("Lens", lens).el, withLabel("Lighting", lighting).el,
      field("Aperture", aperture.el).el, withLabel("Grade", grade).el), { open: false });

    const [fMin, fMax] = catalog.limits.focal_length_mm;
    const [dMin, dMax] = catalog.limits.duration_seconds;
    const focal = bind(sliderField({ id: "focal", label: "Focal length", min: fMin, max: fMax, value: forms.get().direct.rig.focal_length_mm, unit: "mm", onChange: (v) => setRig(forms, { focal_length_mm: v }) }), (d) => d.rig.focal_length_mm);
    const length = bind(sliderField({ id: "length", label: "Length", min: dMin, max: dMax, value: forms.get().direct.rig.duration_seconds, unit: "s", onChange: (v) => setRig(forms, { duration_seconds: v }) }), (d) => d.rig.duration_seconds);
    const speed = bind(segmented({ label: "Speed", options: opts("speed"), value: forms.get().direct.rig.speed, onChange: (v) => setRig(forms, { speed: v }) }), (d) => d.rig.speed);
    const format = bind(segmented({ label: "Format", options: [{ value: "landscape", label: "16:9" }, { value: "portrait", label: "9:16" }], value: forms.get().direct.orientation, onChange: (v) => setDirect(forms, { orientation: v }) }), (d) => d.orientation);
    errors.focal_length_mm = field("Focal length", focal.el, { id: "focal" });
    errors.duration_seconds = field("Length", length.el, { id: "length" });
    // an effect on the LTX shot: a preset sentence in the prompt, or a transformation (the last still is edited into the
    // end state, approved, and LTX renders the change)
    const effects = catalog.effects ?? [];
    const asOption = (e) => ({ value: e.id, label: e.id === "none" ? "None" : e.label });
    const weather = effects.filter((e) => e.kind === "prompt" && e.id !== "none").map(asOption);
    const transformations = effects.filter((e) => e.kind === "keyframed").map(asOption);
    const effectOptions = transformations.length
      ? [{ value: "none", label: "None" }, { group: "Weather and light", options: weather }, { group: "Transformations", options: transformations }]
      : opts("effect");
    const effect = bind(selectField({ id: "effect", options: effectOptions, value: forms.get().direct.rig.effect ?? "none", onChange: (v) => setRig(forms, { effect: v }) }), (d) => d.rig.effect ?? "none");
    const effectField = field("Effect", effect.el, { id: "effect" });
    errors.effect = effectField;
    const effectHint = h("p", { class: "hint" });
    const paintEffect = () => {
      const fx = describeEffect(catalog, forms.get().direct.rig.effect ?? "none");
      const picked = catalog.moves.find((m) => m.id === forms.get().direct.rig.movement);
      if (picked?.reversed) return setText(effectHint, `${picked.label} is played backwards, so it takes no effect.`);
      setText(effectHint, !fx
        ? "Rain, lightning, time freeze, dust, fog, or a transformation."
        : fx.kind === "keyframed" ? "Keyframed. Approve the end still, then shoot."
          : "A preset sentence added to the shot.");
    };
    forms.subscribe(paintEffect);
    paintEffect();
    // quality: still and video sizes plus still steps, the only things the templates let a tier change honestly
    const tiers = (catalog.quality ?? []).map((q) => ({ value: q.id, label: q.label, title: q.what }));
    const qualityCtl = bind(segmented({ label: "Quality", options: tiers.length ? tiers : [{ value: "standard", label: "Standard" }], value: forms.get().direct.quality ?? QUALITY_DEFAULT, onChange: (v) => setDirect(forms, { quality: v }) }), (d) => d.quality ?? QUALITY_DEFAULT);
    const qualityHint = h("p", { class: "hint" });
    const paintQuality = () => {
      const q = describeQuality(catalog, forms.get().direct.quality ?? QUALITY_DEFAULT);
      setText(qualityHint, q ? `${q.what}.` : "");
    };
    forms.subscribe(paintQuality);
    paintQuality();
    const shot = section("Shot", h("div", { class: "stack" }, errors.focal_length_mm.el, errors.duration_seconds.el, field("Quality", qualityCtl.el).el, qualityHint, field("Speed", speed.el).el, field("Format", format.el).el, effectField.el, effectHint), { open: false });

    const cast = selectField({ id: "cast", options: [{ value: "", label: "No character" }], value: "", onChange: (v) => setDirect(forms, { castId: v || null }) });
    bind(cast, (d) => d.castId ?? "");
    const castHint = h("p", { class: "hint" });
    // the hero still: rendered from the text, or the person's own image (the anchors are edited from it either way)
    const revoke = (url) => url && URL.revokeObjectURL(url);
    const pickSource = (file) => { revoke(forms.get().direct.sourcePreview); setDirect(forms, { sourceFile: file, sourcePreview: URL.createObjectURL(file) }); };
    const dropSource = () => { revoke(forms.get().direct.sourcePreview); setDirect(forms, { sourceFile: null, sourcePreview: null }); };
    const heroMode = bind(segmented({ label: "Start from", options: [{ value: "prompt", label: "Prompt" }, { value: "image", label: "My image" }], value: forms.get().direct.heroMode ?? "prompt", onChange: (v) => setDirect(forms, { heroMode: v }) }), (d) => d.heroMode ?? "prompt");
    const sourceSlot = h("div", { class: "slot" });
    const sourceZone = dropZone({ accept: IMAGE_TYPES.join(","), label: "Add your image", hint: `${IMAGE_TYPES.join(", ")} up to ${IMAGE_MB} MB. Becomes the first frame (the last, on a move played backwards).`, onFile: pickSource });
    const sourceHint = h("p", { class: "hint" });
    const sourcePane = h("div", { class: "stack", hidden: true }, sourceSlot, h("p", { class: "hint" }, "A photo of you, or of someone who agreed to this use."), sourceHint);
    errors.source = field("", sourcePane, {});
    const character = section("Character", h("div", { class: "stack" }, field("Start from", heroMode.el, { id: "hero-mode" }).el, errors.source.el, field("Cast", cast.el, { id: "cast" }).el, castHint), { open: false });
    let sourceSig = "";
    const paintSource = () => {
      const d = forms.get().direct;
      const on = fromImage(d);
      sourcePane.hidden = !on;
      const sig = `${on}|${d.sourceFile?.name ?? ""}|${d.sourceFile?.size ?? ""}|${d.castId ?? ""}`;
      if (sig === sourceSig) return;
      sourceSig = sig;
      sourceSlot.replaceChildren(d.sourceFile ? fileChip(d.sourceFile, d.sourcePreview, "image", dropSource) : sourceZone);
      setText(sourceHint, d.castId ? "Checked against the Cast you picked." : "With no Cast, the result is checked against your photo.");
    };
    forms.subscribe(paintSource);
    paintSource();
    let castSig = "";
    const paintCast = () => {
      const list = store.get().cast;
      const chosen = forms.get().direct.castId;
      const sig = `${list.map((c) => `${c.id}:${c.name}`).join()}|${chosen}`;
      if (sig === castSig) return;
      castSig = sig;
      cast.setOptions([{ value: "", label: list.length ? "No character" : "No characters yet" }, ...list.map((c) => ({ value: c.id, label: c.name }))], chosen ?? "");
      setText(castHint, chosen ? "Face checked against this character's photos." : list.length ? "Pick a character to keep the same face across shots." : "Add a character in Cast to keep one face.");
    };
    store.subscribe((_, changed) => changed.includes("cast") && paintCast());
    forms.subscribe(paintCast);
    paintCast();

    const scoreOptions = (catalog.options.score ?? ["none"]).map((value) => ({ value, label: value === "none" ? "None" : optionLabel(value) }));
    const score = bind(selectField({ id: "score", options: scoreOptions, value: forms.get().direct.rig.score ?? "none", onChange: (v) => setRig(forms, { score: v }) }), (d) => d.rig.score ?? "none");
    const soundscapeOptions = (catalog.options.soundscape ?? ["none"]).map((value) => ({ value, label: value === "none" ? "None" : optionLabel(value) }));
    const soundscape = bind(selectField({ id: "soundscape", options: soundscapeOptions, value: forms.get().direct.rig.soundscape ?? "none", onChange: (v) => setRig(forms, { soundscape: v }) }), (d) => d.rig.soundscape ?? "none");
    const audio = bind(textField({ id: "audio", multiline: true, rows: 2, maxlength: LIMITS.audio, placeholder: "What we hear: waves, a distant bell", onInput: (v) => setDirect(forms, { audio: v }) }), (d) => d.audio);
    const seed = bind(textField({ id: "seed", type: "number", inputmode: "numeric", placeholder: "Random", onInput: (v) => setDirect(forms, { seed: v }) }), (d) => d.seed);
    const dice = h("button", { type: "button", class: "btn secondary icon-only", title: "Pick a random seed", "aria-label": "Pick a random seed" }, icon("dices"));
    dice.addEventListener("click", () => setDirect(forms, { seed: String(Math.floor(Math.random() * LIMITS.seed)) }));
    errors.audio = field("Sound", audio.el, { id: "audio", hint: "Sound is made with the picture." });
    // a spoken line: LTX 2.5 writes the voice with the picture when the prompt quotes it
    const dialogue = describeDialogue(catalog);
    const line = bind(textField({ id: "line", multiline: true, rows: 2, maxlength: dialogue.maxChars, placeholder: "What they say: We leave at first light.", onInput: (v) => setDirect(forms, { line: v }) }), (d) => d.line ?? "");
    const delivery = bind(selectField({ id: "delivery", options: dialogue.deliveries.map((x) => ({ value: x.id, label: x.label })), value: forms.get().direct.delivery ?? DELIVERY_DEFAULT, onChange: (v) => setDirect(forms, { delivery: v }) }), (d) => d.delivery ?? DELIVERY_DEFAULT);
    const language = bind(textField({ id: "language", maxlength: LIMITS.language, placeholder: "English", onInput: (v) => setDirect(forms, { language: v }) }), (d) => d.language ?? "");
    errors.line = field("Line", line.el, { id: "line", hint: "Spoken in the shot, lips and all." });
    errors.delivery = field("Delivery", delivery.el, { id: "delivery" });
    errors.language = field("Language", language.el, { id: "language", hint: "Leave empty for English." });
    errors.seed = field("Seed", h("div", { class: "input-row" }, seed.el, dice), { id: "seed", hint: "Empty for random. Saved in the receipt." });
    const quick = bind(switchRow({ title: "Quick mode", hint: "One still, then the move. Nothing to approve first.", onChange: (v) => setDirect(forms, { quick: v }) }), (d) => d.quick);
    const auto = bind(switchRow({ title: "Skip approval", hint: "Shoot without approving the stills.", onChange: (v) => setDirect(forms, { autoApprove: v }) }), (d) => d.autoApprove);
    // a frozen move (bullet time) is one still circled from the camera as shot: Quick has nothing to drop, and the camera stays put
    const holdFrozen = () => {
      const d = forms.get().direct;
      const frozen = Boolean(catalog.moves.find((m) => m.id === d.rig.movement)?.frozen);
      quick.setDisabled(frozen);
      if (frozen && d.quick) setDirect(forms, { quick: false });
      if (frozen && (d.rig.angle ?? ANGLE_DEFAULT) !== ANGLE_DEFAULT) setRig(forms, { angle: ANGLE_DEFAULT });
    };
    forms.subscribe(holdFrozen);
    holdFrozen();
    const advanced = section("Sound and options", h("div", { class: "stack" },
      withLabel("Score", score, { hint: "Music and room sound, made with the picture." }).el,
      withLabel("Soundscape", soundscape).el,
      errors.audio.el, errors.line.el, errors.delivery.el, errors.language.el, errors.seed.el, quick.el, auto.el), { open: false });

    el.replaceChildren(moveSection.el, shot.el, look.el, character.el, advanced.el); // length and format are what changes between takes
    // every closed section says what it holds, so the dock reads at a glance with only the stage plan open
    const paintMeta = () => {
      const d = forms.get().direct;
      moveSection.setMeta(catalog.moves.find((m) => m.id === d.rig.movement)?.label ?? "");
      const fx = describeEffect(catalog, d.rig.effect) ? ` · ${describeEffect(catalog, d.rig.effect).label}` : "";
      const tier = d.quality && d.quality !== QUALITY_DEFAULT ? ` · ${describeQuality(catalog, d.quality)?.label ?? d.quality}` : "";
      shot.setMeta(`${d.rig.focal_length_mm} mm · ${d.rig.duration_seconds} s · ${optionLabel(d.rig.speed)} · ${d.orientation === "portrait" ? "9:16" : "16:9"}${fx}${tier}`);
      const graded = d.rig.grade && d.rig.grade !== "none" ? ` · ${optionLabel(d.rig.grade)}` : "";
      look.setMeta(`${optionLabel(d.rig.lens)} · ${optionLabel(d.rig.aperture)}${graded}`);
      const who = store.get().cast.find((c) => c.id === d.castId)?.name ?? "No character";
      character.setMeta(fromImage(d) ? `Your image · ${who}` : who);
      const spoken = (d.line ?? "").trim() ? " · A line" : "";
      advanced.setMeta((d.seed === "" || d.seed == null ? "Random seed" : `Seed ${d.seed}`) + spoken);
    };
    forms.subscribe(paintMeta);
    store.subscribe((_, changed) => changed.includes("cast") && paintMeta());
    paintMeta();
  }

  function update() {
    const state = forms.get().direct;
    const catalog = store.get().moves;
    if (!state || !catalog) return;
    if (!el.firstChild || el.firstChild.classList?.contains("skeleton")) build(catalog);
    for (const sync of bound) sync();
    const problems = validate(state, catalog);
    for (const key of ["focal_length_mm", "duration_seconds", "audio", "line", "delivery", "language", "seed", "source", "effect"]) errors[key]?.setError(problems.find((p) => p.field === key)?.message);
  }

  el.append(h("div", { class: "skeleton", style: { height: "120px", margin: "16px" } }));
  forms.subscribe(update);
  store.subscribe((_, changed) => changed.includes("moves") && update());
  update();
  return { el };
}
