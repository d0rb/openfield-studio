// A take saved with its planned camera: the stage drawn on a canvas (the same floor, path, numbered marks and camera as
// the stage view in ui/stageview.js), the layout of a saved frame, and the format the browser records in. No DOM here.

import { anchorsAlong, frustum, litCount, poseAt, spreadStacked, stageFit } from "./pathview.js";

const W = 100; // the stage's plan units, as ui/stageview.js draws it
const H = 62;
const FLOOR_SPAN = 3;
const clamp01 = (t) => (Number.isFinite(t) ? Math.min(1, Math.max(0, t)) : 0);

/** The part of a polyline travelled at share `v` (0 to 1) of its length, ending on the exact point reached. */
export function travelled(points, v) {
  if (points.length < 2) return points.slice();
  const lengths = [0];
  for (let i = 1; i < points.length; i++) lengths.push(lengths[i - 1] + Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y));
  const total = lengths.at(-1);
  if (!(total > 0)) return [points[0]];
  const goal = clamp01(v) * total;
  const out = [points[0]];
  for (let i = 1; i < points.length; i++) {
    if (lengths[i] <= goal) { out.push(points[i]); continue; }
    const f = (goal - lengths[i - 1]) / (lengths[i] - lengths[i - 1]);
    if (f > 0) out.push({ x: points[i - 1].x + (points[i].x - points[i - 1].x) * f, y: points[i - 1].y + (points[i].y - points[i - 1].y) * f });
    break;
  }
  return out;
}

/** Where the parts of a saved frame go: the stage at the lower left (half the width on a portrait frame), the titles at
 * the upper left, the studio's name at the lower right. Sizes follow the frame's short side. */
export function overlayLayout(width, height) {
  const short = Math.min(width, height);
  const margin = Math.round(short * 0.045);
  const w = Math.round(width * (height > width ? 0.5 : 0.3));
  const h = Math.round((w * H) / W);
  return {
    margin,
    stage: { x: margin, y: height - margin - h, w, h },
    title: { x: margin, y: margin, size: Math.round(short * 0.075) },
    note: { size: Math.round(short * 0.03) },
    mark: { x: width - margin, y: height - margin, size: Math.round(short * 0.032) },
    shade: Math.round(height * 0.26), // the darkening under the titles, from the top
  };
}

// MP4 with AAC sound first (what every network takes), then MP4 with Opus sound, then WebM. A browser can say yes to a
// format and still fail to encode it (Chrome on Windows does with AAC), so ui/overlay.js tries each one before recording.
const TYPES = ["video/mp4;codecs=avc1,mp4a.40.2", "video/mp4;codecs=avc1.640028,mp4a.40.2", "video/mp4;codecs=avc1,opus", "video/mp4",
  "video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"];

/** Every format this browser says it can record, best first. */
export function recordingTypes(isSupported = (type) => globalThis.MediaRecorder?.isTypeSupported?.(type)) {
  return TYPES.filter((type) => { try { return Boolean(isSupported(type)); } catch { return false; } });
}

/** The best format this browser says it can record, or null. */
export const recordingType = (isSupported) => recordingTypes(isSupported)[0] ?? null;

/** The saved file's name: the move, then the take. */
export const overlayName = (moveId, takeId, type) => `${String(moveId).replace(/_/g, "-")}-${takeId}.${String(type).includes("mp4") ? "mp4" : "webm"}`;

/** Draw the stage for `poses` at share `t` of the take into `box` ({ x, y, w, h }, the plan's 100:62). `colors` holds the
 * page's tokens; `hollow` draws a one-still shot (one mark, the camera as planned rather than pinned). */
