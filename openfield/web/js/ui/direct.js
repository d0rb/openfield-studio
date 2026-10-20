// The Direct station's form: the prompt bar with its plan line and Shoot button, and the settings dock.

import { LIMITS, estimatePlan, matchesRecording, optionLabel, planSummary, requestBody, validate } from "../lib/direct.js";
import { describeMove } from "../lib/movepad.js";
import { field, segmented, section, selectField, sliderField, switchRow, textField } from "./controls.js";
import { createMovePad } from "./movepad.js";
import { fill, h, icon, setText } from "./dom.js";

const KEYS = (e) => (e.ctrlKey || e.metaKey) && e.key === "Enter";
const SHORTCUT = /Mac|iPhone|iPad/.test(globalThis.navigator?.platform ?? "") ? "⌘ ↵" : "Ctrl ↵";

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
    const match = recorded.find((r) => matchesRecording(state, r, castNameOf(store, state.castId)));
    return match ? { kind: "recreate", recorded: match, problems } : { kind: "locked", problems };
  }
  return { kind: problems.length ? "invalid" : "ready", problems };
}

export function createPrompt({ forms, store, controller, ui }) {
  const subject = textField({
    id: "subject", multiline: true, rows: 1, grow: 132, maxlength: LIMITS.subject[1],
    placeholder: "Describe the shot: who or what is in it, where, and what happens.",
    onInput: (v) => setDirect(forms, { subject: v }),
  });
  subject.el.classList.add("prompt-text");
  subject.el.setAttribute("aria-label", "Describe the shot");
  const plan = h("p", { class: "plan", id: "plan-line" });
  const shoot = h("button", { type: "button", class: "btn primary lg", "aria-describedby": "plan-line" });
  const el = h("div", { class: "prompt" }, subject.el, h("div", { class: "prompt-foot" }, plan, shoot));
  let busy = false;

  async function go() {
    const s = shootState({ store, forms });
    if (busy || !["ready", "recreate"].includes(s.kind)) return;
    busy = true;
    paint();
    try {
      if (s.kind === "recreate") await controller.recreate(s.recorded.id);
      else await controller.startDirect(requestBody(forms.get().direct));
    } finally {
      busy = false;
      paint();
    }
  }
  shoot.addEventListener("click", go);
  subject.el.addEventListener("keydown", (e) => KEYS(e) && (e.preventDefault(), go()));
  ui.shoot = go;

  function paint() {
    const { moves } = store.get();
    const state = forms.get().direct;
    if (!state || !moves) return;
    subject.set(state.subject);
    const s = shootState({ store, forms });
    const move = moves.moves.find((m) => m.id === state.rig.movement);
    const estimate = move ? estimatePlan(move, state.rig.duration_seconds, state.quick) : null;
    const parts = [];
    if (move) parts.push(h("b", null, move.label), describeMove(move, { quick: state.quick }).modeLabel);
    if (estimate) parts.push(planSummary(estimate) + (estimate.total_seconds !== state.rig.duration_seconds ? ` (asked for ${state.rig.duration_seconds} s)` : ""));
    let line = h("span", null, parts.flatMap((p, i) => (i ? [h("span", { class: "sep" }, "·"), p] : [p])));
    const subjectProblem = s.problems?.find((p) => p.field === "subject");
    if (s.kind === "locked") line = h("span", { class: "plan-note" }, icon("lock", "sm"), "This shot was not recorded. Replay can only recreate recorded takes; connect a backend to render new ones.");
    else if (subjectProblem && state.subject.trim()) line = h("span", { class: "plan-note" }, icon("circle-alert", "sm"), subjectProblem.message);
    if (plan.firstChild?.outerHTML !== line.outerHTML) plan.replaceChildren(line);

    const labels = { recreate: ["circle-play", "Recreate (replay)"], locked: ["lock", "Needs a backend"], loading: ["clapperboard", "Shoot"] };
    const [name, text] = labels[s.kind] ?? ["clapperboard", "Shoot"];
    shoot.disabled = !["ready", "recreate"].includes(s.kind);
    shoot.title = s.kind === "recreate" ? "Plays back the recorded run. Nothing is rendered." : s.kind === "locked" ? "Replay can only play back recorded takes" : !state.subject.trim() ? "Describe the shot to begin" : "";
    shoot.setAttribute("aria-busy", String(busy));
    const key = `${name}|${text}|${busy}`;
    if (shoot.dataset.key !== key) {
      shoot.dataset.key = key;
      fill(shoot, icon(name), h("span", null, busy ? "Starting…" : text), ["ready", "recreate"].includes(s.kind) && !busy ? h("span", { class: "kbd" }, SHORTCUT) : null);
    }
  }

  forms.subscribe(paint);
  store.subscribe((_, changed) => changed.some((k) => ["moves", "status", "recorded", "cast"].includes(k)) && paint());
  paint();
  return { el, focus: () => subject.el.focus() };
}

