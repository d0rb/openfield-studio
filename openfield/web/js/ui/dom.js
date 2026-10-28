// Tiny DOM helpers: no framework, no build step.

import { holdStill } from "../lib/motion.js";

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
  const keep = new Set(items.map((item) => String(key(item))));
  for (const [id, el] of existing) if (!keep.has(id)) el.remove(); // first, so a stale element never pushes the ones after it out of place
  items.forEach((item, index) => {
    const id = String(key(item));
    let el = existing.get(id);
    if (el) update?.(el, item);
    else {
      el = create(item);
      el.dataset.key = id;
    }
    if (parent.children[index] !== el) parent.insertBefore(el, parent.children[index] ?? null);
  });
}

/**
 * How children moved between two measurements (Maps of key -> { left, top, bottom }); pure, so it is tested alone.
 * `moved`: each key's offset back to where it was (dx, dy); `entered`: the keys that were not there. `within`
 * ({ top, bottom }) skips what is off screen before and after; a shift under `shift` px is no move.
 */
export function flipPlan(before, after, { within = null, shift = 1 } = {}) {
  const seen = (r) => !within || (r.bottom > within.top && r.top < within.bottom);
  const moved = [];
  const entered = [];
  for (const [key, to] of after) {
    const from = before.get(key);
    if (!from) { if (seen(to)) entered.push(key); continue; }
    const dx = from.left - to.left;
    const dy = from.top - to.top;
    if ((Math.abs(dx) >= shift || Math.abs(dy) >= shift) && (seen(from) || seen(to))) moved.push({ key, dx, dy });
  }
  return { moved, entered };
}

/**
 * Run `change()` (a re-rank) and glide what moved from its old place over `ms`; what appeared settles in (opacity, a 4 px
 * rise). Children match by `data-key` (renderList), else by identity. `change()` always runs once; nothing animates when
 * the page holds still or `parent` is not on screen. `keys`, when the caller knows them, are the keys `change` leaves
 * there, in order: the ones already there in that order cannot move, so nothing is measured.
 */
export function flip(parent, change, { ms = 180, keys = null } = {}) {
  if (holdStill() || (keys?.length === parent.children.length && keys.every((k, i) => parent.children[i].dataset.key === String(k))) || parent.offsetParent === null) return change(); // offsetParent last: it forces a layout
  const kids = () => new Map([...parent.children].map((el) => [el.dataset.key ?? el, el]));
  const rects = (map) => new Map([...map].map(([key, el]) => [key, el.getBoundingClientRect()]));
  const before = rects(kids()); // where each stands now, a glide under way included
  for (const a of parent.getAnimations({ subtree: true })) if (a.id === "flip") a.cancel(); // the new places are measured clean
  const result = change();
  const now = kids();
  const { moved, entered } = flipPlan(before, rects(now), { within: { top: 0, bottom: innerHeight } });
  const easing = getComputedStyle(document.documentElement).getPropertyValue("--ease").trim() || "ease-out";
  const play = (key, from, to) => now.get(key).animate([from, to], { id: "flip", duration: ms, easing }); // `translate` leaves a hover transform alone
  for (const { key, dx, dy } of moved) play(key, { translate: `${dx}px ${dy}px` }, { translate: "0 0" });
  for (const key of entered) play(key, { opacity: 0, translate: "0 4px" }, { opacity: 1, translate: "0 0" });
  return result;
}

/** Let `el` leave: `.leaving` so the stylesheet can fade it, resolved when its own transition ends (or `ms` plus a margin
    passes); at once when the page holds still or it is already gone. A sheet, a menu or a notice goes through it before it
    is removed, so nothing vanishes mid-frame. */
export function leave(el, { ms = 120 } = {}) {
  if (!el) return Promise.resolve();
  el.classList.add("leaving");
  if (holdStill() || !el.isConnected) return Promise.resolve();
  return new Promise((done) => {
    let over = false;
    const end = (e) => {
      if (over || (e && e.target !== el)) return; // a child's transition is not the element's own
      over = true;
      el.removeEventListener("transitionend", end);
      done();
    };
    el.addEventListener("transitionend", end);
    setTimeout(end, ms + 40);
  });
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
