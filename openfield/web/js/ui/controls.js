// The control vocabulary: every control returns { el, set(value) } and calls onChange(value) on a person's edit.
// set() never calls onChange, so the form model can push values in without loops.

import { bytes, h, icon } from "./dom.js";

let uid = 0;
export const nextId = (prefix = "f") => `${prefix}${++uid}`;

/** A labelled field. `control` is an element; `error` is updated through the returned setError(). */
export function field(label, control, { hint, id, value } = {}) {
  const errorBox = h("div", { class: "field-error", hidden: true, role: "alert" });
  const head = label ? h("div", { class: "label" }, id ? h("label", { for: id }, label) : h("span", null, label), value ?? null) : null;
  const el = h("div", { class: "field" }, head, control, hint ? h("div", { class: "hint" }, hint) : null, errorBox);
  return {
    el,
    setError(message) {
      errorBox.hidden = !message;
      errorBox.replaceChildren(...(message ? [icon("circle-alert", "sm"), h("span", null, message)] : []));
      const input = control.matches?.("input,textarea,select") ? control : control.querySelector?.("input,textarea,select");
      if (input) input.setAttribute("aria-invalid", message ? "true" : "false");
    },
  };
}

export function textField({ id = nextId(), value = "", placeholder, multiline = false, rows = 3, maxlength, onInput, type = "text", inputmode, grow = 0 } = {}) {
  const input = h(multiline ? "textarea" : "input", {
    class: multiline ? "textarea" : "input", id, placeholder, maxlength, rows: multiline ? rows : null, type: multiline ? null : type, inputmode,
    autocomplete: "off", spellcheck: "false",
  });
  input.value = value;
  // `grow` is the tallest the box may get, in pixels: it starts at its minimum height and follows the text
  const fit = () => {
    if (!grow) return;
    input.style.height = "auto";
    const full = input.scrollHeight + 2;
    const cs = globalThis.getComputedStyle?.(input);
    const cap = Math.min(grow, (cs && parseFloat(cs.maxHeight)) || grow); // the stylesheet may cap it lower on a phone
    if (full <= cap) { input.style.height = `${full}px`; return; }
    // capped: a height of whole lines, so the last line in view is never cut in half (the rest scrolls). A box that
    // scrolls keeps its borders and its top padding in view; the bottom padding scrolls away with the text, so it is
    // not part of the frame (counting it left a sliver of the next line showing under the last whole one)
    const line = cs ? parseFloat(cs.lineHeight) || 0 : 0;
    const frame = cs ? (parseFloat(cs.borderTopWidth) || 0) + (parseFloat(cs.borderBottomWidth) || 0) + (parseFloat(cs.paddingTop) || 0) : 2;
    input.style.height = `${line > 0 ? frame + Math.max(1, Math.floor((cap - frame) / line)) * line : cap}px`;
  };
  // the web font changes the line height: fit again when fonts come in (ready may already have resolved before this box)
  globalThis.document?.fonts?.ready?.then(fit);
  globalThis.document?.fonts?.addEventListener?.("loadingdone", fit);
  input.addEventListener("input", () => { fit(); onInput?.(input.value); });
  if (grow && globalThis.ResizeObserver) new ResizeObserver(fit).observe(input);
  return { el: input, id, set: (v) => { if (input.value !== String(v ?? "")) { input.value = v ?? ""; fit(); } } };
}

/** A native select. An entry with `group` and `options` becomes an optgroup. */
export function selectField({ id = nextId(), options, value, onChange }) {
  const select = h("select", { id });
  const option = (o) => h("option", { value: o.value }, o.label);
  const fill = (list) => select.replaceChildren(...list.map((o) => (o.group ? h("optgroup", { label: o.group }, ...o.options.map(option)) : option(o))));
  fill(options);
  select.value = value;
  select.addEventListener("change", () => onChange?.(select.value));
  const el = h("div", { class: "select" }, select, icon("chevron-down", "sm"));
  return {
    el, id, select,
    set(v) { select.value = v ?? ""; },
    setOptions(list, v) { fill(list); select.value = v ?? ""; },
  };
}

