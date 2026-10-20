// Records a scripted walk through the real interface: frames from the browser's screencast plus a timeline.
// scripts/record_demo.py runs this and encodes the MP4. Run it through that, unless you are working on the recorder.
//
//   node scripts/ui/record.mjs --url http://127.0.0.1:8879/ --scenario scripts/ui/demo.scenario.json --out data-dev/demo
//
// A scenario is JSON: { "title": "...", "steps": [ { "do": "...", ... } ] }. Steps:
//   goto   { route: "direct" } or { url: "http://..." }    open a station (or any page)
//   say    { text }                                         a narration cue, timed in the finished video
//   hold   { ms }                                           stay put (what you see keeps being recorded)
//   click  { selector, text? }                              glide the cursor there and click; `text` picks the match containing it
//   type   { selector, text, cps? }                         click the field, then type at human speed (characters per second)
//   key    { key, ctrl? }                                   press a key
//   drag   { selector, by: [dx, dy] }                       press on the element, drag, release (the Before/After handle)
//   scroll { selector, to }                                 scroll an element to a position
//   ring   { selector, ms? }                                draw attention to something for a moment
//   until  { expr, timeout?, speed?, label? }               wait for a page condition; `speed` N plays that wait N times faster
//                                                           with an "N x time-lapse" badge on screen, so the cut is never hidden
//   eval   { expr }                                         run a snippet in the page

import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { launch } from "./browser.mjs";

const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, token, i, all) => (token.startsWith("--") ? [...pairs, [token.slice(2), all[i + 1]]] : pairs), []));
const url = args.url;
const out = args.out;
const width = Number(args.width ?? 1920);
const height = Number(args.height ?? 1080);
if (!url || !args.scenario || !out) {
  console.error("usage: node scripts/ui/record.mjs --url URL --scenario FILE --out DIR [--width 1920 --height 1080]");
  process.exit(2);
}
const scenario = JSON.parse(await readFile(args.scenario, "utf-8"));

const framesDir = join(out, "frames");
rmSync(out, { recursive: true, force: true });
mkdirSync(framesDir, { recursive: true });

// What is drawn on top of the page: a cursor that glides, a ripple where it clicks, a badge, attention rings.
// It lives only in the recording browser's pages; the app itself knows nothing about it.
const OVERLAY = `(() => {
  const css = \`
    #demo-cursor { position: fixed; left: 0; top: 0; width: 24px; height: 24px; z-index: 2147483647; pointer-events: none;
      transform: translate(-200px, -200px); transition: transform 520ms cubic-bezier(.22, 1, .36, 1); }
    #demo-cursor svg { display: block; filter: drop-shadow(0 1px 2px rgba(0, 0, 0, .65)); }
    #demo-ripple { position: fixed; width: 46px; height: 46px; margin: -23px 0 0 -23px; border-radius: 50%; border: 2px solid #8e9bff;
      z-index: 2147483646; pointer-events: none; opacity: 0; }
    @keyframes demo-ripple { from { opacity: .95; transform: scale(.3); } to { opacity: 0; transform: scale(1.5); } }
    #demo-badge { position: fixed; right: 20px; bottom: 20px; z-index: 2147483647; display: none; padding: 8px 14px; border-radius: 999px;
      background: rgba(8, 9, 11, .9); border: 1px solid #667080; color: #e6e8eb; font: 600 15px Inter, system-ui, sans-serif; }
    .demo-ring { position: fixed; z-index: 2147483645; pointer-events: none; border: 2px solid #8e9bff; border-radius: 10px; box-shadow: 0 0 0 5px rgba(142, 155, 255, .25); }
  \`;
  const mount = () => {
    if (document.getElementById("demo-cursor")) return;
    const style = Object.assign(document.createElement("style"), { textContent: css });
    const cursor = document.createElement("div");
    cursor.id = "demo-cursor";
    cursor.innerHTML = '<svg viewBox="0 0 24 24" width="24" height="24"><path d="M4 2 L4 19 L8.6 14.8 L11.6 21.6 L14.2 20.4 L11.2 13.8 L17.4 13.4 Z" fill="#fff" stroke="#0f1115" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    const ripple = Object.assign(document.createElement("div"), { id: "demo-ripple" });
    const badge = Object.assign(document.createElement("div"), { id: "demo-badge" });
    document.documentElement.append(style, cursor, ripple, badge);
  };
  document.addEventListener("DOMContentLoaded", mount);
  if (document.readyState !== "loading") mount();
  window.__demo = {
    move(x, y) { mount(); document.getElementById("demo-cursor").style.transform = "translate(" + x + "px, " + y + "px)"; },
    click(x, y) { mount(); const r = document.getElementById("demo-ripple"); r.style.left = x + "px"; r.style.top = y + "px"; r.style.animation = "none"; void r.offsetWidth; r.style.animation = "demo-ripple 520ms ease-out"; },
    badge(text) { mount(); const b = document.getElementById("demo-badge"); b.textContent = text ?? ""; b.style.display = text ? "block" : "none"; },
    ring(rect, ms) { const el = document.createElement("div"); el.className = "demo-ring"; Object.assign(el.style, { left: rect.x - 6 + "px", top: rect.y - 6 + "px", width: rect.width + 12 + "px", height: rect.height + 12 + "px" }); document.documentElement.append(el); setTimeout(() => el.remove(), ms); },
  };
})();`;

