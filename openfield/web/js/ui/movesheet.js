// A camera move on a page of its own: the take that shows it, beside the set seen from above with the camera travelling
// the move's path in step with the take; what the video model is told and what it keeps still; the take's billing; and a
// way to direct it. The arrows walk the gallery. The address bar carries the move, so the page can be shared. Opened from
// a gallery card, the page is flown in from that card's frame by a view transition.

import { h, icon } from "./dom.js";
import { openSheet } from "./sheet.js";
import { createStageView } from "./stageview.js";
import { loadTake, notify } from "./actions.js";
import { canSaveWithPath, savePathButton } from "./overlay.js";
import { claimSlot, freeSlot, previewOf } from "./wall.js";
import { billing, gpuCost, gpuSeconds } from "../lib/billing.js";
import { fileOf } from "../lib/stages.js";
import { moveDeck, stepIn } from "../lib/deck.js";
import { movePageUrl } from "../lib/shareurls.js";
import { holdStill } from "../lib/motion.js";

const HOW = {
  prompt_only: "One approved still, then the move.",
  keyframed: (n) => `${n} approved stills, one at each mark, then the move.`,
};
const flights = new WeakMap(); // a card's frame -> the flight that last named it (the same card can be opened again mid-flight)

/** `from`: the gallery frame the page was opened from, when a card opened it (an address or a link passes none). */
export function openMoveSheet(ctx, firstId, { ids = [], from = null } = {}) {
  const { store, api, ui } = ctx;
  const isStatic = api.kind === "static";
  const body = h("div", { class: "move-sheet" });
  const prev = h("button", { type: "button", class: "btn ghost sm icon-only", "aria-label": "Previous move", title: "Previous move (Left arrow)" }, icon("chevron-left", "sm"));
  const next = h("button", { type: "button", class: "btn ghost sm icon-only", "aria-label": "Next move", title: "Next move (Right arrow)" }, icon("chevron-right", "sm"));
  const copy = h("button", { type: "button", class: "btn ghost sm" }, icon("link", "sm"), h("span", null, "Copy link"));
  // the gallery's moves in its order: the Lobby's list, else (a shared link opens before the previews, with the gallery still empty) the same from the store
  const deck = () => (ids.length ? ids : moveDeck(store.get().moves, store.get().previews).map((m) => m.id));
  let video = null;
  let raf = 0;
  let current = null;
  let closed = false; // set when the page closes: a flight's update step may still be waiting for its frame
  // carried: the card's frame flies to the page's own. Held still, or with no View Transitions, the page just opens
  const carried = Boolean(from?.isConnected && document.startViewTransition && !holdStill());
  delete document.body.dataset.dir; // a page opens in place: only a walk comes in from a side

  const release = () => {
    cancelAnimationFrame(raf);
    raf = 0;
    if (!video) return;
    freeSlot(video);
    video.pause();
    video.removeAttribute("src");
    video.load();
    video = null;
  };
  const sheet = openSheet({ title: "Camera move", body, actions: [prev, next, copy], className: "sheet-move", focusSheet: true, carried,
    onClose: () => {
      closed = true;
      release();
      stopWaiting();
      sheet.el.removeEventListener("keydown", onKey);
      delete document.body.dataset.dir;
      if (/^#\/lobby\//.test(location.hash)) history.replaceState(null, "", "#/lobby");
    } });
  const title = sheet.el.querySelector(".sheet-head h3");

  // an address for a move this studio does not have: say so, close the page, and put the address bar back at the Lobby
  function noSuchMove(id) {
    waiting = null;
    notify(ctx, "No such camera move.", id, "info");
    sheet.close(); // which swaps #/lobby in with replaceState, so Back never returns to the bad address
    if (location.hash !== "#/lobby") location.hash = "#/lobby";
  }

  function paint(id) {
    const s = store.get();
    const move = s.moves?.moves.find((m) => m.id === id);
    if (s.loaded && s.moves && !move) return noSuchMove(id); // the catalog is here and has no such move
    // a move this copy has no take for still keeps its name on the page
    if (move) title.replaceChildren(move.label, h("span", { class: "move-title-group" }, ` · ${move.group_label}`));
    const takeId = s.previews?.moves?.[id];
    const take = (s.recorded ?? []).find((t) => t.id === takeId) ?? s.takes.find((t) => t.id === takeId) ?? null;
    copy.disabled = !take; // no take, nothing to share
    prev.hidden = next.hidden = deck().length < 2; // arrows only with another move to walk to
    if (!move || !take) {
      // a shared link opens the page before the catalog and the previews have loaded: it waits for them and paints then
      const loading = !s.loaded || !s.moves || s.previews === null; // null: not answered yet; false: this copy has none
      release();
      body.replaceChildren(h("p", { class: "hint" }, loading ? "Loading the take…" : "This copy has no recorded take for that move."));
      waiting = loading ? id : null;
      return;
    }
    waiting = null;
    release();
    current = id;
    history.replaceState(null, "", `#/lobby/${id}`);
    const clip = previewOf(s, take, api, { width: 1000 });
    const file = fileOf(take, "video");
    video = h("video", { class: "move-take", muted: true, loop: true, playsinline: true, preload: "auto", "aria-label": `The recorded take: ${move.label}`,
      poster: clip?.poster ?? null, disablepictureinpicture: true });
    video.muted = true;
    if (file || clip) video.src = file ? api.media(take, file) : clip.video;

    // how this take was shot: a keyframed move shot in quick mode (prompt_only) rendered from one still too, and the
    // stage draws it that way, the camera dashed with no marks along the way
    const oneStill = move.mode !== "keyframed" || Boolean(take.recipe?.prompt_only);
    const how = oneStill ? HOW.prompt_only : HOW.keyframed(move.anchors ?? 2);
    const stage = createStageView(move, { hollow: oneStill, label: `The camera's path for ${move.label}, from above.` });
    const follow = () => {
      raf = 0;
      if (!video || !(video.duration > 0)) return;
      stage.seek(video.currentTime / video.duration);
      if (!video.paused) raf = requestAnimationFrame(follow);
    };
    video.addEventListener("play", () => { raf ||= requestAnimationFrame(follow); });
    video.addEventListener("seeked", follow);
    const play = h("button", { type: "button", class: "btn secondary sm move-play", hidden: !holdStill() },
      icon("play", "sm"), h("span", null, "Play"));
    play.addEventListener("click", () => { play.hidden = true; claimSlot(video, { pin: true }); video.play().catch(() => {}); });
    video.addEventListener("pause", () => { if (video?.isConnected) play.hidden = false; }); // paused for any reason: Play is there
    video.addEventListener("play", () => { play.hidden = true; });

    const row = ([label, value]) => h("div", null, h("dt", null, label), h("dd", { class: label === "Audit" ? null : "num" }, value));
    const bill = h("dl", { class: "move-billing" }, billing(take, s.moves).map(row));
    // the GPU time and its price, once the receipt has come (it is the receipt that recorded them)
    api.receipt?.(take).then((view) => {
      const gpu = gpuSeconds(view?.receipt);
      if (gpu > 0 && current === id) bill.append(row(["GPU", `${Math.round(gpu)} s`]), row(["Cost", `≈ ${gpuCost(gpu)}`]));
    }).catch(() => {});
    const direct = h("button", { type: "button", class: "btn primary lg" }, icon("clapperboard"), h("span", null, "Direct this move"));
    direct.addEventListener("click", () => { sheet.close(); loadTake(ctx, take); });
    const open = h("button", { type: "button", class: "btn secondary lg" }, icon("film"), h("span", null, "Open the take"));
    open.addEventListener("click", () => {
      sheet.close();
      history.pushState(null, "", `#/takes/${take.id}`);
      ui.openTake(take.id);
    });
    // the take with its planned camera drawn in a corner, as a file to post (recorded in the page)
    const withPath = canSaveWithPath() && move.path?.length
      ? savePathButton(ctx, take, move, { className: "btn secondary lg", onError: (why) => notify(ctx, "Could not save the video.", why, "error"),
        onSaved: (name) => notify(ctx, "Saved.", name, "info") }) : null; // a save that ends after the page closed still says so
    body.replaceChildren(
      h("div", { class: "move-main" },
        h("figure", { class: "move-footage" }, video, play),
        h("div", { class: "move-words" },
          h("h4", null, "The direction"),
          h("p", { class: "move-phrase" }, move.words ?? move.phrase),
          h("h4", null, "How this take was shot"),
          h("p", null, how))),
      h("div", { class: "move-side" },
        h("figure", { class: "move-plan" }, stage.el, h("figcaption", null, "The camera's path from above. It moves with the take.")),
        bill),
      h("div", { class: "move-actions" }, direct, open, withPath));
    if (!holdStill()) {
      claimSlot(video, { pin: true }); // the loops behind the sheet never take its decoder
      video.play().catch(() => { play.hidden = false; });
    }
  }

  // repaint the move a shared link asked for once its take is known (the previews come after the first paint)
  let waiting = null;
  const stopWaiting = store.subscribe((state, changed) => {
    if (waiting && changed.some((k) => ["loaded", "moves", "previews", "recorded"].includes(k))) paint(waiting);
  });
  // the arrows wrap around the gallery; the side walked towards goes on the page, and the stylesheet brings the new move in from it
  const walk = (delta) => {
    const id = stepIn(deck(), current, delta);
    if (!id || id === current) return;
    document.body.dataset.dir = delta > 0 ? "next" : "prev";
    paint(id);
  };
  const onKey = (e) => {
    if (e.target.closest?.("input,textarea,select")) return;
    if (e.key === "ArrowLeft") { e.preventDefault(); walk(-1); }
    if (e.key === "ArrowRight") { e.preventDefault(); walk(1); }
  };
  sheet.el.addEventListener("keydown", onKey);
  prev.addEventListener("click", () => walk(-1));
  next.addEventListener("click", () => walk(1));
  copy.addEventListener("click", async () => {
    const url = movePageUrl(current, { isStatic, href: location.href });
    try {
      await navigator.clipboard.writeText(url);
      copy.lastChild.textContent = "Copied";
    } catch {
      copy.lastChild.textContent = "Copy failed";
    }
    setTimeout(() => { copy.lastChild.textContent = "Copy link"; }, 1800);
  });
  // The flight: the card's frame is named move-frame while the browser takes its picture, then the page is painted (in the
  // transition's update step, so the frame has somewhere to land) and the name moves to the page's take frame: one name may
  // stand once in each state, so the card gives it up first. The browser carries the one picture into the other. Both come
  // off in `finished`, whether the flight ended, was skipped, or the page was closed in it.
  const name = (el, on) => (on ? el?.style.setProperty("view-transition-name", "move-frame") : el?.style.removeProperty("view-transition-name"));
  function fly() {
    let landing = null;
    const mine = {};
    flights.set(from, mine);
    const giveUp = () => { if (flights.get(from) === mine) name(from, false); }; // an older flight, skipped by a newer one, leaves the name alone
    name(from, true);
    let flight = null; // set before the update step can run, which the browser defers past the capture
    flight = document.startViewTransition(() => {
      giveUp();
      if (closed) { flight?.skipTransition(); return; } // closed before its first frame: nothing to land on, and nothing to paint
      paint(firstId);
      landing = body.querySelector(".move-footage"); // the frame that holds video.move-take
      name(landing, true);
    });
    flight.ready.catch(() => {}); // skipped by a later transition: the page is painted all the same
    flight.finished.catch(() => {}).then(() => { giveUp(); name(landing, false); });
  }
  if (carried) fly();
  else paint(firstId);
  return sheet;
}
