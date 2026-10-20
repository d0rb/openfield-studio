// Tiny DOM helpers: no framework, no build step.

const SVG_NS = "http://www.w3.org/2000/svg";
const PROPERTIES = new Set(["value", "checked", "disabled", "hidden", "selected", "open", "indeterminate", "muted", "loop"]);

function setProps(el, props) {
  for (const [key, value] of Object.entries(props ?? {})) {
    if (value == null || value === false) continue;
    if (key === "class") el.setAttribute("class", value);
    else if (key === "style" && typeof value === "object") {
      for (const [name, v] of Object.entries(value)) (name.startsWith("--") ? el.style.setProperty(name, v) : (el.style[name] = v));
    } else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (PROPERTIES.has(key)) el[key] = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
}

function append(el, kids) {
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
}

export function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  setProps(el, props);
  append(el, kids);
  return el;
}

export function svg(tag, props, ...kids) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(props ?? {})) if (value != null && value !== false) el.setAttribute(key, value);
  append(el, kids);
  return el;
}

/** A Lucide icon from the sprite; `size` is "sm" | "lg" | undefined. */
export function icon(name, size) {
  const el = svg("svg", { class: `icon${size ? ` ${size}` : ""}`, "aria-hidden": "true", focusable: "false" });
  el.append(svg("use", { href: `icons/sprite.svg#i-${name}` }));
  return el;
}

export const clear = (el) => el.replaceChildren();

/** Replace an element's children, skipping null and false (replaceChildren would write them as text). */
export function fill(el, ...kids) {
  el.replaceChildren(...kids.flat(Infinity).filter((k) => k != null && k !== false));
  return el;
}

/**
 * Keep `parent`'s children in step with `items`, reusing the elements already there (so a playing
 * video or a focused input survives a refresh). `create(item)` makes one; `update(el, item)` refreshes it.
 */
export function renderList(parent, items, key, create, update) {
  const existing = new Map();
  for (const child of parent.children) existing.set(child.dataset.key, child);
  const keep = new Set();
  items.forEach((item, index) => {
    const id = String(key(item));
    let el = existing.get(id);
    if (el) update?.(el, item);
    else {
      el = create(item);
      el.dataset.key = id;
    }
    keep.add(id);
    if (parent.children[index] !== el) parent.insertBefore(el, parent.children[index] ?? null);
  });
  for (const [id, el] of existing) if (!keep.has(id)) el.remove();
}

/** A server label ("dolly in: a lighthouse (replay)") as a title: no replay suffix, first letter capital. */
export const sentence = (text) => (text ? text.replace(/ \(replay\)$/, "").replace(/^./, (c) => c.toUpperCase()) : "");

/** Set text only when it changed, so screen readers are not re-announcing the same line. */
export function setText(el, text) {
  if (el.textContent !== text) el.textContent = text;
}

export const debounce = (fn, ms) => {
  let timer = null;
  const wrapped = (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
  wrapped.cancel = () => clearTimeout(timer);
  return wrapped;
};

/** "1.2 MB", "340 KB". */
export function bytes(n) {
  if (n >= 1048576) return `${(n / 1048576).toFixed(n >= 10485760 ? 0 : 1)} MB`;
  return `${Math.max(1, Math.round(n / 1024))} KB`;
}

/** Download a text or blob through an anchor, with a name. */
export function saveAs(url, name) {
  const a = h("a", { href: url, download: name ?? "" });
  document.body.append(a);
  a.click();
  a.remove();
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = h("textarea", { style: { position: "fixed", opacity: "0" } });
    area.value = text;
    document.body.append(area);
    area.select();
    const ok = document.execCommand?.("copy") ?? false;
    area.remove();
    return ok;
  }
}
