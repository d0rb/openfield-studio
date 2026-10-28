// The Re-shoot station: keep the movement of a clip, swap in a new character (Wan Animate 2), or only a Cast's face.

import { CLIP_TYPES, IMAGE_TYPES, LIMITS, toForm, validate } from "../lib/reshoot.js";
import { h, icon, setText } from "./dom.js";
import { dropZone, field, fileChip, section, selectField, switchRow, textField } from "./controls.js";
import { quietWhileBusy } from "./direct.js";

export const setReshoot = (forms, patch) => forms.set((s) => ({ reshoot: { ...s.reshoot, ...patch } }));

/** The "no take yet" screen: instructions, or the chosen clip and reference side by side. */
export function reshootEmpty({ forms }) {
  const { clip, referenceFile, preview } = forms.get().reshoot;
  if (!clip) {
    return h("div", { class: "empty" }, h("img", { class: "empty-art", src: "art/art-reshoot.webp", alt: "", loading: "lazy", decoding: "async" }), h("h2", null, "Re-shoot a clip with a new character"),
      h("p", null, "Add a clip and a reference image in Settings, then Re-shoot."));
  }
  return h("div", { class: "staging" },
    h("figure", null, h("video", { src: preview?.clip, muted: true, controls: true, playsinline: true, preload: "metadata" }), h("figcaption", null, "Your clip")),
    h("figure", null, preview?.reference ? h("img", { src: preview.reference, alt: "Reference" }) : h("div", { class: "empty" }, h("p", null, "Add a reference image.")), h("figcaption", null, "Reference")));
}

export function createReshootPrompt({ forms, store, controller }) {
  const prompt = textField({
    id: "re-prompt", multiline: true, rows: 1, grow: 132, maxlength: LIMITS.prompt[1],
    placeholder: "Describe the new character: age, hair, clothing, what they look like.",
    onInput: (v) => setReshoot(forms, { prompt: v }),
  });
  prompt.el.classList.add("prompt-text");
  prompt.el.setAttribute("aria-label", "Describe the new character");
  const plan = h("p", { class: "plan", id: "re-plan" });
  const go = h("button", { type: "button", class: "btn primary lg", "aria-describedby": "re-plan" });
  const el = h("div", { class: "prompt" }, prompt.el, h("div", { class: "prompt-foot" }, plan, go));
  let busy = false;

  async function shoot() {
    const state = forms.get().reshoot;
    if (busy || store.get().status?.backend?.locked) return;
    const problems = validate(state);
    if (problems.length) return setReshoot(forms, { attempted: true });
    busy = true;
    paint();
    try { await controller.startReshoot(toForm(state)); } finally { busy = false; paint(); }
  }
  go.addEventListener("click", shoot);
  prompt.el.addEventListener("keydown", (e) => (e.ctrlKey || e.metaKey) && e.key === "Enter" && (e.preventDefault(), shoot()));

  function paint() {
    const state = forms.get().reshoot;
    const locked = Boolean(store.get().status?.backend?.locked);
    const problems = validate(state);
    prompt.set(state.prompt);
    const first = problems[0];
    const face = state.faceOnly;
    plan.replaceChildren(locked
      ? h("span", { class: "plan-note" }, icon("lock", "sm"), "Recorded takes only. Connect a backend to render.")
      : first ? h("span", { class: "plan-note quiet" }, first.message)
        : h("span", null, h("b", null, face ? "Qwen-Image 2.1 + Wan Animate 2" : "Wan Animate 2"), h("span", { class: "sep" }, "·"), face ? "2 renders" : "1 render"));
    go.disabled = locked || problems.length > 0 || busy;
    go.setAttribute("aria-busy", String(busy));
    go.replaceChildren(icon(locked ? "lock" : "repeat-2"), h("span", null, busy ? "Starting…" : locked ? "Needs a backend" : "Re-shoot"));
  }
  forms.subscribe(paint);
  store.subscribe((_, changed) => changed.includes("status") && paint());
  store.subscribe((state, changed) => changed.some((k) => ["takes", "selected", "recorded"].includes(k)) && quietWhileBusy(go, state, ["reshoot"]));
  paint();
  return { el };
}