/** Radio group drawn as buttons: arrow keys move the choice, like native radios. */
export function segmented({ options, value, onChange, label }) {
  const el = h("div", { class: "seg", role: "radiogroup", "aria-label": label });
  const buttons = options.map((o) => // `name`: the spoken label when the visible one is an abbreviation
    h("button", { type: "button", role: "radio", "data-value": o.value, title: o.title, "aria-label": o.name, "aria-checked": "false", tabindex: "-1" }, o.label));
  el.append(...buttons);
  const set = (v) => {
    const at = buttons.findIndex((b) => b.dataset.value === String(v));
    buttons.forEach((b, i) => {
      b.setAttribute("aria-checked", i === at ? "true" : "false");
      b.tabIndex = i === at || (at < 0 && i === 0) ? 0 : -1;
    });
  };
  const choose = (button) => {
    set(button.dataset.value);
    onChange?.(options.find((o) => String(o.value) === button.dataset.value).value);
  };
  el.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (b && !b.disabled) choose(b);
  });
  el.addEventListener("keydown", (e) => {
    const move = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (!move) return;
    e.preventDefault();
    const enabled = buttons.filter((b) => !b.disabled);
    const at = enabled.indexOf(document.activeElement);
    const next = enabled[(at + move + enabled.length) % enabled.length];
    next.focus();
    choose(next);
  });
  set(value);
  return { el, set, setDisabled: (off) => buttons.forEach((b) => (b.disabled = off)) };
}

/** Keys for radios whose pick is costly: one tab stop, on the checked one (sync() moves it); arrows, Home and End move the
 * focus, and onPick comes once it rests 250 ms. */
export function radioKeys(group, { onPick }) {
  let timer = 0;
  const radios = () => [...group.querySelectorAll("[role=radio]")];
  const sync = () => {
    const all = radios();
    const on = all.find((r) => r.getAttribute("aria-checked") === "true") ?? all[0];
    for (const r of all) r.tabIndex = r === on ? 0 : -1;
  };
  group.addEventListener("keydown", (e) => {
    const all = radios();
    const at = all.indexOf(e.target);
    const to = { ArrowRight: at + 1, ArrowDown: at + 1, ArrowLeft: at - 1, ArrowUp: at - 1, Home: 0, End: -1 }[e.key];
    if (at < 0 || to === undefined || e.altKey || e.ctrlKey || e.metaKey) return;
    e.preventDefault();
    const next = all.at(to % all.length);
    next.focus();
    clearTimeout(timer);
    timer = setTimeout(() => next.isConnected && document.activeElement === next && onPick(next), 250); // never after the group is gone
  });
  sync();
  return sync;
}

/** A range with a number box beside it. `format` renders the value shown in the label. */
export function sliderField({ id = nextId(), min, max, step = 1, value, unit = "", onChange, label }) {
  const range = h("input", { class: "range", type: "range", id, min, max, step, "aria-label": label });
  const number = h("input", { class: "input num-input", type: "number", min, max, step, inputmode: "numeric", "aria-label": `${label} (number)` });
  const unitEl = unit ? h("span", { class: "hint" }, unit) : null;
  const paint = () => range.style.setProperty("--fill", `${((range.value - min) / (max - min)) * 100}%`);
  const set = (v) => {
    if (range.value !== String(v)) range.value = v;
    if (document.activeElement !== number) number.value = v;
    paint();
  };
  range.addEventListener("input", () => {
    number.value = range.value;
    paint();
    onChange?.(Number(range.value));
  });
  number.addEventListener("input", () => {
    const v = Number(number.value);
    if (number.value !== "" && Number.isFinite(v)) {
      range.value = Math.min(max, Math.max(min, v));
      paint();
      onChange?.(v); // out-of-range values go through so the form can say so
    }
  });
  number.addEventListener("blur", () => { number.value = number.value === "" ? range.value : number.value; });
  set(value);
  return { el: h("div", { class: "slider-row" }, range, h("div", { class: "input-row", style: { alignItems: "center" } }, number, unitEl)), set, id };
}

