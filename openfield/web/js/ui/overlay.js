// Save a take with its planned camera: the footage plays into a canvas with the stage in a corner, the camera travelling
// its path in step, the move's name and the models over it, and the browser records the canvas and the take's own sound.
// It runs in the page, so the hosted copy can do it too. Recording takes as long as the take plays.

import { angleGeometry } from "../lib/direct.js";
import { drawStage, firstThatRecords, overlayLayout, overlayName, planOf, recordingType, recordingTypes } from "../lib/overlay.js";
import { withAngle } from "../lib/pathview.js";
import { fileOf } from "../lib/stages.js";
import { icon, saveAs, setText } from "./dom.js";

/** Whether this browser can record a canvas with sound. */
export const canSaveWithPath = () => typeof globalThis.MediaRecorder === "function" && typeof globalThis.HTMLCanvasElement === "function"
  && "captureStream" in HTMLCanvasElement.prototype && Boolean(globalThis.AudioContext ?? globalThis.webkitAudioContext) && recordingType() !== null;

const once = (target, type) => new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error("The take took too long to load. Try again.")), 8000);
  target.addEventListener(type, (e) => { clearTimeout(timer); resolve(e); }, { once: true });
  target.addEventListener("error", () => { clearTimeout(timer); reject(new Error("The take could not be loaded.")); }, { once: true });
});
const even = (n) => Math.max(2, Math.round(n / 2) * 2);
const DISPLAY = `"Barlow Condensed", "Barlow", system-ui, sans-serif`;
const MONO = `"Overpass Mono", ui-monospace, monospace`;
const BODY = `"Barlow", system-ui, sans-serif`;

// A browser can say yes to a format and still fail to encode it once the recording runs (Chrome on Windows does with
// AAC sound). A format that fails is skipped for the rest of the visit, and the one that worked is tried first.
const failed = new Set();
let worked = null;
let busy = false; // one recording at a time: a move's page and a Share sheet both have the button
const candidates = () => [...new Set([worked, ...recordingTypes()].filter((type) => type && !failed.has(type)))];

/** The page's colour tokens, for drawing on a canvas in the room's own colours. */
export function pageColors() {
  const css = getComputedStyle(document.documentElement);
  const t = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
  return {
    screen: t("--screen", "#050504"), grid: t("--grid-line", "#1d1b18"), lineStrong: t("--line-strong", "#2e2b27"),
    text: t("--text", "#ebe8e3"), text2: t("--text-2", "#aba59d"), text3: t("--text-3", "#908a82"), ground: t("--ground", "#0c0b0a"),
    accent: t("--accent", "#ff7a1a"), accentSoft: t("--accent-soft", "rgb(255 122 26 / 0.16)"), accentFill: t("--accent-fill", "#ff7a1a"),
    accentText: t("--accent-text", "#ffa35f"), onAccent: t("--on-accent", "#140a02"),
  };
}

/** The poses the camera follows in this take: the move's path, turned to the take's starting angle when it had one. */
export function posesFor(take, move, catalog) {
  const poses = move.path?.length ? move.path : move.keys ?? [];
  const angle = angleGeometry(catalog, take.recipe?.rig?.angle);
  return angle ? withAngle(poses, angle) : poses;
}

/**
 * Record `take` with `move`'s camera path and save the file. Call it from a click: the sound needs the person's gesture.
 * `onProgress(share)` follows the recording from 0 to 1. Resolves with the saved file's name.
 */
