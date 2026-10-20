// The Cast station: characters and products reused across shots. Consent comes first; a character can
// be photos you have the right to use, or an invented person generated from a description.

import { CONSENT, IMAGE_TYPES, KINDS, LIMITS, candidatesOf, characterBody, initialCast, initialCharacter, suggestName, toForm, validate, validateCharacter } from "../lib/cast.js";
import { portraitTakes } from "../lib/takes.js";
import { bytes, h, icon, renderList } from "./dom.js";
import { field, pill, section, segmented, textField } from "./controls.js";
import { setDirect } from "./direct.js";

const setCast = (forms, patch) => forms.set((s) => ({ castForm: { ...s.castForm, ...patch } }));
const setCharacter = (forms, patch) => forms.set((s) => ({ character: { ...s.character, ...patch } }));

export function createCastStation(ctx) {
  const { api, store, forms, controller, ui } = ctx;
  const locked = () => Boolean(store.get().status?.backend?.locked) || api.kind === "static";
  const candidates = h("section", { class: "cast-candidates", hidden: true });
  const grid = h("div", { class: "cast-grid" });
  const empty = h("div", { class: "empty" }, icon("users-round", "lg"), h("h2", null, "No characters yet"),
    h("p", null, "Generate an invented character from a description, or add photos you have the right to use. Pick them in Direct to keep the same face across shots."));
  const el = h("section", { class: "cast-station", "aria-label": "Cast" },
    h("div", { class: "station-head" }, h("h1", null, "Cast"), h("p", null, "Characters, products and places you reuse across shots.")),
    candidates, grid, empty);
  let armed = null;

  function card(c) {
    const first = c.refs?.[0]?.file;
    const use = h("button", { type: "button", class: "btn secondary sm" }, icon("clapperboard", "sm"), "Use in Direct");
    use.addEventListener("click", () => { setDirect(forms, { castId: c.id }); ui.go("direct"); });
    const del = h("button", { type: "button", class: "btn ghost sm quiet-danger icon-only", "aria-label": `Delete ${c.name}` }, icon("trash-2", "sm"));
    del.addEventListener("click", () => {
      if (armed !== c.id) { armed = c.id; return paint(); }
      armed = null;
      controller.removeCast(c.id);
    });
    return h("article", { class: "cast-card" },
      h("div", { class: "cast-photo" }, first ? h("img", { src: api.cast.refUrl(c.id, first), alt: `${c.name}`, loading: "lazy" }) : icon("image", "lg"), c.refs?.length > 1 ? h("span", { class: "tile-badge" }, `${c.refs.length} photos`) : null),
      h("div", { class: "cast-meta" }, h("b", null, c.name), pill(c.kind), c.origin ? pill("Generated", "accent") : null),
      h("p", { class: "hint" }, c.consent_text ?? ""),
      h("div", { class: "cast-actions" }, use, del));
  }

  function updateCard(node, c) {
    const del = node.querySelector("button.quiet-danger");
    const label = armed === c.id ? "Delete?" : null;
    del.replaceChildren(...(label ? [label] : [icon("trash-2", "sm")]));
    del.classList.toggle("icon-only", !label);
  }

  function candidateRow() {
    const takes = portraitTakes(store.get().takes).slice(0, 1);
    candidates.hidden = takes.length === 0;
    candidates.replaceChildren(...takes.map((take) => {
      const live = take.status !== "succeeded";
      const faces = candidatesOf(take).map(({ number, file }) => {
        const name = textField({ id: `keep-${take.id}-${number}`, value: suggestName(take.recipe?.description ?? ""), maxlength: LIMITS.name[1] });
        name.el.setAttribute("aria-label", `Name for candidate ${number}`);
        const keep = h("button", { type: "button", class: "btn primary" }, "Keep");
        keep.addEventListener("click", async () => { keep.disabled = true; await controller.keepCandidate(take.id, number, name.el.value.trim()); keep.disabled = false; });
        return h("figure", { class: "candidate" }, h("img", { src: api.media(take, file), alt: `Candidate ${number}` }), h("figcaption", null, name.el, keep));
      });
      const discard = h("button", { type: "button", class: "btn ghost sm" }, icon("x", "sm"), live && take.status !== "failed" ? "Stop" : "Discard these");
      discard.addEventListener("click", () => controller.remove(take.id));
      return h("div", { class: "candidate-set" },
        h("div", { class: "candidate-head" }, h("h2", null, "Generated characters"), h("span", { class: "hint" }, take.recipe?.description ?? take.label),
          live ? pill(take.status === "failed" ? "Failed" : "Generating…", take.status === "failed" ? "red" : "accent") : pill("Invented people. Keep the one you like.", "accent"),
          h("span", { class: "grow" }), discard),
        live && take.status !== "failed" ? h("div", { class: "bar" }, h("span", { style: { "--p": String(take.progress ?? 0) } })) : null,
        take.status === "failed" ? h("p", { class: "hint" }, take.error?.message ?? "Generation failed.") : null,
        h("div", { class: "candidate-row" }, faces));
    }));
  }

  function paint() {
    const casts = store.get().cast;
    renderList(grid, casts, (c) => c.id, card, updateCard);
    grid.hidden = casts.length === 0;
    empty.hidden = casts.length > 0 || !candidates.hidden;
    candidateRow();
  }
  store.subscribe((_, changed) => changed.some((k) => ["cast", "takes", "status"].includes(k)) && paint());
  paint();
  return { el, locked };
}

