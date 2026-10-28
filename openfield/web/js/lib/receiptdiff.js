// What two takes' receipts say differently: the rows of the Compare sheet. Each row reads one thing from both receipts
// in the app's own words; the texts a model read are compared word by word.

import { gpuCost, gpuSeconds } from "./billing.js";
import { describeAngle, describeEffect, describeQuality } from "./direct.js";

const KIND = { direct: "Direct", reshoot: "Re-shoot", shots: "Shots", edit: "Edit", extend: "Extend", upscale: "Upscale", transition: "Transition", export: "Export" };
const MADE = { prompt_only: "One still, then the shot", experimental: "One still, then the shot", keyframed: "A still at each key, then the shot" };
// the plan's shape, then what code did to the render (played backwards, mirrored, rolled, the window following the face)
const madeOf = (inputs) => {
  const facts = [MADE[inputs?.mode], inputs?.reversed && "played backwards", inputs?.mirror && "mirrored", inputs?.roll && "rolled in code",
    inputs?.reframe && (inputs.reframe.tracked ? "the window follows the face" : "reframed in code")].filter(Boolean);
  return facts.length ? facts.join(", ") : null;
};
const plain = (s) => (typeof s === "string" && s ? s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()) : null);

const moveLabel = (catalog, id) => (id ? catalog?.moves?.find((m) => m.id === id)?.label ?? plain(id) : null);
const angleLabel = (catalog, id) => (id ? describeAngle(catalog, id) ?? "Where the still was shot" : null);
const effectLabel = (catalog, id) => (id && id !== "none" ? describeEffect(catalog, id)?.label ?? plain(id) : null);
const seconds = (n) => (n > 0 ? `${Math.round(n)} s` : null);

/** The rows, in reading order. `text` rows get a word-by-word diff; `list` rows compare as sets. */
const ROWS = [
  { key: "kind", label: "Kind", read: (r) => KIND[r.take?.kind] ?? plain(r.take?.kind) },
  { key: "move", label: "Camera move", read: (r, c) => moveLabel(c, r.inputs?.rig?.movement ?? r.inputs?.move) },
  { key: "angle", label: "Angle", read: (r, c) => angleLabel(c, r.inputs?.rig?.angle) },
  { key: "made", label: "How it was made", read: (r) => madeOf(r.inputs) },
  { key: "subject", label: "Subject", text: true, read: (r) => r.inputs?.subject },
  { key: "action", label: "What happens", text: true, read: (r) => r.inputs?.action },
  { key: "line", label: "Spoken line", text: true, read: (r) => r.inputs?.line },
  { key: "audio", label: "Sound", text: true, read: (r) => r.inputs?.audio },
  { key: "cast", label: "Cast", read: (r) => r.inputs?.cast?.name },
  { key: "effect", label: "Effect", read: (r, c) => effectLabel(c, r.inputs?.rig?.effect) },
  { key: "speed", label: "Speed", read: (r) => plain(r.inputs?.rig?.speed) },
  { key: "lens", label: "Lens", read: (r) => plain(r.inputs?.rig?.lens) },
  { key: "light", label: "Light", read: (r) => plain(r.inputs?.rig?.lighting) },
  { key: "seed", label: "Seed", read: (r) => (Number.isFinite(r.inputs?.seed) ? String(r.inputs.seed) : null) },
  { key: "quality", label: "Quality", read: (r, c) => (r.inputs?.quality ? describeQuality(c, r.inputs.quality)?.label ?? plain(r.inputs.quality) : null) },
  { key: "length", label: "Length", read: (r) => seconds(r.inputs?.rig?.duration_seconds) },
  { key: "format", label: "Format", read: (r) => plain(r.inputs?.orientation) },
  { key: "workflow", label: "Workflow", read: (r) => (r.workflow?.template ? `${r.workflow.template} · ${String(r.workflow.sha256 ?? "").slice(0, 8)}` : null) },
  { key: "models", label: "Model files", list: true, read: (r) => [...new Set((r.models ?? []).map((m) => m?.file).filter(Boolean))].sort() },
  { key: "face", label: "Face check", read: (r) => (Number.isFinite(r.identity?.score) ? r.identity.score.toFixed(2) : null) },
  { key: "gpu", label: "GPU time", read: (r) => seconds(gpuSeconds(r)) },
  { key: "cost", label: "Cost", read: (r) => gpuCost(gpuSeconds(r)) },
];