export function createDirectDock({ forms, store }) {
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

    const pad = createMovePad({ forms, store });
    const moveSection = section("Camera move", pad.el);

    const sensor = bind(selectField({ id: "sensor", options: opts("sensor"), value: forms.get().direct.rig.sensor, onChange: (v) => setRig(forms, { sensor: v }) }), (d) => d.rig.sensor);
    const lens = bind(selectField({ id: "lens", options: opts("lens"), value: forms.get().direct.rig.lens, onChange: (v) => setRig(forms, { lens: v }) }), (d) => d.rig.lens);
    const lighting = bind(selectField({ id: "lighting", options: opts("lighting"), value: forms.get().direct.rig.lighting, onChange: (v) => setRig(forms, { lighting: v }) }), (d) => d.rig.lighting);
    const aperture = bind(segmented({ label: "Aperture", options: opts("aperture"), value: forms.get().direct.rig.aperture, onChange: (v) => setRig(forms, { aperture: v }) }), (d) => d.rig.aperture);
    const look = section("Look", h("div", { class: "stack" },
      withLabel("Camera", sensor).el, withLabel("Lens", lens).el, withLabel("Lighting", lighting).el,
      field("Aperture", aperture.el).el), { open: false });

    const [fMin, fMax] = catalog.limits.focal_length_mm;
    const [dMin, dMax] = catalog.limits.duration_seconds;
    const focal = bind(sliderField({ id: "focal", label: "Focal length", min: fMin, max: fMax, value: forms.get().direct.rig.focal_length_mm, unit: "mm", onChange: (v) => setRig(forms, { focal_length_mm: v }) }), (d) => d.rig.focal_length_mm);
    const length = bind(sliderField({ id: "length", label: "Length", min: dMin, max: dMax, value: forms.get().direct.rig.duration_seconds, unit: "s", onChange: (v) => setRig(forms, { duration_seconds: v }) }), (d) => d.rig.duration_seconds);
    const speed = bind(segmented({ label: "Speed", options: opts("speed"), value: forms.get().direct.rig.speed, onChange: (v) => setRig(forms, { speed: v }) }), (d) => d.rig.speed);
    const format = bind(segmented({ label: "Format", options: [{ value: "landscape", label: "16:9" }, { value: "portrait", label: "9:16" }], value: forms.get().direct.orientation, onChange: (v) => setDirect(forms, { orientation: v }) }), (d) => d.orientation);
    errors.focal_length_mm = field("Focal length", focal.el, { id: "focal" });
    errors.duration_seconds = field("Length", length.el, { id: "length" });
    const shot = section("Shot", h("div", { class: "stack" }, errors.focal_length_mm.el, errors.duration_seconds.el, field("Speed", speed.el).el, field("Format", format.el).el));

    const cast = selectField({ id: "cast", options: [{ value: "", label: "No character" }], value: "", onChange: (v) => setDirect(forms, { castId: v || null }) });
    bind(cast, (d) => d.castId ?? "");
    const castHint = h("p", { class: "hint" });
    const character = section("Character", h("div", { class: "stack" }, field("Cast", cast.el, { id: "cast" }).el, castHint));
    let castSig = "";
    const paintCast = () => {
      const list = store.get().cast;
      const chosen = forms.get().direct.castId;
      const sig = `${list.map((c) => `${c.id}:${c.name}`).join()}|${chosen}`;
      if (sig === castSig) return;
      castSig = sig;
      cast.setOptions([{ value: "", label: list.length ? "No character" : "No characters yet" }, ...list.map((c) => ({ value: c.id, label: c.name }))], chosen ?? "");
      setText(castHint, chosen ? "The result is checked against this character's photos." : list.length ? "Pick a character to keep the same face across shots." : "Add a character in Cast to keep a face the same across shots.");
    };
    store.subscribe((_, changed) => changed.includes("cast") && paintCast());
    forms.subscribe(paintCast);
    paintCast();

    const audio = bind(textField({ id: "audio", multiline: true, rows: 2, maxlength: LIMITS.audio, placeholder: "What we hear: waves, a distant bell", onInput: (v) => setDirect(forms, { audio: v }) }), (d) => d.audio);
    const seed = bind(textField({ id: "seed", type: "number", inputmode: "numeric", placeholder: "Random", onInput: (v) => setDirect(forms, { seed: v }) }), (d) => d.seed);
    const dice = h("button", { type: "button", class: "btn secondary icon-only", title: "Pick a random seed", "aria-label": "Pick a random seed" }, icon("dices"));
    dice.addEventListener("click", () => setDirect(forms, { seed: String(Math.floor(Math.random() * LIMITS.seed)) }));
    errors.audio = field("Sound", audio.el, { id: "audio", hint: "LTX makes the sound with the picture." });
    errors.seed = field("Seed", h("div", { class: "input-row" }, seed.el, dice), { id: "seed", hint: "Leave empty for a random seed. It is saved in the receipt." });
    const quick = bind(switchRow({ title: "Quick mode", hint: "One still and a camera instruction: fewer renders, no anchor stills.", onChange: (v) => setDirect(forms, { quick: v }) }), (d) => d.quick);
    const auto = bind(switchRow({ title: "Skip approval", hint: "Shoot without pausing for you to approve the stills.", onChange: (v) => setDirect(forms, { autoApprove: v }) }), (d) => d.autoApprove);
    const advanced = section("Sound and options", h("div", { class: "stack" }, errors.audio.el, errors.seed.el, quick.el, auto.el), { open: false });

    el.replaceChildren(moveSection.el, shot.el, look.el, character.el, advanced.el); // length and format are what changes between takes
    const paintMeta = () => moveSection.setMeta(catalog.moves.find((m) => m.id === forms.get().direct.rig.movement)?.label ?? "");
    forms.subscribe(paintMeta);
    paintMeta();
  }

  function update() {
    const state = forms.get().direct;
    const catalog = store.get().moves;
    if (!state || !catalog) return;
    if (!el.firstChild || el.firstChild.classList?.contains("skeleton")) build(catalog);
    for (const sync of bound) sync();
    const problems = validate(state, catalog);
    for (const key of ["focal_length_mm", "duration_seconds", "audio", "seed"]) errors[key]?.setError(problems.find((p) => p.field === key)?.message);
  }

  el.append(h("div", { class: "skeleton", style: { height: "120px", margin: "16px" } }));
  forms.subscribe(update);
  store.subscribe((_, changed) => changed.includes("moves") && update());
  update();
  return { el };
}
