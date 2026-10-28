// The Lobby's reveal: what comes into view rises. A list's items rise one after another as they cross into the view, so
// the wave follows the person down the page (and along a rail) instead of spending itself below the fold; a section head
// rises on its own. An item rises once: when its rise ends (or its room is hidden mid-rise) it is done, so a room shown
// again never replays it. Nothing is hidden while motion is held, and nothing waits on a timer.

import { holdStill, onMotionChange } from "../lib/motion.js";

const STEPS = 7; // the wave's reach: the eighth item that came into view and every one after it rise together
const NAMES = new Set(["lobby-rise", "lobby-lift"]); // the rises this module starts (lobby.css)
const lists = new Set(); // every list armed, and every head armed on its own
const begun = new WeakSet(); // lists that have started to rise: a child added later joins without a second wave
let view = null; // the one IntersectionObserver
let late = null; // the one MutationObserver: children a list gains after it was armed

/** The wave: the items that came into view together, in the page's order, each a step after the one before. */
export function wave(items, before = (a, b) => (a.compareDocumentPosition(b) & 4 ? -1 : 1)) {
  return [...items].sort(before).map((el, i) => [el, Math.min(i, STEPS)]);
}

/** Whether a child added to a list that has begun still waits its turn: only one ahead of the view does (below the line
    the reveal watches, or past the right edge of a rail). A hidden room measures zeros: its new children count as seen. */
export const ahead = (rect, width, height) => rect.top >= height * 0.92 || rect.left >= width;

const done = (el) => {
  el.classList.add("in", "done");
  view?.unobserve(el);
};
const listOf = (el) => (el.classList.contains("armed-self") ? el : el.parentElement);

function seen(entries) {
  // an entry queued for an item its list has since replaced still arrives: it is skipped, not shown (its list would be null)
  const now = entries.filter((e) => e.isIntersecting && e.target.isConnected !== false && !e.target.classList.contains("in")).map((e) => e.target);
  for (const [el, i] of wave(now)) {
    el.style.setProperty("--i", String(i));
    el.classList.add("in");
    view.unobserve(el);
    const list = listOf(el);
    if (list) begun.add(list);
  }
}

// a rise that ends, or is cut off because its room was hidden, leaves the item done: shown again, it stays still
function ended(e) {
  const el = e.target;
  if (NAMES.has(e.animationName) && (el === e.currentTarget || el.parentElement === e.currentTarget)) el.classList.add("done");
}

function joined(records) {
  for (const r of records) {
    let risen = [...r.removedNodes].filter((n) => n.classList?.contains("in")).length; // places the list had shown
    for (const n of r.removedNodes) if (n.nodeType === 1) view.unobserve(n);
    for (const n of r.addedNodes) {
      if (n.nodeType !== 1) continue;
      // a list that has begun shows a new child at once (no second wave) in a place it had shown, or one not ahead of the view
      if (holdStill() || (begun.has(r.target) && (risen-- > 0 || !ahead(n.getBoundingClientRect(), globalThis.innerWidth, globalThis.innerHeight)))) done(n);
      else view.observe(n);
    }
  }
}

/** Arm `list` so its children rise as each comes into view (`self`: the element rises on its own, as a head does).
    Under reduced motion or Save-Data nothing is armed, so nothing is ever hidden. */
export function rise(list, { self = false } = {}) {
  if (!list || holdStill() || !globalThis.IntersectionObserver || !globalThis.MutationObserver) return;
  view ??= new IntersectionObserver(seen, { rootMargin: "0px 0px -8% 0px" });
  late ??= new MutationObserver(joined);
  lists.add(list);
  list.classList.add(self ? "armed-self" : "armed");
  list.addEventListener("animationend", ended);
  list.addEventListener("animationcancel", ended);
  if (self) {
    view.observe(list);
    return;
  }
  for (const el of list.children) view.observe(el);
  late.observe(list, { childList: true });
}

/** Show `list` as it stands, with no rise: every child (a head: itself) is done. A gallery's filter change calls it
    before its own reflow, so choosing a filter is never a reveal. */
export function settle(list) {
  if (!list) return;
  begun.add(list);
  for (const el of list.classList.contains("armed-self") ? [list] : [...list.children]) done(el);
}

// motion held while the page is open (reduced motion turned on): everything still waiting is shown at once
onMotionChange(() => {
  if (holdStill()) for (const list of lists) settle(list);
});
