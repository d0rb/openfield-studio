// The shot sheet: one picture of a take as it was planned and made. Three of its frames, the camera's path seen from
// above, the words the video model read and the receipt's facts, to share or print. The facts and the layout; no DOM.

import { gpuCost, gpuSeconds } from "./billing.js";

export const SHEET = { width: 1600, height: 1000, pad: 56 };

const FAMILY = { "qwen-image-2.1": "Qwen-Image 2.1", "ltx-2.5": "LTX 2.5", "wan-animate-2": "Wan Animate 2", "real-esrgan": "Real-ESRGAN" };

/** The model families a receipt lists, in its order: ["Qwen-Image 2.1", "LTX 2.5"]. Encoders and VAEs are not named. */
export function modelFamilies(receipt) {
  const out = [];
  for (const m of receipt?.models ?? []) {
    const slug = String(m?.role ?? "").split(":")[1];
    if (!slug) continue;
    const name = FAMILY[slug] ?? slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    if (!out.includes(name)) out.push(name);
  }
  return out;
}

/** The facts beside the frames, as [label, value] rows; a fact the receipt does not hold is left out. */
export function sheetFacts(take, receipt) {
  const i = receipt?.inputs ?? {};
  const rows = [];
  if (Number.isFinite(i.seed)) rows.push(["Seed", String(i.seed)]);
  const length = i.rig?.duration_seconds ?? take?.seconds;
  if (length > 0) rows.push(["Length", `${Math.round(length * 10) / 10} s`]);
  if (typeof i.quality === "string" && i.quality) rows.push(["Quality", i.quality[0].toUpperCase() + i.quality.slice(1)]);
  const models = modelFamilies(receipt);
  if (models.length) rows.push(["Models", models.join(" · ")]);
  const gpu = gpuSeconds(receipt);
  if (gpu) rows.push(["GPU time", `${Math.round(gpu)} s`], ["Cost", `about ${gpuCost(gpu)}`]);
  if (receipt?.audit?.result === "pass") rows.push(["Checked", "Open weights only"]);
  const digest = receipt?.integrity?.digest;
  if (typeof digest === "string" && digest) rows.push(["Receipt", digest.slice(0, 16)]);
  return rows;
}

/** Where the three frames come from: just after the start, the middle, just before the end. */
export const sheetTimes = (duration) => (duration > 0 ? [Math.min(0.05, duration / 4), duration / 2, Math.max(0, duration - 0.15)] : [0, 0, 0]);

/** "00:02.5": a frame's time, as the monitor writes it. */
export const stamp = (seconds) => `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${(seconds % 60).toFixed(1).padStart(4, "0")}`;

/** A word wider than `max` in pieces that fit, each but the last ending in a hyphen. */
function hardBreak(word, max, measure) {
  const rest = [...word];
  const out = [];
  while (rest.length > 1 && measure(rest.join("")) > max) {
    let n = 1;
    while (n < rest.length - 1 && measure(`${rest.slice(0, n + 1).join("")}-`) <= max) n++;
    out.push(`${rest.splice(0, n).join("")}-`);
  }
  return [...out, rest.join("")];
}

/** Text in lines no wider than `max` (by `measure`), at most `lines` of them; a word too long for a line is hyphenated, and
 * a last line that had to stop ends in "…". */
export function wrap(text, max, measure, lines = Infinity) {
  const words = String(text ?? "").split(/\s+/).filter(Boolean).flatMap((word) => hardBreak(word, max, measure));
  const out = [];
  let line = "";
  let i = 0;
  for (; i < words.length; i++) {
    const next = line ? `${line} ${words[i]}` : words[i];
    if (!line || measure(next) <= max) {
      line = next;
      continue;
    }
    out.push(line);
    line = "";
    if (out.length === lines) break;
    line = words[i];
  }
  if (line) out.push(line);
  if (i < words.length && out.length) {
    let last = out[out.length - 1].replace(/-$/, ""); // the ellipsis, not the hyphen
    while (measure(`${last}…`) > max && last.length > 1) last = last.includes(" ") ? last.replace(/\s+\S+$/, "") : [...last].slice(0, -1).join("");
    out[out.length - 1] = `${last}…`;
  }
  return out;
}

/** The sheet's boxes: the title, three frame slots, the words, the facts and the stage, the footer. */
export function sheetLayout({ width = SHEET.width, height = SHEET.height, pad = SHEET.pad } = {}) {
  const gap = 24;
  const slot = Math.floor((width - 2 * pad - 2 * gap) / 3);
  const frameH = Math.round((slot * 9) / 16);
  const top = 292;
  const lower = top + frameH + 64;
  const stageW = 400;
  return {
    header: { x: pad, y: pad },
    title: { x: pad, y: 168, size: 84 },
    subject: { x: pad, y: 206, width: width - 2 * pad, size: 26 },
    frames: [0, 1, 2].map((n) => ({ x: pad + n * (slot + gap), y: top, w: slot, h: frameH })),
    words: { x: pad, y: lower, width: 620, size: 24 },
    facts: { x: pad + 620 + 48, y: lower, width: 380 },
    stage: { x: width - pad - stageW, y: lower, w: stageW, h: Math.round((stageW * 62) / 100) },
    footer: { y: height - pad + 8 },
  };
}