export async function saveWithPath(ctx, take, move, { onProgress = () => {} } = {}) {
  const { api, store } = ctx;
  if (!candidates().length) throw new Error("This browser cannot record video.");
  if (busy) throw new Error("Another take is being saved. Wait for it to finish.");
  busy = true;
  const video = document.createElement("video");
  video.playsInline = true;
  video.preload = "auto";
  video.style.cssText = "position:fixed;left:0;top:0;width:2px;height:2px;opacity:0;pointer-events:none"; // in the page, so it decodes
  document.body.append(video);
  let raf = 0;
  let stream = null;
  let audio = null;
  try {
    audio = new (globalThis.AudioContext ?? globalThis.webkitAudioContext)(); // made inside the click, so it may sound
    video.src = api.media(take, fileOf(take, "video") ?? "take.mp4");
    await once(video, "loadeddata");
    const scale = Math.min(1, 1280 / Math.max(video.videoWidth, video.videoHeight));
    const width = even(video.videoWidth * scale);
    const height = even(video.videoHeight * scale);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const g = canvas.getContext("2d");
    const layout = overlayLayout(width, height);
    const colors = pageColors();
    await Promise.all([`600 ${layout.title.size}px "Barlow Condensed"`, `600 ${layout.note.size}px "Overpass Mono"`, `600 ${layout.mark.size}px "Barlow"`]
      .map((font) => document.fonts?.load?.(font).catch(() => null)));
    const poses = posesFor(take, move, store.get().moves);
    const receipt = (await api.receipt?.(take).catch(() => null))?.receipt ?? null;
    const { hollow, anchors } = planOf(move, receipt, take.recipe); // as this take was made: its receipt says
    const portrait = height > width;
    const title = move.label.toUpperCase();
    const note = "QWEN-IMAGE 2.1 · LTX 2.5 · OPEN WEIGHTS";

    const draw = () => {
      const t = video.duration > 0 ? video.currentTime / video.duration : 0;
      g.drawImage(video, 0, 0, width, height);
      const shade = g.createLinearGradient(0, 0, 0, layout.shade);
      shade.addColorStop(0, "rgba(0, 0, 0, 0.62)");
      shade.addColorStop(1, "rgba(0, 0, 0, 0)");
      g.fillStyle = shade;
      g.fillRect(0, 0, width, layout.shade);
      g.textAlign = "left";
      g.textBaseline = "top";
      g.shadowColor = "rgba(0, 0, 0, 0.75)"; // the titles read on a bright sky as well as a dark street
      g.shadowBlur = layout.note.size / 2;
      g.fillStyle = colors.text;
      g.font = `600 ${layout.title.size}px ${DISPLAY}`;
      g.fillText(title, layout.title.x, layout.title.y);
      g.fillStyle = colors.accentText;
      g.font = `600 ${layout.note.size}px ${MONO}`;
      g.fillText(note, layout.title.x, layout.title.y + layout.title.size * 1.08);
      g.shadowBlur = 0;
      drawStage(g, { poses, anchors, t, hollow, aspect: portrait ? 9 / 16 : 16 / 9, box: layout.stage, colors, mono: MONO });
      g.textAlign = "right";
      g.textBaseline = "alphabetic";
      g.fillStyle = colors.text;
      g.font = `600 ${layout.mark.size}px ${BODY}`;
      g.shadowColor = "rgba(0, 0, 0, 0.6)";
      g.shadowBlur = layout.mark.size / 3;
      g.fillText("OpenField Studio", layout.mark.x, layout.mark.y);
      g.shadowBlur = 0;
      onProgress(Math.min(t, 0.99));
    };

    const sink = audio.createMediaStreamDestination(); // the take's sound goes into the file, not to the speakers
    audio.createMediaElementSource(video).connect(sink);
    if (audio.state === "suspended") await audio.resume().catch(() => {});
    stream = canvas.captureStream(30);
    for (const track of sink.stream.getAudioTracks()) stream.addTrack(track);

    /** One pass of the take into a recorder of `type`: the file, or the reason it broke. */
    const pass = async (type) => {
      let recorder;
      try {
        recorder = new MediaRecorder(stream, { mimeType: type, videoBitsPerSecond: 6_000_000, audioBitsPerSecond: 160_000 });
      } catch (error) {
        return { broke: error?.message || "The recorder would not start.", format: true };
      }
      const chunks = [];
      let broke = null;
      recorder.addEventListener("dataavailable", (e) => { if (e.data?.size) chunks.push(e.data); });
      recorder.addEventListener("error", (e) => { broke = e.error?.message || "The recorder stopped."; });
      const stopped = new Promise((resolve) => recorder.addEventListener("stop", resolve, { once: true }));
      video.pause();
      video.currentTime = 0;
      await once(video, "seeked").catch(() => {});
      draw(); // the first frame is in the file before the take moves
      try {
        recorder.start(250);
      } catch (error) {
        return { broke: error?.message || "The recorder would not start.", format: true };
      }
      const ended = new Promise((resolve) => video.addEventListener("ended", resolve, { once: true }));
      try {
        await video.play();
      } catch {
        if (recorder.state !== "inactive") recorder.stop();
        await stopped;
        return { broke: "The browser would not play the take. Press the button again.", format: false }; // not the format's fault
      }
      const loop = () => { draw(); raf = requestAnimationFrame(loop); };
      loop();
      await Promise.race([ended, stopped]); // a recorder that breaks stops on its own
      cancelAnimationFrame(raf);
      if (broke) {
        video.pause();
        await stopped;
        return { broke, format: true };
      }
      draw();
      if (recorder.state !== "inactive") recorder.stop();
      await stopped;
      if (broke) return { broke, format: true };
      const blob = new Blob(chunks, { type: type.split(";")[0] });
      return blob.size ? { blob } : { broke: "The recording came out empty.", format: true };
    };

    // a format this browser cannot encode is skipped for the visit, and the take starts again from the top in the next
    const { blob, type } = await firstThatRecords(candidates(), pass, { failed, onRetry: () => onProgress(0) });
    worked = type;
    const name = overlayName(move.id, take.id, type);
    const url = URL.createObjectURL(blob);
    saveAs(url, name);
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
    onProgress(1);
    return name;
  } catch (error) {
    if (error?.constructor === Error) throw error; // thrown here, in plain words
    console.warn("Saving with the camera's path failed:", error); // the browser's own (a DOMException, a TypeError)
    throw new Error("This browser could not record the video.");
  } finally {
    busy = false;
    cancelAnimationFrame(raf);
    for (const track of stream?.getTracks() ?? []) track.stop();
    video.pause();
    video.removeAttribute("src");
    video.load();
    video.remove();
    audio?.close().catch(() => {});
  }
}

/** A button that saves `take` with its camera path; its label follows the recording. onSaved(name) runs even if its sheet
 * has closed. */
export function savePathButton(ctx, take, move, { className = "btn secondary", onError = null, onSaved = null } = {}) {
  const label = "Save with the camera's path";
  const text = document.createElement("span");
  text.textContent = label;
  const button = document.createElement("button");
  button.type = "button";
  button.className = `${className} save-path`;
  button.title = "Save as a video file you can post.";
  button.append(icon("upload", className.includes(" sm") ? "sm" : undefined), text);
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const name = await saveWithPath(ctx, take, move, { onProgress: (share) => setText(text, share < 1 ? `Recording… ${Math.round(share * 100)}%` : "Saved") });
      setTimeout(() => { text.textContent = label; }, 2400);
      onSaved?.(name);
    } catch (error) {
      text.textContent = label;
      onError?.(error?.message ?? "This browser could not record the video.");
    } finally {
      button.disabled = false;
    }
  });
  return button;
}