export function switchRow({ title, hint, value = false, onChange, id = nextId("sw") }) {
  const button = h("button", { type: "button", role: "switch", class: "switch", id, "aria-checked": String(Boolean(value)), "aria-labelledby": `${id}-t` });
  button.addEventListener("click", () => {
    const on = button.getAttribute("aria-checked") !== "true";
    button.setAttribute("aria-checked", String(on));
    onChange?.(on);
  });
  const el = h("div", { class: "switch-row" }, h("div", { class: "copy" }, h("span", { class: "title", id: `${id}-t` }, title), hint ? h("span", { class: "hint" }, hint) : null), button);
  return { el, set: (v) => button.setAttribute("aria-checked", String(Boolean(v))), setDisabled: (off) => (button.disabled = off) };
}

/** A collapsible dock section. Open state is remembered per title for the session. */
const remembered = new Map();
export function section(title, body, { open = true, meta = null } = {}) {
  const id = nextId("sec");
  const isOpen = remembered.get(title) ?? open;
  const metaEl = h("span", { class: "meta" }, meta ?? "");
  const head = h("button", { type: "button", class: "section-head", "aria-expanded": String(isOpen), "aria-controls": id }, h("span", null, title), metaEl, h("span", { class: "grow" }), icon("chevron-down", "sm"));
  head.lastChild.classList.add("chev");
  const content = h("div", { class: "section-body", id, hidden: !isOpen }, body);
  head.addEventListener("click", () => {
    const next = head.getAttribute("aria-expanded") !== "true";
    head.setAttribute("aria-expanded", String(next));
    content.hidden = !next;
    remembered.set(title, next);
  });
  return { el: h("section", { class: "section" }, head, content), setMeta: (text) => { metaEl.textContent = text ?? ""; } };
}

/** A pill: tone is neutral | green | amber | red | accent. */
export function pill(text, tone, { dot = false, size } = {}) {
  return h("span", { class: `pill${size ? ` ${size}` : ""}`, "data-tone": tone ?? null }, dot ? h("span", { class: "dot" }) : null, text);
}

/** A drop zone: a button that opens the file picker, and accepts a dragged file. */
export function dropZone({ accept, label, hint, onFile }) {
  const input = h("input", { type: "file", accept, class: "sr-only", tabindex: "-1", "aria-label": label });
  const zone = h("button", { type: "button", class: "drop" }, icon("upload"), h("span", { class: "drop-text" }, h("b", null, label), h("span", { class: "hint" }, hint)));
  zone.addEventListener("click", () => input.click());
  input.addEventListener("change", () => input.files[0] && (onFile(input.files[0]), (input.value = "")));
  for (const type of ["dragenter", "dragover"]) zone.addEventListener(type, (e) => { e.preventDefault(); zone.classList.add("over"); });
  for (const type of ["dragleave", "drop"]) zone.addEventListener(type, () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => { e.preventDefault(); const file = e.dataTransfer.files[0]; if (file) onFile(file); });
  return h("div", null, zone, input);
}

/** A chosen file: its thumbnail (image or video), name and size, and a button to take it out again. */
export function fileChip(file, url, kind, onRemove) {
  const remove = h("button", { type: "button", class: "btn ghost sm icon-only", "aria-label": "Remove" }, icon("x", "sm"));
  remove.addEventListener("click", onRemove);
  return h("div", { class: "file" }, kind === "video" ? h("video", { src: `${url}#t=0.1`, muted: true, preload: "metadata", playsinline: true }) : h("img", { src: url, alt: "" }),
    h("div", { class: "file-text" }, h("b", null, file.name), h("span", { class: "hint" }, bytes(file.size))), remove);
}
