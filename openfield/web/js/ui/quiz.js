// "Name the move": one loop at a time, four names, a score to share. It plays in the Lobby; at the end it draws a score
// card (a picture of the result) to save or send. A right name pings and a wrong one dulls, when the studio's sound is on.

import { buildQuiz, dailyQuiz, dailyShareText, dayLabel, nextRecord, quizDay, scoreLine, shareText, squares, validDay, xIntent } from "../lib/quiz.js";
import { h, icon, saveAs } from "./dom.js";
import { play as cue } from "./sound.js";
import { claimSlot, freeSlot, previewOf } from "./wall.js";
import { fileOf } from "../lib/stages.js";
import { holdStill } from "../lib/motion.js";

const DAY_KEY = "openfield.quiz-day";
const readDay = () => { try { return validDay(JSON.parse(localStorage.getItem(DAY_KEY) ?? "null")); } catch { return null; } };
const saveDay = (record) => { try { localStorage.setItem(DAY_KEY, JSON.stringify(record)); } catch { /* a private window: today still shows */ } return record; };
const button = (label, cls, fn, glyph = null) => h("button", { type: "button", class: cls, onclick: fn }, glyph ? icon(glyph, "sm") : null, label);
const onPhone = () => Boolean(globalThis.matchMedia?.("(max-width: 719px)")?.matches);

/** A score hangs in like the marquee's letters: a span a character for the eye (aria-hidden, `--i` its place in the stagger),
 * and one sr-only span that says the line whole. Held still, the stylesheet leaves the spans where they are. */
const hang = (text, from = 0) => [...text].map((c, i) => h("span", { class: "quiz-ch", "aria-hidden": "true", style: { "--i": from + i } }, c));
const scoreEl = (line, marks = "") => h("p", { class: "quiz-score num" }, h("span", { class: "sr-only" }, line), hang(line),
  marks ? h("span", { class: "quiz-squares", "aria-hidden": "true" }, " ", hang(marks, line.length)) : null);