const empty = (v) => v == null || v === "" || (Array.isArray(v) && !v.length);

/** The table for two receipts: [{ key, label, a, b, same, words?, onlyA?, onlyB?, shared? }], leaving out the rows
 * neither receipt has. `catalog` (the moves catalog) names moves, angles, effects and quality tiers. */
export function receiptRows(ra, rb, catalog = null) {
  const rows = [];
  for (const row of ROWS) {
    const a = row.read(ra ?? {}, catalog);
    const b = row.read(rb ?? {}, catalog);
    if (empty(a) && empty(b)) continue;
    if (row.list) {
      const left = a ?? [];
      const right = b ?? [];
      const onlyA = left.filter((x) => !right.includes(x));
      const onlyB = right.filter((x) => !left.includes(x));
      rows.push({ key: row.key, label: row.label, a: left, b: right, same: !onlyA.length && !onlyB.length, onlyA, onlyB, shared: left.length - onlyA.length });
      continue;
    }
    const same = (a ?? null) === (b ?? null);
    const out = { key: row.key, label: row.label, a: a ?? null, b: b ?? null, same };
    if (row.text && !same) out.words = wordDiff(a ?? "", b ?? "");
    rows.push(out);
  }
  return rows;
}

const tokens = (s) => (typeof s === "string" ? s.split(/\s+/).filter(Boolean) : []);
const keyOf = (w) => w.toLowerCase().replace(/[.,;:!?"]+$/u, ""); // "rain," and "Rain" are the same word
function push(runs, word, op) {
  const last = runs.at(-1);
  if (last && last.op === op) last.text += ` ${word}`;
  else runs.push({ text: word, op });
}

/** Two texts word by word: { a, b }, each a list of runs { text, op }, op "same", or "gone" (only in a) / "new" (only
 * in b). Texts too long to compare cheaply come back as one changed run each. */
export function wordDiff(a, b) {
  const A = tokens(a);
  const B = tokens(b);
  if (A.length * B.length > 160000) {
    const same = A.join(" ") === B.join(" ");
    return { a: A.length ? [{ text: A.join(" "), op: same ? "same" : "gone" }] : [], b: B.length ? [{ text: B.join(" "), op: same ? "same" : "new" }] : [] };
  }
  const ka = A.map(keyOf);
  const kb = B.map(keyOf);
  const n = A.length;
  const m = B.length;
  const lcs = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) lcs[i][j] = ka[i] === kb[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
  const outA = [];
  const outB = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (ka[i] === kb[j]) { push(outA, A[i++], "same"); push(outB, B[j++], "same"); }
    else if (lcs[i + 1][j] >= lcs[i][j + 1]) push(outA, A[i++], "gone");
    else push(outB, B[j++], "new");
  }
  while (i < n) push(outA, A[i++], "gone");
  while (j < m) push(outB, B[j++], "new");
  return { a: outA, b: outB };
}

/** The takes worth comparing with `take`, best first: the same subject shot another way, then the same cast, then the
 * same move, then the rest, newest first. Each recording counts once (a replay stands for its recording). */
export function compareCandidates(take, takes) {
  const idOf = (t) => t.replay_of ?? t.id;
  const subject = (t) => (t.recipe?.subject ?? "").trim().toLowerCase();
  const cast = (t) => t.recipe?.cast_name ?? null;
  const move = (t) => t.recipe?.rig?.movement ?? null;
  const score = (t) => (subject(t) && subject(t) === subject(take) ? 4 : 0) + (cast(t) && cast(t) === cast(take) ? 2 : 0) + (move(t) && move(t) === move(take) ? 1 : 0);
  const seen = new Set([idOf(take)]);
  return takes
    .filter((t) => t.status === "succeeded" && !seen.has(idOf(t)) && seen.add(idOf(t)))
    .map((t, i) => ({ t, i, s: score(t) }))
    .sort((x, y) => y.s - x.s || String(y.t.created_at ?? "").localeCompare(String(x.t.created_at ?? "")) || x.i - y.i)
    .map(({ t }) => t);
}

/** How the Compare sheet's B follows A, `behind` it by so many seconds: ±5% speed from 0.04 s, a seek past 0.25 s. */
export function driftAction(behind) {
  const off = Math.abs(behind);
  if (!(off >= 0.04)) return "none";
  if (off > 0.25) return "seek";
  return behind > 0 ? "nudge-up" : "nudge-down";
}
