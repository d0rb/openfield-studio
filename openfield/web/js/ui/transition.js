// Transition: one LTX 2.5 render from the last frame of one take to the first frame of another, on the same
// first-last-frame path the keyframed moves use; the new take plays the first take, the bridge and the second.
// How it gets there (optional) gives the bridge a path to render.

import { fileOf, fromRecorded, posterAttrs, titleOf } from "../lib/stages.js";
import { bridgeRequest, recordedBridge } from "../lib/edit.js";
import { h, icon } from "./dom.js";
import { field, segmented, textField } from "./controls.js";
import { hoverClip, hoverPlay } from "./hoverplay.js";
import { isLocked, leaves, takeSheet } from "./sheet.js";

const idOf = (t) => t.replay_of ?? t.id;

export function openTransitionSheet(ctx, from) {
  const { api, store, controller } = ctx;
  const state = store.get();
  const catalog = state.moves?.transitions;
  if (!catalog) return null;
  const locked = isLocked(ctx);
  const first = idOf(from);
  const recordings = state.recorded.filter((r) => r.kind === "transition" && r.recipe?.first === first);
  const seen = new Set([first]);
  const candidates = [...state.takes, ...state.recorded.map(fromRecorded)]
    .filter((t) => t.status === "succeeded" && ["direct", "reshoot"].includes(t.kind) && fileOf(t, "poster"))
    .filter((t) => !seen.has(idOf(t)) && seen.add(idOf(t)))
    // in Replay only a recorded bridge can play: those landing takes lead
    .sort((a, b) => Number(recordings.some((r) => r.recipe?.second === idOf(b))) - Number(recordings.some((r) => r.recipe?.second === idOf(a))));
  const pick = recordings[0]?.recipe;
  let to = pick?.second ?? (locked ? null : idOf(candidates[0] ?? {}) ?? null);
  let style = pick?.style ?? catalog.default;
  let seconds = pick?.seconds ?? catalog.seconds[0];
  let idea = pick?.idea ?? "";
  const recorded = () => recordedBridge(recordings, { first, second: to, style, seconds, idea });
  // Replay plays only recorded bridges, and an idea cannot be guessed: a recorded choice brings its idea
  const near = () => recordings.find((r) => r.recipe?.second === to && r.recipe?.style === style && r.recipe?.seconds === seconds)?.recipe;
  const adopt = (r) => { if (locked && r) { styles.set(style = r.style); lengths.set(seconds = r.seconds); words.set(idea = r.idea ?? ""); } };

  const grid = h("div", { class: "transition-pick", role: "radiogroup", "aria-label": "Lands on" });
  const styles = segmented({ label: "Style", options: catalog.styles.map((s) => ({ value: s.id, label: s.label })), value: style, onChange: (v) => { style = v; adopt(near()); paint(); } });
  const lengths = segmented({ label: "Length", options: catalog.seconds.map((n) => ({ value: n, label: `${n} s` })), value: seconds, onChange: (v) => { seconds = Number(v); adopt(near()); paint(); } });
  const words = textField({ id: "transition-idea", multiline: true, rows: 2, value: idea, maxlength: catalog.idea_max ?? 240, placeholder: "The camera flies into the dragon's fire and comes out of a lava wave.", onInput: (v) => { idea = v; note(); } });
  const say = takeSheet(ctx, { title: "Transition", className: "sheet-transition", label: locked ? "Play the recorded transition" : "Render the transition", glyph: "arrow-left-right",
    parts: [leaves(api, from, fileOf(from, "poster"), "Leaves"), field("Lands on", grid, { id: "transition-to" }).el, field("Style", styles.el, { id: "transition-style" }).el,
      field("How it gets there (optional)", words.el, { id: "transition-idea", hint: "Say how one scene becomes the other." }).el,
      field("Length", lengths.el, { id: "transition-length" }).el],
    recorded: () => (locked ? recorded() : null), start: () => controller.startTransition(bridgeRequest({ first, second: to, style, seconds, idea })) });

  function paint() {
    grid.replaceChildren(...candidates.slice(0, 18).map((t) => {
      const b = h("button", { type: "button", role: "radio", class: "transition-option", "aria-checked": String(idOf(t) === to), title: titleOf(t) },
        h("img", { ...posterAttrs(state, t, api, "96px"), alt: titleOf(t), loading: "lazy", draggable: "false" }),
        recordings.some((r) => r.recipe?.second === idOf(t)) ? h("span", { class: "transition-has", "aria-hidden": "true" }, icon("arrow-left-right", "sm")) : null);
      b.addEventListener("click", () => { to = idOf(t); adopt(near() ?? recordings.find((r) => r.recipe?.second === to)?.recipe); paint(); });
      hoverPlay(b, hoverClip(store, t, api)); // a landing take plays under the hand before it is picked
      return b;
    }));
    note();
  }
  function note() { // typing an idea repaints only this, not the landing takes
    const rec = recorded();
    const short = bridgeRequest({ idea }).idea?.length < 3; // 3 to idea_max characters, or none
    say(locked ? (rec ? "Replay plays this recorded transition." : "Recorded takes only. Connect a backend to render.")
      : short ? "Say how it gets there, or leave it empty." : `Renders ${seconds} s between the two takes.`, to && (locked ? rec : !short));
  }
  paint();
}