const b = await launch({ width, height });
const frames = [];
const lapses = [];
const cues = [];
const now = () => Date.now() / 1000;
let startedAt = null;

b.on("Page.screencastFrame", (p) => {
  const file = `frame-${String(frames.length + 1).padStart(6, "0")}.jpg`;
  writeFileSync(join(framesDir, file), Buffer.from(p.data, "base64"));
  frames.push({ file, ts: p.metadata.timestamp });
  b.send("Page.screencastFrameAck", { sessionId: p.sessionId }).catch(() => {});
});

const ev = (js) => b.eval(js);
const box = (selector, text) => ev(`(() => {
  const all = [...document.querySelectorAll(${JSON.stringify(selector)})].filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; });
  const el = ${JSON.stringify(text ?? null)} ? all.find((e) => e.textContent.includes(${JSON.stringify(text ?? "")})) : all[0];
  if (!el) return null;
  el.scrollIntoView({ block: "nearest", inline: "nearest" });
  const r = el.getBoundingClientRect();
  return { x: r.x, y: r.y, width: r.width, height: r.height, cx: r.x + r.width / 2, cy: r.y + r.height / 2 };
})()`);
const need = async (selector, text) => {
  const r = await box(selector, text);
  if (!r) throw new Error(`nothing to point at: ${selector}${text ? ` containing "${text}"` : ""}`);
  return r;
};
const glideTo = async (r) => {
  await ev(`window.__demo.move(${r.cx}, ${r.cy})`);
  await b.sleep(560);
  await b.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: r.cx, y: r.cy });
};
const press = async (r, type) => b.send("Input.dispatchMouseEvent", { type, x: r.cx, y: r.cy, button: "left", clickCount: 1 });

const steps = {
  async goto(s) {
    if (s.url) {
      await b.goto(s.url);
      await b.waitFor("window.openfield?.store.get().loaded", { timeout: 30000 });
    } else {
      await ev(`location.hash = "#/${s.route}"`);
      await b.waitFor(`window.openfield.store.get().route === "${s.route}"`);
    }
    await b.sleep(500);
  },
  async say(s) { cues.push({ at: now(), text: s.text }); },
  async hold(s) { await b.sleep(s.ms ?? 1000); },
  async click(s) {
    const r = await need(s.selector, s.text);
    await glideTo(r);
    await ev(`window.__demo.click(${r.cx}, ${r.cy})`);
    await press(r, "mousePressed");
    await b.sleep(80);
    await press(r, "mouseReleased");
    await b.sleep(220);
  },
  async type(s) {
    await steps.click({ selector: s.selector });
    for (const ch of s.text) {
      await b.send("Input.insertText", { text: ch });
      await b.sleep(1000 / (s.cps ?? 22));
    }
    await b.sleep(250);
  },
  async key(s) { await b.key(s.key, { ctrl: Boolean(s.ctrl) }); await b.sleep(250); },
  async drag(s) {
    const r = await need(s.selector);
    await glideTo(r);
    await press(r, "mousePressed");
    const [dx, dy] = s.by;
    for (let i = 1; i <= 24; i += 1) {
      const x = r.cx + (dx * i) / 24;
      const y = r.cy + (dy * i) / 24;
      await ev(`window.__demo.move(${x}, ${y})`);
      await b.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y, button: "left", buttons: 1 });
      await b.sleep(28);
    }
    await press({ cx: r.cx + dx, cy: r.cy + dy }, "mouseReleased");
    await b.sleep(300);
  },
  async scroll(s) { await ev(`document.querySelector(${JSON.stringify(s.selector)}).scrollTo({ top: ${s.to}, behavior: "smooth" })`); await b.sleep(700); },
  async ring(s) {
    const r = await need(s.selector);
    await ev(`window.__demo.ring(${JSON.stringify({ x: r.x, y: r.y, width: r.width, height: r.height })}, ${s.ms ?? 1600})`);
    await b.sleep(s.ms ?? 1600);
  },
  async until(s) {
    const speed = s.speed ?? 1;
    const from = now();
    if (speed > 1) await ev(`window.__demo.badge(${JSON.stringify(`${speed}× time-lapse${s.label ? `: ${s.label}` : ""}`)})`);
    try {
      await b.waitFor(s.expr, { timeout: s.timeout ?? 120000, label: s.label ?? s.expr });
    } finally {
      if (speed > 1) {
        lapses.push({ from, to: now(), speed });
        await ev("window.__demo.badge('')");
      }
    }
    await b.sleep(400);
  },
  async eval(s) { await ev(s.expr); },
};

