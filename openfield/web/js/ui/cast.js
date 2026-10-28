// The Cast station: characters and products reused across shots. Consent comes first; a character can
// be photos you have the right to use, or an invented person generated from a description.

import { CONSENT, IMAGE_TYPES, KINDS, LIMITS, candidatesOf, characterBody, initialCast, initialCharacter, suggestName, toForm, validate, validateCharacter } from "../lib/cast.js";
import { portraitTakes } from "../lib/takes.js";
import { fileOf, fromRecorded, posterAttrs, titleOf } from "../lib/stages.js";
import { phone, savingData } from "../lib/pictures.js";
import { bytes, flip, h, icon, renderList } from "./dom.js";
import { field, pill, section, segmented, textField } from "./controls.js";
import { setDirect } from "./direct.js";
import { hoverClip, hoverPlay } from "./hoverplay.js";

const setCast = (forms, patch) => forms.set((s) => ({ castForm: { ...s.castForm, ...patch } }));
const setCharacter = (forms, patch) => forms.set((s) => ({ character: { ...s.character, ...patch } }));

export function createCastStation(ctx) {
  const { api, store, forms, controller, ui } = ctx;
  const locked = () => Boolean(store.get().status?.backend?.locked) || api.kind === "static";
  const candidates = h("section", { class: "cast-candidates", hidden: true });
  const grid = h("div", { class: "cast-grid" });
  const empty = h("div", { class: "empty" }, h("img", { class: "empty-art", src: "art/art-cast.webp", alt: "", loading: "lazy", decoding: "async" }), h("h2", null, "No characters yet"),
    h("p", null, "Make one from a description, or add photos."));
  const note = h("p", { class: "hint cast-note" }, "Generated characters are invented. Photos need the right to use them.");
  const el = h("section", { class: "cast-station", "aria-label": "Cast" },
    h("div", { class: "station-head" }, h("h1", null, "Cast"), h("p", null, "Characters, products and places you reuse across shots.")),
    candidates, grid, note, empty);
  let armed = null;

  // the takes a character is in: Direct takes cast with them and re-shoots that made them the new character,
  // in the showcase's reel order, then newest first
  function appearances(name) {
    const s = store.get();
    const own = new Set(s.takes.map((t) => t.id));
    const reel = new Map((s.status?.hero_reel ?? []).map((id, i) => [id, i]));
    const place = (t) => reel.get(t.id) ?? reel.size;
    return [...s.takes, ...s.recorded.filter((r) => !own.has(r.id)).map(fromRecorded)]
      .filter((t) => t.status === "succeeded" && !t.replay && (t.recipe?.cast_name === name || t.recipe?.reference_name === name) && fileOf(t, "poster"))
      .map((t, i) => ({ t, i })).sort((a, b) => place(a.t) - place(b.t) || a.i - b.i).map(({ t }) => t);
  }
  function appearsRow(c) {
    const shots = appearances(c.name);
    if (!shots.length) return null;
    return h("div", { class: "cast-appears", "data-sig": shots.slice(0, 4).map((t) => t.id).join() + `|${shots.length}` },
      h("span", { class: "cast-appears-label" }, `In ${shots.length} take${shots.length === 1 ? "" : "s"}`),
      h("div", { class: "cast-appears-row" }, ...shots.slice(0, 4).map((t) => {
        const open = h("button", { type: "button", class: "cast-take", "aria-label": `Open ${titleOf(t)}`, title: titleOf(t) },
          h("img", { ...posterAttrs(store.get(), t, api, "80px"), alt: "", loading: "lazy", draggable: "false" }));
        open.addEventListener("click", () => ui.openTake(t.id));
        hoverPlay(open, hoverClip(store, t, api)); // the take plays in its thumb under the hand; the portrait above never does
        return open;
      })));
  }

  // a portrait: the reference alone, or with the hosted copy's 768px one beside it (a phone or a data saver keeps to the small one)
  function portrait(c, ref) {
    const url = (file) => api.cast.refUrl(c.id, file);
    const small = ref.small; // the export's 768px copy (hosted copy only)
    if (!small) return h("img", { src: url(ref.file), alt: c.name, loading: "lazy", decoding: "async" });
    if (phone() || savingData()) return h("img", { src: url(small.file), alt: c.name, loading: "lazy", decoding: "async" }); // a 3x phone would ask for the PNG
    return h("img", { src: url(ref.file), srcset: `${url(small.file)} ${small.width}w, ${url(ref.file)} ${ref.size?.[0] ?? 1024}w`,
      sizes: "(max-width: 719px) 92vw, 322px", alt: c.name, loading: "lazy", decoding: "async" });
  }

  function card(c) {
    const ref = c.refs?.[0];
    const use = h("button", { type: "button", class: "btn secondary sm" }, icon("clapperboard", "sm"), "Use in Direct");
    use.title = `${c.name} keeps the same face across shots`;
    use.addEventListener("click", () => { setDirect(forms, { castId: c.id }); ui.go("direct"); });
    const del = h("button", { type: "button", class: "btn ghost sm quiet-danger icon-only", "aria-label": `Delete ${c.name}` }, icon("trash-2", "sm"));
    del.addEventListener("click", () => {
      if (armed !== c.id) { armed = c.id; return paint(); }
      armed = null;
      controller.removeCast(c.id);
    });
    return h("article", { class: "cast-card" },
      h("div", { class: "cast-photo" }, ref?.file ? portrait(c, ref) : icon("image", "lg"),
        h("span", { class: "cast-name" }, c.name), c.refs?.length > 1 ? h("span", { class: "tile-badge" }, `${c.refs.length} photos`) : null),
      h("div", { class: "cast-meta" }, pill(c.kind), c.origin ? Object.assign(pill("Generated", null, { dot: true }), { title: "An invented person, made from a description" }) : null, c.bundled ? pill("Showcase") : null, h("span", { class: "grow" }), use, c.bundled ? null : del), // bundled members come with the showcase
      appearsRow(c) ?? h("div", { class: "cast-appears", hidden: true }));
  }

  function updateCard(node, c) {
    const row = appearsRow(c);
    const old = node.querySelector(".cast-appears");
    if (row && old?.dataset.sig !== row.dataset.sig) old.replaceWith(row);
    else if (!row && old && !old.hidden) old.replaceWith(h("div", { class: "cast-appears", hidden: true }));
    const del = node.querySelector("button.quiet-danger");
    if (!del) return;
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
          live ? pill(take.status === "failed" ? "Failed" : "Generating…", take.status === "failed" ? "red" : "accent") : pill("Invented people. Keep the one you like."),
          h("span", { class: "grow" }), discard),
        live && take.status !== "failed" ? h("div", { class: "bar" }, h("span", { style: { "--p": String(take.progress ?? 0) } })) : null,
        take.status === "failed" ? h("p", { class: "hint" }, take.error?.message ?? "Generation failed.") : null,
        h("div", { class: "candidate-row" }, faces));
    }));
  }

  function paint() {
    const casts = store.get().cast;
    flip(grid, () => renderList(grid, casts, (c) => c.id, card, updateCard), { keys: casts.map((c) => c.id) }); // a card added or deleted: the others glide, a new one settles in
    grid.hidden = casts.length === 0;
    note.hidden = !store.get().cast.length;
    empty.hidden = casts.length > 0 || !candidates.hidden;
    candidateRow();
  }
  store.subscribe((_, changed) => changed.some((k) => ["cast", "takes", "recorded", "status"].includes(k)) && paint());
  paint();
  return { el, locked };
}

export function createCastDock(ctx) {
  const { api, store, forms, controller } = ctx;
  const el = h("div", { class: "dock-pane", "data-pane": "settings" });
  const lock = h("p", { class: "hint lock-note" }, icon("lock", "sm"), "Replay cannot make characters. Connect a backend.");

  // -- generate -------------------------------------------------------------------------------
  const description = textField({ id: "ch-desc", multiline: true, rows: 3, maxlength: LIMITS.description[1], placeholder: "A woman in her late twenties with short dark hair, freckles and a yellow rain jacket", onInput: (v) => setCharacter(forms, { description: v }) });
  const count = segmented({ label: "How many", options: [1, 2, 3, 4].map((n) => ({ value: n, label: String(n) })), value: 3, onChange: (n) => setCharacter(forms, { count: n }) });
  const seed = textField({ id: "ch-seed", type: "number", inputmode: "numeric", placeholder: "Random", onInput: (v) => setCharacter(forms, { seed: v }) });
  const gen = h("button", { type: "button", class: "btn primary" }, icon("user-round-plus"), "Generate");
  const fDesc = field("Description", description.el, { id: "ch-desc", hint: "Always an invented person." });
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