export function drawStage(g, { poses, anchors = 2, t = 0, hollow = false, aspect = 16 / 9, box, colors, mono = "monospace" }) {
  const { to, floor, scale } = stageFit(poses, { width: W, height: H, aspect });
  const s = box.w / W;
  const hair = Math.max(1, box.w / 320); // the stage view's 1px lines, kept visible on a large frame
  const at = (p) => ({ x: box.x + p.x * s, y: box.y + p.y * (box.h / H) });
  const path = (points) => { g.beginPath(); points.forEach((p, i) => (i ? g.lineTo(p.x, p.y) : g.moveTo(p.x, p.y))); };
  const circle = (p, r) => { g.beginPath(); g.arc(p.x, p.y, r, 0, Math.PI * 2); };
  const v = clamp01(t);

  g.save();
  g.beginPath();
  g.rect(box.x, box.y, box.w, box.h);
  g.clip();
  g.globalAlpha = 0.88;
  g.fillStyle = colors.screen;
  g.fillRect(box.x, box.y, box.w, box.h);
  g.globalAlpha = 1;
  g.lineCap = "round";
  g.lineJoin = "round";

  // the floor's tape grid and the subject's mark, its post up to eye level drawn later over the path
  g.beginPath();
  for (let u = -FLOOR_SPAN; u <= FLOOR_SPAN; u += 0.5) {
    for (const [a, b] of [[{ x: u, y: floor, z: -FLOOR_SPAN }, { x: u, y: floor, z: FLOOR_SPAN }], [{ x: -FLOOR_SPAN, y: floor, z: u }, { x: FLOOR_SPAN, y: floor, z: u }]]) {
      const p = at(to(a));
      const q = at(to(b));
      g.moveTo(p.x, p.y);
      g.lineTo(q.x, q.y);
    }
  }
  g.strokeStyle = colors.grid;
  g.lineWidth = hair;
  g.stroke();
  const foot = at(to({ x: 0, y: floor, z: 0 }));
  const eye = at(to({ x: 0, y: 0, z: 0 }));
  const r = 0.09 * scale * s;
  g.beginPath();
  g.ellipse(foot.x, foot.y, r, r * 0.47, 0, 0, Math.PI * 2);
  g.strokeStyle = colors.lineStrong;
  g.stroke();

  // where the camera is now: the lens, its frame ahead, and its spot on the floor
  const pose = poseAt(poses, v);
  const { apex, corners } = frustum(pose, { aspect });
  const lens = at(to(apex));
  const frame = corners.map((p) => at(to(p)));
  const spot = at(to({ x: pose.x, y: floor, z: pose.z }));
  g.setLineDash([1 * s, 0.8 * s]);
  path([lens, spot]);
  g.strokeStyle = colors.text3;
  g.lineWidth = 0.3 * s;
  g.stroke();
  g.setLineDash([]);
  circle(spot, 0.9 * s);
  g.fillStyle = colors.text3;
  g.fill();

  // the whole path, and the part travelled so far over it
  const plan = poses.map(to);
  const track = plan.map(at);
  path(track);
  g.strokeStyle = colors.text3;
  g.lineWidth = 0.5 * s;
  g.stroke();
  path(travelled(track, v));
  g.strokeStyle = colors.accent;
  g.lineWidth = 0.75 * s;
  g.stroke();

  path([foot, eye]);
  g.strokeStyle = colors.text2;
  g.lineWidth = 1.5 * hair;
  g.stroke();
  circle(eye, 1.5 * s);
  g.fillStyle = colors.text2;
  g.fill();

  g.beginPath();
  for (const c of frame) { g.moveTo(lens.x, lens.y); g.lineTo(c.x, c.y); }
  g.globalAlpha = 0.5;
  g.strokeStyle = colors.accent;
  g.lineWidth = hair;
  g.stroke();
  g.globalAlpha = 1;
  path(frame);
  g.closePath();
  if (hollow) {
    g.setLineDash([1.2 * s, 0.8 * s]);
    g.lineWidth = 0.3 * s;
  } else {
    g.fillStyle = colors.accentSoft;
    g.fill();
    g.lineWidth = hair;
  }
  g.strokeStyle = colors.accent;
  g.stroke();
  g.setLineDash([]);

  // the numbered tape marks, one per approved still, lit once the camera passes them
  const count = hollow ? 1 : Math.max(2, anchors);
  const reached = litCount(count, v);
  spreadStacked(anchorsAlong({ points: plan }, count), 7.5).forEach((p, i) => {
    const m = at(p);
    const lit = i < reached;
    circle(m, 3 * s);
    g.fillStyle = lit ? colors.accentFill : colors.ground;
    g.fill();
    g.strokeStyle = lit ? colors.ground : colors.accent;
    g.lineWidth = hair;
    g.stroke();
    g.fillStyle = lit ? colors.onAccent : colors.accentText;
    g.font = `600 ${(3.4 * s).toFixed(1)}px ${mono}`;
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillText(String(i + 1), m.x, m.y + 0.2 * s);
  });

  circle(lens, 2 * s);
  g.fillStyle = hollow ? colors.ground : colors.accentFill;
  g.fill();
  g.strokeStyle = hollow ? colors.accent : colors.ground;
  g.lineWidth = hair;
  g.stroke();
  g.restore();

  g.strokeStyle = colors.lineStrong;
  g.lineWidth = hair;
  g.strokeRect(box.x + hair / 2, box.y + hair / 2, box.w - hair, box.h - hair);
}

/** Record with the first format that works. `pass(type)` answers { blob } or { broke, format }: a format whose encoder failed
 * (`format: true`) joins `failed` and the next one is tried; any other failure, or a throw, stops at once. `warn` gets the
 * browser's own words; the error says it plainly. Resolves { blob, type }. */
export async function firstThatRecords(types, pass, { failed = new Set(), onRetry = () => {}, warn = console.warn } = {}) {
  const fail = "This browser could not record the video.";
  for (const type of types) {
    if (failed.has(type)) continue;
    let result;
    try {
      result = await pass(type);
    } catch (error) {
      warn(`Recording as ${type} failed:`, error);
      throw new Error(fail);
    }
    if (result?.blob) return { blob: result.blob, type };
    warn(`Recording as ${type} failed: ${result?.broke}`);
    if (!result?.format) throw new Error(result?.broke ?? fail); // not the format's fault, and said plainly
    failed.add(type);
    onRetry(type, result.broke);
  }
  throw new Error(fail);
}

/** How a take was planned, from its receipt when it has one (the catalog can change after the take is made): a keyframed
 * take shows a mark per still, a one-still take one mark and the camera as planned. */
export function planOf(move, receipt, recipe) {
  const mode = receipt?.inputs?.mode;
  const stills = receipt?.inputs?.anchors?.length ?? 0;
  if (mode === "keyframed" && stills > 1) return { hollow: false, anchors: stills };
  if (mode) return { hollow: true, anchors: 1 };
  return { hollow: move.mode !== "keyframed" || Boolean(recipe?.prompt_only), anchors: move.anchors ?? 2 };
}