/** The quiz in a box: `el` to place anywhere, `start` to deal ten rounds, `stop` to let its video go. */
export function createQuiz(ctx, { onLeave = null } = {}) {
  const { store, api, ui } = ctx;
  let rounds = [], at = 0, correct = 0, media = null, results = [];
  let daily = true; // today's five, the same for everyone; else ten at random
  let day = quizDay();
  const move = (id) => store.get().moves?.moves.find((m) => m.id === id);
  const el = h("div", { class: "quiz" });

  function release() {
    if (!media) return;
    freeSlot(media);
    media.pause();
    media.removeAttribute("src");
    media.load();
    media = null;
  }

  function stage(r) {
    release();
    const s = store.get();
    const clip = previewOf(s, { id: r.takeId }, api, { width: 700 });
    const box = h("div", { class: "quiz-stage" });
    if (!clip) {
      box.append(h("p", { class: "hint" }, "No loop for this round."));
      return box;
    }
    // the whole take when this copy has it (sharper, and the move from its start to its end), else the short loop; a phone
    // always gets the loop (the take is several MB a round), its sharper copy on a dense screen
    const take = (s.recorded ?? []).find((t) => t.id === r.takeId);
    const file = take && !onPhone() ? fileOf(take, "video") : null;
    const src = file ? api.media(take, file) : clip.video;
    const video = () => h("video", { muted: true, loop: true, playsinline: true, poster: clip.poster, src, "aria-label": "The camera move to name" });
    if (!holdStill()) {
      const clipEl = (media = video());
      box.append(clipEl);
      claimSlot(clipEl, { pin: true });
      // reduced motion turned on mid-round pauses the clip (the wall's rule): a Play button lets the round go on
      clipEl.addEventListener("pause", () => {
        if (!holdStill() || box.querySelector(".quiz-play")) return;
        const again = button("Play", "btn primary sm quiz-play", () => { again.remove(); claimSlot(clipEl, { pin: true }); clipEl.play().catch(() => {}); }, "play");
        box.append(again);
      });
    } else {
      box.append(h("img", { src: clip.poster, alt: "" }), button("Play", "btn primary sm quiz-play",
        () => { box.replaceChildren((media = video())); claimSlot(media, { pin: true }); media.play().catch(() => {}); }, "play"));
    }
    return box;
  }

  function answer(r, picked, choices, reveal) {
    const m = move(r.answer), label = m?.label ?? r.answer, right = picked.dataset.id === r.answer;
    cue(right ? "ping" : "dull");
    if (right) correct++;
    results.push({ label, right });
    for (const b of choices.children) {
      b.disabled = true;
      const word = b.dataset.id === r.answer ? "Correct" : b === picked ? "Not this one" : null;
      if (word) { b.dataset.state = b.dataset.id === r.answer ? "right" : "wrong"; b.append(h("span", { class: "quiz-mark" }, word)); }
    }
    const next = button(at === rounds.length - 1 ? "See the score" : "Next", "btn primary", () => { at++; paint(); });
    const open = button("Open the take", "btn secondary", () => {
      onLeave?.();
      history.pushState(null, "", `#/takes/${r.takeId}`);
      ui.openTake?.(r.takeId);
    });
    reveal.hidden = false;
    reveal.replaceChildren(
      h("p", { class: "quiz-verdict" }, right ? `Right. ${label}.` : `It was ${label}.`),
      h("div", { class: "quiz-actions" }, next, open));
    next.focus({ preventScroll: true });
  }

  function paint() {
    const r = rounds[at];
    if (!r) return end();
    const reveal = h("div", { class: "quiz-reveal", hidden: true });
    const choices = h("div", { class: "quiz-choices" },
      r.choices.map((id) => h("button", { type: "button", class: "btn secondary quiz-choice", "data-id": id, onclick: (e) => answer(r, e.currentTarget, choices, reveal) }, move(id)?.label ?? id)));
    el.replaceChildren(stage(r), h("div", { class: "quiz-side" },
      h("p", { class: "quiz-count num" }, daily ? `Today's five · ${at + 1} of ${rounds.length}` : `Round ${at + 1} of ${rounds.length}`, h("span", { class: "quiz-tally" }, ` · ${correct} right`)),
      choices, reveal));
    if (seen) media?.play?.().catch(() => {});
  }

  function end() {
    release();
    if (!rounds.length) return el.replaceChildren(h("p", { class: "hint" }, "This copy has no recorded camera moves to play with yet."));
    if (daily) return showDay(saveDay(nextRecord(readDay(), day, results)));
    const site = `${location.origin}${location.pathname}${location.search}`;
    const share = h("a", { class: "btn primary", href: xIntent(shareText(correct, rounds.length), site), target: "_blank", rel: "noopener noreferrer" },
      icon("send", "sm"), "Post your score");
    const card = button("Save the score card", "btn secondary", () => saveCard(results, correct, site), "image");
    const today = readDay()?.day === day ? null : button("Today's five", "btn secondary", () => start("daily"), "clock");
    el.replaceChildren(h("div", { class: "quiz-end" },
      scoreEl(scoreLine(correct, rounds.length)),
      resultList(results),
      h("div", { class: "quiz-actions" }, share, card, button("Play ten more", "btn secondary", () => start("random"), "refresh-cw"), today)));
  }

  const resultList = (list) => h("ol", { class: "quiz-results" }, list.map((x) => h("li", { "data-state": x.right ? "right" : "wrong" },
    icon(x.right ? "check" : "x", "sm"), h("span", null, x.label), h("span", { class: "sr-only" }, x.right ? " (right)" : " (missed)"))));

  // today's five, played once a day: the result and the streak stay in this browser until tomorrow's five
  function showDay(record) {
    const site = `${location.origin}${location.pathname}${location.search}`;
    const list = record.results ?? [];
    const share = h("a", { class: "btn primary", href: xIntent(dailyShareText(record.day, list), site), target: "_blank", rel: "noopener noreferrer" },
      icon("send", "sm"), "Post today's score");
    const card = button("Save the score card", "btn secondary", () => saveCard(list, record.correct, site, { when: dayLabel(record.day) }), "image");
    const streak = record.streak > 1 ? `${record.streak} days in a row` : "Day one of a streak";
    el.replaceChildren(h("div", { class: "quiz-end" },
      h("p", { class: "quiz-day" }, `Today's five · ${dayLabel(record.day)}`),
      scoreEl(scoreLine(record.correct, record.total), squares(list)),
      h("p", { class: "quiz-streak" }, `${streak}. Five new clips tomorrow.`),
      resultList(list),
      h("div", { class: "quiz-actions" }, share, card, button("Play ten at random", "btn secondary", () => start("random"), "refresh-cw"))));
  }

  function start(mode = "daily") {
    const s = store.get();
    daily = mode === "daily";
    day = quizDay();
    if (daily && readDay()?.day === day && s.previews) { // played today already: the result, not the same five again
      rounds = [true];
      return showDay(readDay());
    }
    rounds = daily ? dailyQuiz({ moves: s.moves?.moves ?? [], previews: s.previews, day })
      : buildQuiz({ moves: s.moves?.moves ?? [], previews: s.previews, seed: Date.now() });
    at = correct = 0;
    results = [];
    paint();
  }

  // the loop plays only while the quiz is on screen; scrolled away it rests (a hidden tab is the wall's shared rule)
  let seen = true;
  if (globalThis.IntersectionObserver) {
    new IntersectionObserver((entries) => {
      seen = entries.some((e) => e.isIntersecting);
      if (!media) return;
      if (seen && !holdStill() && !document.hidden) { claimSlot(media, { pin: true }); media.play().catch(() => {}); }
      else { freeSlot(media); media.pause(); } // scrolled away, it gives its decoder back to the galleries
    }, { rootMargin: "80px 0px" }).observe(el);
  }
  const playIfSeen = () => { if (media && seen && !holdStill()) { claimSlot(media, { pin: true }); media.play().catch(() => {}); } };

  // leaving marks what the quiz has shown: a room shown again restarts animations and first-paint transitions, and these stand
  const stop = () => { release(); for (const node of el.querySelectorAll(".quiz-stage, .quiz-side, .quiz-reveal, .quiz-score")) node.classList.add("seen"); };
  return { el, start, stop, wake: playIfSeen };
}