export function createCastDock(ctx) {
  const { api, store, forms, controller } = ctx;
  const el = h("div", { class: "dock-pane", "data-pane": "settings" });
  const lock = h("p", { class: "hint lock-note" }, icon("lock", "sm"), "Replay cannot make or save characters. Connect a backend to generate one, or install OpenField to add photos.");

  // -- generate -------------------------------------------------------------------------------
  const description = textField({ id: "ch-desc", multiline: true, rows: 3, maxlength: LIMITS.description[1], placeholder: "A woman in her late twenties with short dark hair, freckles and a yellow rain jacket", onInput: (v) => setCharacter(forms, { description: v }) });
  const count = segmented({ label: "How many", options: [1, 2, 3, 4].map((n) => ({ value: n, label: String(n) })), value: 3, onChange: (n) => setCharacter(forms, { count: n }) });
  const seed = textField({ id: "ch-seed", type: "number", inputmode: "numeric", placeholder: "Random", onInput: (v) => setCharacter(forms, { seed: v }) });
  const gen = h("button", { type: "button", class: "btn primary" }, icon("user-round-plus"), "Generate");
  const fDesc = field("Description", description.el, { id: "ch-desc", hint: "Always an invented person. It will not look like anyone real." });
  const fSeed = field("Seed", seed.el, { id: "ch-seed" });
  gen.addEventListener("click", async () => {
    const s = forms.get().character;
    if (validateCharacter(s).length) return setCharacter(forms, { attempted: true });
    gen.disabled = true;
    await controller.generateCharacter(characterBody(s));
    gen.disabled = false;
  });
  const generate = section("Generate a character", h("div", { class: "stack" }, fDesc.el, field("Candidates", count.el).el, fSeed.el, gen));

  // -- from photos ----------------------------------------------------------------------------
  const name = textField({ id: "ca-name", maxlength: LIMITS.name[1], placeholder: "Mara", onInput: (v) => setCast(forms, { name: v }) });
  const kinds = segmented({ label: "Kind", options: KINDS.map((k) => ({ value: k, label: k[0].toUpperCase() + k.slice(1) })), value: "character", onChange: (k) => setCast(forms, { kind: k }) });
  const consent = h("div", { class: "consent", role: "radiogroup", "aria-label": "Consent" },
    ...Object.entries(CONSENT).map(([value, text]) => {
      const input = h("input", { type: "radio", name: "consent", value, id: `consent-${value}` });
      input.addEventListener("change", () => setCast(forms, { consent: value }));
      return h("label", { for: `consent-${value}`, class: "radio" }, input, h("span", null, text));
    }));
  const fileInput = h("input", { type: "file", multiple: true, accept: IMAGE_TYPES.join(","), class: "sr-only", tabindex: "-1", "aria-label": "Choose photos" });
  const chooser = h("button", { type: "button", class: "drop" }, icon("upload"), h("span", { class: "drop-text" }, h("b", null, "Add photos"), h("span", { class: "hint" }, `${LIMITS.images[0]} to ${LIMITS.images[1]} images, ${IMAGE_TYPES.join(", ")}, up to ${LIMITS.imageMB} MB each.`)));
  chooser.addEventListener("click", () => fileInput.click());
  const addFiles = (list) => setCast(forms, { files: [...forms.get().castForm.files, ...list].slice(0, LIMITS.images[1]) });
  fileInput.addEventListener("change", () => { addFiles(fileInput.files); fileInput.value = ""; });
  chooser.addEventListener("dragover", (e) => { e.preventDefault(); chooser.classList.add("over"); });
  chooser.addEventListener("dragleave", () => chooser.classList.remove("over"));
  chooser.addEventListener("drop", (e) => { e.preventDefault(); chooser.classList.remove("over"); addFiles(e.dataTransfer.files); });
  const fileList = h("ul", { class: "files" });
  const save = h("button", { type: "button", class: "btn primary" }, icon("check"), "Save to Cast");
  const fName = field("Name", name.el, { id: "ca-name" });
  const fConsent = field("Who is in these photos", consent, {});
  const fFiles = field("Photos", h("div", { class: "stack" }, chooser, fileInput, fileList), {});
  save.addEventListener("click", async () => {
    const s = forms.get().castForm;
    if (validate(s).length) return setCast(forms, { attempted: true });
    save.disabled = true;
    const made = await controller.createCast(toForm(s));
    save.disabled = false;
    if (made) forms.set({ castForm: initialCast() });
  });
  const photos = section("Add from photos", h("div", { class: "stack" }, fName.el, field("Kind", kinds.el).el, fConsent.el, fFiles.el, save), { open: false });

  el.append(lock, generate.el, photos.el);

  function update() {
    const isLocked = Boolean(store.get().status?.backend?.locked) || api.kind === "static";
    lock.hidden = !isLocked;
    gen.disabled = isLocked;
    save.disabled = isLocked;
    const ch = forms.get().character;
    const cf = forms.get().castForm;
    description.set(ch.description);
    count.set(ch.count);
    seed.set(ch.seed);
    const cp = validateCharacter(ch);
    fDesc.setError(ch.attempted ? cp.find((p) => p.field === "description")?.message : undefined);
    fSeed.setError(cp.find((p) => p.field === "seed")?.message);
    name.set(cf.name);
    kinds.set(cf.kind);
    consent.querySelectorAll("input").forEach((i) => (i.checked = i.value === cf.consent));
    fileList.replaceChildren(...cf.files.map((f, i) => {
      const rm = h("button", { type: "button", class: "btn ghost sm icon-only", "aria-label": `Remove ${f.name}` }, icon("x", "sm"));
      rm.addEventListener("click", () => setCast(forms, { files: forms.get().castForm.files.filter((_, j) => j !== i) }));
      return h("li", null, h("span", { class: "file-name" }, f.name), h("span", { class: "hint" }, bytes(f.size)), rm);
    }));
    const problems = validate(cf);
    const when = (field_) => (cf.attempted || /not a|over/.test(problems.find((p) => p.field === field_)?.message ?? "") ? problems.find((p) => p.field === field_)?.message : undefined);
    fName.setError(cf.attempted ? problems.find((p) => p.field === "name")?.message : undefined);
    fConsent.setError(cf.attempted ? problems.find((p) => p.field === "consent")?.message : undefined);
    fFiles.setError(when("files"));
  }
  forms.subscribe((_, changed) => changed.some((k) => ["character", "castForm"].includes(k)) && update());
  store.subscribe((_, changed) => changed.includes("status") && update());
  update();
  return { el };
}

export { initialCharacter };
