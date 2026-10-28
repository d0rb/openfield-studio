// Edit with words: one Qwen-Image 2.1 edit of one still (a Cast gives any face or person); the take plays it before and
// after. Dub: a talking take re-rendered from its own first still, speaking a translated line. Extend: one LTX 2.5 render
// from a finished take's last frame; the take plays the original, then the extension. Upscale: one Real-ESRGAN pass.

import { dubIn, dubProblem, dubRequest, editPreset, editProblem, editRequest, heroStill, recordedDubs, recordedEdit, recordedExtend, recordedUpscale } from "../lib/edit.js";
import { fileOf } from "../lib/stages.js";
import { h } from "./dom.js";
import { field, segmented, selectField, textField } from "./controls.js";
import { notify, stillFile } from "./actions.js";
import { isLocked, leaves, takeSheet } from "./sheet.js";

export function openEditSheet(ctx, take, { still = null, receipt = null } = {}) {
  const { api, store, controller } = ctx;
  const { moves: catalog, cast: casts, recorded: shelf } = store.get();
  const edits = catalog?.edits;
  if (!edits?.presets?.length) return;
  const locked = isLocked(ctx);
  const recorded = (id) => (locked ? recordedEdit(shelf, take, id, still) : null);
  let preset = (edits.presets.find((p) => recorded(p.id)) ?? editPreset(catalog, "custom") ?? edits.presets[0]).id; // in Replay a recorded one leads
  let light = edits.lights[0]?.id;
  let detail = "";
  let castId = "";
  const presets = segmented({ label: "Edit", options: edits.presets.map((p) => ({ value: p.id, label: p.label })), value: preset, onChange: (v) => { preset = v; paint(); } });
  const lights = segmented({ label: "Light", options: edits.lights.map((l) => ({ value: l.id, label: l.label })), value: light, onChange: (v) => { light = v; paint(); } });
  const words = textField({ id: "edit-words", maxlength: edits.max_chars, onInput: (v) => { detail = v; paint(); } });
  const cast = selectField({ id: "edit-cast", options: [{ value: "", label: casts.length ? "Pick a character" : "No characters yet" }, ...casts.map((c) => ({ value: c.id, label: c.name }))], value: "", onChange: (v) => { castId = v; paint(); } });
  const asks = { light: field("Light", lights.el).el, words: field("Words", words.el, { id: "edit-words" }).el,
    cast: field("Character", cast.el, { id: "edit-cast", hint: "Faces come only from a Cast." }).el };
  const say = takeSheet(ctx, { title: "Edit with words", className: "sheet-edit", label: locked ? "Play the recorded edit" : "Render the edit", glyph: "image",
    parts: [leaves(api, take, still ?? receipt?.inputs?.anchors?.[0]?.file ?? fileOf(take, "poster"), "Edits"), // no still named: the server edits the first approved one
      field("Edit", presets.el).el, asks.light, asks.words, asks.cast],
    recorded: () => recorded(preset),
    start: () => {
      const form = new FormData();
      form.append("request", JSON.stringify(editRequest({ preset, detail, light, castId, take: take.replay_of ?? take.id, still }, catalog)));
      return controller.startEdit(form);
    } });

  function paint() {
    const p = editPreset(catalog, preset);
    const rec = recorded(preset);
    asks.light.hidden = locked || preset !== "relight"; // Replay renders nothing, so it asks for nothing
    asks.words.hidden = locked || !p.needs_detail;
    asks.cast.hidden = locked || !p.needs_cast;
    words.el.placeholder = preset === "relight" ? "Or the light in your own words" : "Say what to change";
    const problem = locked ? null : editProblem({ preset, detail, light, castId }, catalog);
    say(locked ? (rec ? "Replay plays this recorded edit." : "Recorded takes only. Connect a backend to render.")
      : problem ?? "One edit. The take shows the still before and after.", locked ? rec : !problem);
  }
  paint();
}

