// A floating sheet over the stage: one dialog at a time; Escape, Back, the scrim or its button close it, and focus returns
// to where it was. The code sheet (a take's snippet) and the Connect sheet are built on it; Transition, Edit with words,
// Dub, Extend and Upscale share the parts below. A sheet leaves the way it came: it fades for 120 ms, but the page behind
// it is live and focus is back the moment it is asked to close, so the fade never holds anything up.

import { titleOf } from "../lib/stages.js";
import { h, icon, leave } from "./dom.js";
import { pill } from "./controls.js";

/** `carried`: the caller flies a frame into this sheet with a view transition, so the sheet does not rise on its own. */
export function openSheet({ title, body, actions = [], label = title, className = "", focusSheet = false, carried = false, onClose }) {
  const close = h("button", { type: "button", class: "btn ghost sm icon-only", "aria-label": "Close" }, icon("x", "sm"));
  const head = h("div", { class: "sheet-head" }, h("h3", null, title), ...actions, close);
  const sheet = h("div", { class: `sheet${className ? ` ${className}` : ""}`, role: "dialog", "aria-modal": "true", "aria-label": label }, head, body);
  const scrim = h("div", { class: `sheet-scrim${carried ? " carried" : ""}` }, sheet);
  const before = document.activeElement;
  const behind = [".app", ".skip"].map((sel) => document.querySelector(sel)).filter(Boolean); // the rooms and the skip link: inert while a sheet is up
  const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); dismiss(); } };
  // the address Back went to stands, whatever onClose writes
  const onPop = () => { const went = location.href; dismiss(); if (location.href !== went) history.replaceState(history.state, "", went); };
  const dismiss = () => {
    if (!scrim.isConnected || scrim.classList.contains("leaving")) return; // a sheet closed twice leaves once
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("popstate", onPop);
    scrim.inert = true; // it answers nothing while it leaves
    leave(scrim).then(() => scrim.remove()); // .leaving fades it; held still, it is gone at once. Asked before onClose, so a throw there cannot strand it
    // the page behind is live and focus is back at once: neither waits for the fade
    if (!document.querySelector(".sheet-scrim:not(.leaving)")) for (const el of behind) el.removeAttribute("inert");
    onClose?.();
    before?.focus?.();
    if (document.activeElement !== before) (document.getElementById("main") ?? document.body).focus({ preventScroll: true }); // the opener is gone
  };
  close.addEventListener("click", dismiss);
  scrim.addEventListener("click", (e) => { if (e.target === scrim) dismiss(); });
  document.addEventListener("keydown", onKey);
  window.addEventListener("popstate", onPop);
  for (const el of behind) el.setAttribute("inert", "");
  document.body.append(scrim);
  if (focusSheet) { sheet.tabIndex = -1; sheet.focus(); } else close.focus();
  return { el: sheet, close: dismiss };
}

/** Replay and the hosted copy render nothing: a sheet there only plays a recording. */
export const isLocked = ({ api, store }) => Boolean(store.get().status?.backend?.locked) || api.kind === "static";

/** The still a sheet works from, beside the take's title. */
export const leaves = (api, take, file, label) => h("div", { class: "transition-from" }, h("img", { src: api.media(take, file), alt: "", draggable: "false" }),
  h("span", null, h("span", { class: "label" }, label), h("b", null, titleOf(take))));

/** A sheet that makes a take from a take: its button plays `recorded()`, else (live) runs `start()`, and the new take
 * opens. Returns say(text, ready) for the note under the `parts` and the button. */
export function takeSheet(ctx, { title, className, parts, label, glyph, recorded, start }) {
  const note = h("p", { class: "hint transition-note" });
  const go = h("button", { type: "button", class: "btn primary" }, icon(glyph), label);
  go.addEventListener("click", async () => {
    go.disabled = true;
    const rec = recorded();
    const out = rec ? await ctx.controller.recreate(rec.id) : isLocked(ctx) ? null : await start();
    if (out) { sheet.close(); ctx.ui.openTake(out.id); } else go.disabled = false;
  });
  const sheet = openSheet({ title, body: h("div", { class: "transition-body" }, parts, note), actions: [go], className });
  return (text, ready) => { note.replaceChildren(text); go.disabled = !ready; };
}