export function createReshootDock({ api, forms, store }) {
  const el = h("div", { class: "dock-pane", "data-pane": "settings" });
  const errors = {};
  const revoke = (url) => url && URL.revokeObjectURL(url);

  const pick = (key, previewKey) => (file) => {
    const previous = forms.get().reshoot.preview ?? {};
    revoke(previous[previewKey]);
    setReshoot(forms, { [key]: file, ...(key === "referenceFile" ? { castId: null } : {}), preview: { ...previous, [previewKey]: URL.createObjectURL(file) } });
  };
  const drop = (key, previewKey) => () => {
    const previous = forms.get().reshoot.preview ?? {};
    revoke(previous[previewKey]);
    setReshoot(forms, { [key]: null, preview: { ...previous, [previewKey]: null } });
  };

  // source clip
  const clipSlot = h("div", { class: "slot" });
  const clipBody = h("div", { class: "stack" }, clipSlot, h("p", { class: "hint" }, "Footage you have the right to use. Everyone in it agreed."));
  errors.clip = field("", clipBody, {});
  const clipZone = dropZone({ accept: CLIP_TYPES.join(","), label: "Add a clip", hint: `${CLIP_TYPES.join(", ")} up to ${LIMITS.clipMB} MB. Full body works best.`, onFile: pick("clip", "clip") });

  // reference
  const modes = [{ value: "upload", label: "Upload image" }, { value: "cast", label: "From Cast" }];
  const refSlot = h("div", { class: "slot" });
  const castSelect = selectField({ id: "re-cast", options: [{ value: "", label: "Pick a character" }], value: "", onChange: (v) => setReshoot(forms, { castId: v || null, referenceFile: null, refIndex: 1 }) });
  const refIndex = selectField({ id: "re-ref", options: [{ value: "1", label: "Photo 1" }], value: "1", onChange: (v) => setReshoot(forms, { refIndex: Number(v) }) });
  const castPreview = h("img", { class: "ref-thumb", alt: "", hidden: true });
  const photo = field("Photo", refIndex.el, { id: "re-ref" });
  const castPane = h("div", { class: "stack" }, field("Character", castSelect.el, { id: "re-cast" }).el, photo.el, castPreview);
  // turning it on drops an uploaded reference, so none is sent unseen
  const faceOnly = switchRow({
    title: "Swap only the face",
    hint: "Clothes and set stay. Only the face changes.",
    onChange: (on) => { if (on) drop("referenceFile", "reference")(); setReshoot(forms, on ? { faceOnly: true, refMode: "cast" } : { faceOnly: false }); },
  });
  const modeSeg = h("div", { class: "seg", role: "radiogroup", "aria-label": "Reference source" });
  const modeButtons = modes.map((m) => h("button", { type: "button", role: "radio", "data-value": m.value, "aria-checked": "false" }, m.label));
  modeSeg.append(...modeButtons);
  modeSeg.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    const previous = forms.get().reshoot.preview ?? {};
    revoke(previous.reference);
    setReshoot(forms, { refMode: b.dataset.value, referenceFile: null, castId: null, preview: { ...previous, reference: null } });
  });
  const refZone = dropZone({ accept: IMAGE_TYPES.join(","), label: "Add a reference image", hint: `${IMAGE_TYPES.join(", ")} up to ${LIMITS.imageMB} MB. One clear photo.`, onFile: pick("referenceFile", "reference") });
  const refBody = h("div", { class: "stack" }, faceOnly.el, modeSeg, refSlot, castPane);
  errors.reference = field("", refBody, {});

  const background = textField({ id: "re-bg", maxlength: LIMITS.text, placeholder: "Optional: where they are", onInput: (v) => setReshoot(forms, { background: v }) });
  const motion = textField({ id: "re-motion", maxlength: LIMITS.text, placeholder: "Optional: describe the movement", onInput: (v) => setReshoot(forms, { motion: v }) });
  const seed = textField({ id: "re-seed", type: "number", inputmode: "numeric", placeholder: "Random", onInput: (v) => setReshoot(forms, { seed: v }) });
  errors.background = field("Background", background.el, { id: "re-bg" });
  errors.motion = field("Movement note", motion.el, { id: "re-motion", hint: "Only if the clip's movement is hard to read." });
  errors.seed = field("Seed", seed.el, { id: "re-seed", hint: "Empty for random. Saved in the receipt." });

  el.append(
    section("Source clip", errors.clip.el).el,
    section("Reference", errors.reference.el).el,
    section("Options", h("div", { class: "stack" }, errors.background.el, errors.motion.el, errors.seed.el), { open: false }).el,
  );
  const clipChip = fileChip;

  let castKey = "";
  function update() {
    const s = forms.get().reshoot;
    const problems = validate(s);
    const show = (field_) => problems.find((p) => p.field === field_ && (s.attempted || !/^Add |^Describe /.test(p.message)))?.message;
    const preview = s.preview ?? {};
    clipSlot.replaceChildren(s.clip ? clipChip(s.clip, preview.clip, "video", drop("clip", "clip")) : clipZone);
    errors.clip.setError(show("clip"));
    const face = Boolean(s.faceOnly);
    faceOnly.set(face);
    const mode = face ? "cast" : s.refMode ?? "upload";
    modeSeg.hidden = face; // a face only from a Cast, every photo of it
    photo.el.hidden = face;
    modeButtons.forEach((b) => b.setAttribute("aria-checked", String(b.dataset.value === mode)));
    refSlot.hidden = mode !== "upload";
    castPane.hidden = mode !== "cast";
    refSlot.replaceChildren(s.referenceFile ? clipChip(s.referenceFile, preview.reference, "image", drop("referenceFile", "reference")) : refZone);
    errors.reference.setError(show("reference"));
    const casts = store.get().cast;
    const key = `${casts.map((c) => c.id).join()}|${s.castId}`;
    if (key !== castKey) {
      castKey = key;
      castSelect.setOptions([{ value: "", label: casts.length ? "Pick a character" : "No characters yet" }, ...casts.map((c) => ({ value: c.id, label: c.name }))], s.castId ?? "");
    }
    const chosen = casts.find((c) => c.id === s.castId);
    refIndex.setOptions((chosen?.refs ?? [{ file: "" }]).map((r, i) => ({ value: String(i + 1), label: `Photo ${i + 1}` })), String(s.refIndex));
    castPreview.hidden = !chosen;
    if (chosen) castPreview.src = api.cast.refUrl(chosen.id, chosen.refs[Math.min(chosen.refs.length, s.refIndex) - 1]?.file ?? chosen.refs[0].file);
    background.set(s.background);
    motion.set(s.motion);
    seed.set(s.seed);
    for (const key_ of ["background", "motion", "seed"]) errors[key_].setError(problems.find((p) => p.field === key_)?.message);
  }
  forms.subscribe((_, changed) => changed.includes("reshoot") && update());
  store.subscribe((_, changed) => changed.includes("cast") && update());
  update();
  return { el };
}
