// Save the shot sheet: a 1600 by 1000 picture of a take as it was planned and made. Three of its frames, the words the
// video model read, the receipt's facts and the camera's path from above. It is drawn in the page, so the hosted copy
// can make one too.
//
// It is printed on card stock, the studio's one light material, because everything on it asserts a fact: the sheet
// someone posts is made of the same paper as the proof pane in the app, torn off down its left edge, with the take's
// keykode running up it. The frames stay emulsion, dark in their own boxes. The accent is spent on one figure.

import { drawStage, planOf } from "../lib/overlay.js";
import { SHEET, sheetFacts, sheetLayout, sheetTimes, stamp, wrap } from "../lib/shotsheet.js";
import { fileOf, titleOf } from "../lib/stages.js";
import { icon, saveAs } from "./dom.js";
import { pageColors, posesFor } from "./overlay.js";

const DISPLAY = `"Barlow Condensed", "Barlow", system-ui, sans-serif`;
const BODY = `"Barlow", system-ui, sans-serif`;
const MONO = `"Overpass Mono", ui-monospace, monospace`;

/** The sheet's own palette: ink on card stock. The frames keep the room's screen black, and the accent is darkened to
    the one that carries on paper (the page's --accent-text is tuned for lacquer, not for a cream sheet). */
function stockColors(css) {
  const t = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
  const ink = t("--card-ink", "#221c16");
  return {
    stock: t("--card-stock", "#ebe3d2"),
    screen: t("--screen", "#050504"),
    grid: "rgb(34 28 22 / 0.14)",
    lineStrong: "rgb(34 28 22 / 0.34)",
    ground: t("--card-stock", "#ebe3d2"),
    text: ink,
    text2: t("--card-ink-2", "#5a5045"),
    text3: "rgb(90 80 69 / 0.8)",
    accent: "#a34806",
    accentText: "#a34806",
    accentSoft: "rgb(163 72 6 / 0.2)",
    accentFill: "#a34806",
    onAccent: t("--card-stock", "#ebe3d2"),
  };
}

const once = (target, type, ms) => new Promise((resolve, reject) => {
  const ac = new AbortController(); // whichever comes first takes the other listeners and the timer with it
  let timer = 0;
  const settle = (fn) => (value) => { ac.abort(); clearTimeout(timer); fn(value); };
  target.addEventListener(type, settle(resolve), { once: true, signal: ac.signal });
  target.addEventListener("error", settle(() => reject(new Error("The take could not be loaded."))), { once: true, signal: ac.signal });
  if (ms) timer = setTimeout(settle(resolve), ms);
});

/** Draw a frame of `video` into `box`, whole (a portrait take sits in the middle of its landscape slot). */
function drawFrame(g, video, box, colors) {
  g.fillStyle = colors.screen;
  g.fillRect(box.x, box.y, box.w, box.h);
  const scale = Math.min(box.w / video.videoWidth, box.h / video.videoHeight);
  const w = video.videoWidth * scale;
  const h = video.videoHeight * scale;
  g.drawImage(video, box.x + (box.w - w) / 2, box.y + (box.h - h) / 2, w, h);
  g.strokeStyle = colors.lineStrong;
  g.lineWidth = 1;
  g.strokeRect(box.x + 0.5, box.y + 0.5, box.w - 1, box.h - 1);
}