try {
  await b.addInitScript(OVERLAY);
  await b.emulate([{ name: "prefers-reduced-motion", value: "no-preference" }]); // the recording shows the app with its motion
  await b.goto(url);
  await b.waitFor("window.openfield?.store.get().loaded", { timeout: 30000, label: "the app loads" });
  await b.sleep(800);
  await b.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: width, maxHeight: height, everyNthFrame: 1 });
  startedAt = now();
  for (const [index, step] of scenario.steps.entries()) {
    if (!steps[step.do]) throw new Error(`step ${index + 1}: unknown action "${step.do}"`);
    try {
      await steps[step.do](step);
    } catch (error) {
      throw new Error(`step ${index + 1} (${step.do}): ${error.message}`);
    }
  }
  await b.sleep(900);
  var endedAt = now();
  await b.send("Page.stopScreencast");
} finally {
  var backend = await ev("window.openfield?.store.get().status?.backend?.label ?? ''").catch(() => "");
  // a hosted Replay of fake takes reports a plain "Replay": the receipts say what actually rendered them
  var fakeFootage = await ev(`(async () => {
    const s = window.openfield.store.get();
    for (const take of [...s.recorded, ...s.takes].slice(0, 16)) {
      try { const view = await window.openfield.api.receipt(take); if (/FAKE/.test(view.receipt?.backend?.label ?? "")) return true; } catch { /* no receipt for this one */ }
    }
    return false;
  })()`).catch(() => false);
  await b.close();
}

if (!frames.length) {
  console.error("the browser sent no frames");
  process.exit(1);
}

// Turn wall-clock frames into a video timeline: a "time-lapse" wait plays N times faster, everything else in real time.
const speedAt = (t) => lapses.find((l) => t >= l.from && t < l.to)?.speed ?? 1;
const lines = ["ffconcat version 1.0"];
const videoStart = [];
let video = 0;
frames.forEach((f, i) => {
  const next = frames[i + 1]?.ts ?? endedAt;
  const seconds = Math.max(0.001, (next - f.ts) / speedAt(f.ts));
  videoStart.push(video);
  video += seconds;
  lines.push(`file 'frames/${f.file}'`, `duration ${seconds.toFixed(4)}`);
});
lines.push(`file 'frames/${frames.at(-1).file}'`); // the concat demuxer ignores the last duration, so the last frame is listed again
writeFileSync(join(out, "concat.txt"), `${lines.join("\n")}\n`);

const videoTimeAt = (wall) => {
  let i = frames.findLastIndex((f) => f.ts <= wall);
  if (i < 0) i = 0;
  return videoStart[i] + Math.max(0, wall - frames[i].ts) / speedAt(frames[i].ts);
};
writeFileSync(join(out, "timeline.json"), JSON.stringify({
  title: scenario.title ?? "", width, height, frames: frames.length, seconds: +video.toFixed(2), backend, fake_footage: fakeFootage,
  lapses: lapses.map((l) => ({ speed: l.speed, real_s: +(l.to - l.from).toFixed(1) })),
  cues: cues.map((c) => ({ video_s: +videoTimeAt(c.at).toFixed(2), text: c.text })),
}, null, 2));
console.log(`recorded ${frames.length} frames, ${video.toFixed(1)} s of video, ${cues.length} narration cue(s), backend: ${backend || "unknown"}`);