/** The score card: a 1080 by 1350 picture of the result in the lobby's own type, saved or handed to the phone's share. */
async function saveCard(results, correct, site, { when = null } = {}) {
  const W = 1080, H = 1350, pad = 84;
  const canvas = Object.assign(document.createElement("canvas"), { width: W, height: H });
  const c = canvas.getContext("2d");
  try { await Promise.all(["800 120px 'Barlow Condensed'", "600 44px 'Barlow Condensed'", "500 36px Barlow", "400 40px 'Overpass Mono'"].map((f) => document.fonts.load(f))); } catch { /* the fallbacks draw */ }
  const css = getComputedStyle(document.documentElement);
  const tone = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
  const ground = tone("--ground", "#0d0c0b"), text = tone("--text", "#ebe8e3"), dim = tone("--text-3", "#908a82");
  const orange = tone("--accent", "#ff7a1a"), brass = tone("--brass-hi", "#d6b77f"), red = tone("--red", "#f0625f");
  c.fillStyle = ground;
  c.fillRect(0, 0, W, H);
  c.strokeStyle = brass;
  c.lineWidth = 2;
  c.strokeRect(36, 36, W - 72, H - 72);
  // the floor-tape T, then the title and the score
  c.fillStyle = orange;
  c.fillRect(pad, pad + 6, 48, 9);
  c.fillRect(pad + 19.5, pad + 6, 9, 27);
  c.fillStyle = text;
  c.font = "600 44px 'Barlow Condensed', sans-serif";
  c.fillText("OPENFIELD STUDIO", pad + 70, pad + 34);
  c.font = "800 128px 'Barlow Condensed', sans-serif";
  c.fillText("NAME THE MOVE", pad, pad + 220);
  if (when) { // today's five: the date, so a card says which day's clips it scored
    c.fillStyle = orange;
    c.font = "600 44px 'Barlow Condensed', sans-serif";
    c.fillText(`TODAY'S FIVE · ${when.toUpperCase()}`, pad, pad + 286);
  }
  c.font = "400 220px 'Overpass Mono', monospace";
  c.fillStyle = orange;
  c.fillText(scoreLine(correct, results.length), pad - 8, pad + 470);
  // one line per round, with a drawn mark: a tick for right, a cross for missed
  c.font = "500 40px Barlow, sans-serif";
  results.forEach((x, i) => {
    const y = pad + 560 + i * 58;
    c.strokeStyle = x.right ? brass : red;
    c.lineWidth = 5;
    c.beginPath();
    if (x.right) { c.moveTo(pad, y - 12); c.lineTo(pad + 12, y); c.lineTo(pad + 34, y - 26); }
    else { c.moveTo(pad + 2, y - 26); c.lineTo(pad + 28, y); c.moveTo(pad + 28, y - 26); c.lineTo(pad + 2, y); }
    c.stroke();
    c.fillStyle = x.right ? text : dim;
    c.fillText(x.label, pad + 58, y);
  });
  c.fillStyle = dim;
  c.font = "500 34px Barlow, sans-serif";
  c.fillText("Camera moves made with open weights.", pad, H - pad - 48);
  c.font = "400 30px 'Overpass Mono', monospace";
  c.fillText(site.replace(/^https?:\/\//, "").replace(/\/$/, ""), pad, H - pad);
  const blob = await new Promise((done) => canvas.toBlob(done, "image/png"));
  if (!blob) return;
  const file = new File([blob], "openfield-score.png", { type: "image/png" });
  if (navigator.canShare?.({ files: [file] })) {
    try { await navigator.share({ files: [file], text: shareText(correct, results.length) }); return; } catch { /* closed: save instead */ }
  }
  const url = URL.createObjectURL(blob);
  saveAs(url, file.name);
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}