/** Make the sheet for `take` (a Direct take whose camera `move` the catalog knows) and save it as a PNG. */
export async function saveShotSheet(ctx, take, move, { link = "" } = {}) {
  const { api, store } = ctx;
  const view = await api.receipt?.(take).catch(() => null);
  const receipt = view?.receipt ?? null;
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.preload = "auto";
  video.style.cssText = "position:fixed;left:0;top:0;width:2px;height:2px;opacity:0;pointer-events:none";
  document.body.append(video);
  try {
    video.src = api.media(take, fileOf(take, "video") ?? "take.mp4");
    await once(video, "loadeddata");
    const canvas = Object.assign(document.createElement("canvas"), { width: SHEET.width, height: SHEET.height });
    const g = canvas.getContext("2d");
    const L = sheetLayout();
    const css = getComputedStyle(document.documentElement);
    const colors = stockColors(css);
    const lacquer = pageColors().ground; // what shows through the sheet's punched edge
    await Promise.all(["800 84px 'Barlow Condensed'", "600 30px 'Barlow Condensed'", "500 26px Barlow", "600 24px Barlow", "600 18px 'Overpass Mono'"]
      .map((font) => document.fonts?.load?.(font).catch(() => null)));

    // the sheet: card stock, torn off down its left edge against the lacquer behind it
    g.fillStyle = lacquer;
    g.fillRect(0, 0, SHEET.width, SHEET.height);
    g.fillStyle = colors.stock;
    g.fillRect(0, 0, SHEET.width, SHEET.height);
    const PERF = { pitch: 34, r: 8, x: 24 }; // clear of the sheet's 56px margin, so no fact sits on the tear
    g.globalCompositeOperation = "destination-out";
    for (let y = PERF.pitch / 2; y < SHEET.height; y += PERF.pitch) {
      g.beginPath();
      g.arc(PERF.x, y, PERF.r, 0, Math.PI * 2);
      g.fill();
    }
    g.globalCompositeOperation = "source-over";
    g.strokeStyle = colors.lineStrong;
    g.lineWidth = 1.5;
    g.beginPath();
    g.moveTo(PERF.x + 22.5, 0);
    g.lineTo(PERF.x + 22.5, SHEET.height);
    g.stroke();
    // the keykode up the torn edge: the same three fields the app prints on every frame
    g.save();
    g.translate(PERF.x - 15, SHEET.height - SHEET.pad);
    g.rotate(-Math.PI / 2);
    g.fillStyle = colors.text3;
    g.font = `500 15px ${MONO}`;
    g.textAlign = "left";
    g.textBaseline = "alphabetic";
    const keyparts = [take.id.replace(/^tk_/, "").replace(/_/g, " ").toUpperCase()];
    if (take.recipe?.seed != null) keyparts.push(`SEED ${take.recipe.seed}`);
    if (receipt?.integrity?.digest) keyparts.push(receipt.integrity.digest.slice(0, 8).toUpperCase());
    g.fillText(keyparts.join("  ▪  "), 0, 0);
    g.restore();

    // the header: the floor-tape T, the studio and the sheet, the take's date
    const { x: hx, y: hy } = L.header;
    g.fillStyle = colors.accent;
    g.fillRect(hx, hy, 40, 8);
    g.fillRect(hx + 16, hy, 8, 24);
    g.fillStyle = colors.text;
    g.font = `600 30px ${DISPLAY}`;
    g.textBaseline = "alphabetic";
    g.textAlign = "left";
    g.fillText("OPENFIELD STUDIO · SHOT SHEET", hx + 58, hy + 25);
    g.textAlign = "right";
    g.fillStyle = colors.text3;
    g.font = `600 18px ${MONO}`;
    const when = take.created_at ? new Date(take.created_at).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" }) : "";
    g.fillText([take.id, when].filter(Boolean).join(" · "), SHEET.width - SHEET.pad, hy + 22);

    // the move and what the shot is
    g.textAlign = "left";
    g.fillStyle = colors.text;
    g.font = `800 ${L.title.size}px ${DISPLAY}`;
    g.fillText(move.label.toUpperCase(), L.title.x, L.title.y);
    g.fillStyle = colors.text2;
    g.font = `500 ${L.subject.size}px ${BODY}`;
    const subject = take.recipe?.subject ?? titleOf(take);
    wrap(subject, L.subject.width, (t) => g.measureText(t).width, 2).forEach((line, n) => g.fillText(line, L.subject.x, L.subject.y + 8 + n * 34));

    // three frames: the start, the middle, the end
    const times = sheetTimes(video.duration);
    for (const [n, box] of L.frames.entries()) {
      video.currentTime = times[n];
      await once(video, "seeked", 5000); // a server without range requests may never seek: draw the frame it has
      drawFrame(g, video, box, colors);
      g.fillStyle = colors.text3;
      g.font = `600 18px ${MONO}`;
      g.fillText(stamp(video.currentTime), box.x, box.y + box.h + 28); // the time of the frame drawn, which a seek that timed out did not reach
    }

    // the words the video model read for the move
    g.fillStyle = colors.text3;
    g.font = `600 16px ${MONO}`;
    g.fillText("WHAT THE VIDEO MODEL READ", L.words.x, L.words.y);
    g.fillStyle = colors.text;
    g.font = `500 ${L.words.size}px ${BODY}`;
    wrap(move.words ?? move.phrase ?? "", L.words.width, (t) => g.measureText(t).width, 7)
      .forEach((line, n) => g.fillText(line, L.words.x, L.words.y + 36 + n * 33));

    // the receipt's facts
    g.fillStyle = colors.text3;
    g.font = `600 16px ${MONO}`;
    g.fillText("THE RECEIPT", L.facts.x, L.facts.y);
    sheetFacts(take, receipt).forEach(([label, value], n) => {
      const y = L.facts.y + 38 + n * 32;
      g.fillStyle = colors.text3;
      g.font = `600 15px ${MONO}`;
      g.fillText(label.toUpperCase(), L.facts.x, y);
      g.fillStyle = label === "Checked" ? colors.accentText : colors.text;
      g.font = label === "Receipt" || label === "Seed" ? `600 19px ${MONO}` : `600 20px ${BODY}`;
      g.fillText(wrap(value, L.facts.width - 120, (t) => g.measureText(t).width, 1)[0] ?? "", L.facts.x + 120, y);
    });

    // the camera's path from above, the whole move travelled
    g.fillStyle = colors.text3;
    g.font = `600 16px ${MONO}`;
    g.fillText("THE CAMERA, FROM ABOVE", L.stage.x, L.stage.y);
    const portrait = video.videoHeight > video.videoWidth;
    const { hollow, anchors } = planOf(move, receipt, take.recipe);
    // the camera most of the way along: on a still picture it would hide the last mark at the very end
    drawStage(g, { poses: posesFor(take, move, store.get().moves), anchors, t: 0.85, hollow, aspect: portrait ? 9 / 16 : 16 / 9,
      box: { x: L.stage.x, y: L.stage.y + 16, w: L.stage.w, h: L.stage.h }, colors, mono: MONO });

    // the footer: where the take lives, and the promise
    g.textAlign = "left";
    g.fillStyle = colors.text3;
    g.font = `600 16px ${MONO}`;
    g.fillText(link.replace(/^https?:\/\//, ""), SHEET.pad, L.footer.y);
    g.textAlign = "right";
    g.fillStyle = colors.text2;
    g.font = `500 20px ${BODY}`;
    g.fillText("Open weights. Every take keeps its receipt.", SHEET.width - SHEET.pad, L.footer.y);

    const blob = await new Promise((done) => canvas.toBlob(done, "image/png"));
    if (!blob?.size) throw new Error("The sheet came out empty.");
    const name = `shot-sheet-${take.id}.png`;
    const url = URL.createObjectURL(blob);
    saveAs(url, name);
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
    return name;
  } finally {
    video.pause();
    video.removeAttribute("src");
    video.load();
    video.remove();
  }
}

/** A button that saves the shot sheet for `take`. */
export function shotSheetButton(ctx, take, move, { className = "btn secondary", link = "", onError = null } = {}) {
  const label = "Save the shot sheet";
  const text = document.createElement("span");
  text.textContent = label;
  const button = document.createElement("button");
  button.type = "button";
  button.className = `${className} save-sheet`;
  button.title = "One picture of the take: frames, path and receipt.";
  button.append(icon("image", className.includes(" sm") ? "sm" : undefined), text);
  button.addEventListener("click", async () => {
    button.disabled = true;
    text.textContent = "Drawing the sheet…";
    try {
      await saveShotSheet(ctx, take, move, { link });
      text.textContent = "Saved";
      setTimeout(() => { text.textContent = label; }, 2400);
    } catch (error) {
      text.textContent = label;
      onError?.(error?.message ?? "This browser could not draw it.");
    } finally {
      button.disabled = false;
    }
  });
  return button;
}