/** Extend and Upscale ask one thing of a take: Replay plays `find(value)` (a recorded choice leads), live `start` renders. */
function choiceSheet(ctx, take, { verb, name, choices, noun, line, find, start, ...sheet }) {
  const locked = isLocked(ctx);
  const rec = (v) => (locked ? find(v) : null);
  let value = (choices.find((c) => rec(c.value)) ?? choices[0]).value;
  const pick = segmented({ label: name, options: choices, value, onChange: (v) => { value = v; paint(); } });
  const say = takeSheet(ctx, { ...sheet, label: locked ? `Play the recorded ${noun}` : sheet.label,
    parts: [leaves(ctx.api, take, fileOf(take, "poster"), verb), field(name, pick.el).el],
    recorded: () => rec(value),
    start: () => start(take.replay_of ?? take.id, value) });

  function paint() {
    say(locked ? (rec(value) ? `Replay plays this recorded ${noun}.` : "Recorded takes only. Connect a backend to render.")
      : line, !locked || rec(value));
  }
  paint();
}

export function openExtendSheet(ctx, take) {
  const { moves, recorded } = ctx.store.get();
  const extend = moves?.extend;
  if (extend?.seconds?.length) choiceSheet(ctx, take, { title: "Extend", className: "sheet-extend", label: "Render the extension", glyph: "chevrons-right",
    verb: "Continues", name: "Adds", noun: "extension", choices: extend.seconds.map((n) => ({ value: n, label: `${n} s` })),
    line: "Continues the shot from its last frame.",
    find: (n) => recordedExtend(recorded, take, n), start: (id, n) => ctx.controller.startExtend(id, n) });
}

export function openUpscaleSheet(ctx, take) {
  const { moves, recorded } = ctx.store.get();
  const targets = moves?.upscale?.targets;
  if (targets?.length) choiceSheet(ctx, take, { title: "Upscale", className: "sheet-upscale", label: "Upscale", glyph: "maximize",
    verb: "Enlarges", name: "Size", noun: "upscale", choices: targets.map((t) => ({ value: t.id, label: t.label })),
    line: "Sharpens the take. Nothing new is drawn in.",
    find: (id) => recordedUpscale(recorded, take, id), start: (id, target) => ctx.controller.startUpscale(id, target) });
}

export function openDubSheet(ctx, take, { receipt = null } = {}) {
  const { api, store, controller } = ctx;
  const { moves, recorded } = store.get();
  const dialogue = moves?.dialogue;
  const recipe = take.recipe ?? {};
  if (!dialogue || !recipe.line) return;
  const locked = isLocked(ctx);
  const dubs = locked ? recordedDubs(recorded, take) : [];
  const still = heroStill(take, receipt);
  let language = dubs[0]?.recipe.language ?? "";
  let line = "";
  const tongue = textField({ id: "dub-language", value: language, maxlength: dialogue.language_max_chars, placeholder: "Spanish", onInput: (v) => { language = v; paint(); } });
  const words = textField({ id: "dub-line", multiline: true, rows: 3, maxlength: dialogue.max_chars, placeholder: "The line, in that language", onInput: (v) => { line = v; paint(); } });
  const lineField = field("New line", words.el, { id: "dub-line", hint: `Now: “${recipe.line}”` }).el;
  lineField.hidden = locked; // Replay plays a recorded dub as it was spoken
  const say = takeSheet(ctx, { title: "Dub", className: "sheet-dub", label: locked ? "Play the recorded dub" : "Render the dub", glyph: "volume-2",
    parts: [leaves(api, take, still, "Speaks"), field("Language", tongue.el, { id: "dub-language" }).el, lineField,
      h("p", { class: "hint" }, "A new render of the same still, speaking the new line.")],
    recorded: () => dubIn(dubs, language),
    start: async () => {
      const form = new FormData();
      form.append("request", JSON.stringify(dubRequest(recipe, { line, language })));
      try { form.append("source", await stillFile(api, take, still)); } catch {
        notify(ctx, "Could not load the take's still.", null, "error");
        return null;
      }
      return controller.startDirectFromImage(form);
    } });

  function paint() {
    const rec = dubIn(dubs, language);
    const problem = locked ? null : dubProblem({ line, language });
    say(locked ? (rec ? `Recorded in ${rec.recipe.language}: “${rec.recipe.line}”.` : "Recorded takes only. Connect a backend to render.")
      : problem ?? "Uses the take's approved stills.", locked ? rec : !problem);
  }
  paint();
}
