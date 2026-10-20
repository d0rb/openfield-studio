// The control vocabulary: every control returns { el, set(value) } and calls onChange(value) on a person's edit.
// set() never calls onChange, so the form model can push values in without loops.

import { h, icon } from "./dom.js";

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
    input.style.height = `${Math.min(input.scrollHeight + 2, grow)}px`;
  };
  input.addEventListener("input", () => { fit(); onInput?.(input.value); });
  if (grow && globalThis.ResizeObserver) new ResizeObserver(fit).observe(input);
  return { el: input, id, set: (v) => { if (input.value !== String(v ?? "")) { input.value = v ?? ""; fit(); } } };
}

export function selectField({ id = nextId(), options, value, onChange }) {
  const select = h("select", { id });
  const fill = (list) => select.replaceChildren(...list.map((o) => h("option", { value: o.value }, o.label)));
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
  const buttons = options.map((o) =>
    h("button", { type: "button", role: "radio", "data-value": o.value, title: o.title, "aria-checked": "false", tabindex: "-1" }, o.label));
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
