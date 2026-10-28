// Records a scripted walk through the real interface: frames from the browser's screencast plus a timeline.
// scripts/record_demo.py runs this and encodes the MP4. Run it through that, unless you are working on the recorder.
//
//   node scripts/ui/record.mjs --url http://127.0.0.1:8879/ --scenario scripts/ui/demo.scenario.json --out data-dev/demo
//
// --clips DIR serves that folder on a free local port for the recording, for `film { src }` (a live render, a canvas).
//
// A scenario is JSON: { "title": "...", "steps": [ { "do": "...", ... } ] }. Steps:
//   goto   { route: "direct" } or { url: "http://..." }    open a station (or any page)
//   say    { text, caption?, tag? }                          a narration cue, timed in the finished video; `caption`
//                                                           (a string, or null to clear) prints it on screen, and `tag`
//                                                           (a short label such as "LTX 2.5") prints above it in small mono type
//   caption { text | null, tag? }                           print or clear a caption, with no narration cue; a null `text`
//                                                           clears the tag with it, and a caption with no `tag` shows none
//   card   { title, lines?, statement?, mono?, ms?, hold?, dim? } a title card; `ms` (default 3000) then it goes, unless `hold`
//                                                           keeps it until the next card or `{ clear: true }`; `dim`
//                                                           sets the scrim (default .86), lighter over footage
//   hold   { ms }                                           stay put (what you see keeps being recorded)
//   click  { selector, text? }                              glide the cursor there and click; `text` picks the match containing it
//   type   { selector, text, cps? }                         click the field, then type at human speed (characters per second)
//   key    { key, ctrl? }                                   press a key
//   drag   { selector, by: [dx, dy] }                       press on the element, drag, release (the Before/After handle)
//   scroll { selector, to }                                 scroll an element to a position
//   ring   { selector, text?, ms? }                         draw attention to something for a moment; `text` picks the match containing it
//   hover  { selector, text?, ms? }                         glide the cursor there and stay (previews play on hover)
//   sweep  { selector, text?, from?, to?, ms?, back? }     run the cursor across it without a click, from `from` to `to`
//                                                           of its width (0.1 to 0.9), over `ms`, and back if `back`:
//                                                           a frame in the Lobby scrubs its take under the mouse
//   until  { expr, timeout?, speed?, label? }               wait for a page condition; `speed` N plays that wait N times faster
//                                                           with an "N x time-lapse" badge on screen, so the cut is never hidden
//   eval   { expr }                                         run a snippet in the page
//   film   { take | src, from?, ms?, caption?, captionTag?, captionAt?, chip?, chipAt?, sound?, loop?, hold? }
//                                                           play a take's own video (the app opens the take behind it)
//                                                           or a clip from --clips, full-bleed, from `from` s for `ms`;
//                                                           `captionTag` is the caption's tag; `chip` slides in the take's
//                                                           verdict as its receipt pane prints it; `sound` marks the cue
//                                                           (`sound` for a take, `clip_sound` for a clip) so record_demo.py
//                                                           lays that file's own sound there, from `from` for `ms`;
//                                                           `hold` keeps the picture for the next film or
//                                                           `{ clear: true, into? }`, which shrinks it into `into` or fades
//   tracker { title, items } | { tick } | { clear: true }    a plain-text checklist top right of the workspace (beside
//                                                           the dock while it is open); `tick` checks the item whose
//                                                           first word it is, e.g. "#4"
//
// `{try_url}` and `{repo_url}` in a card, caption or say text are replaced from --try-url and --repo-url;
// a card `lines` entry or `mono` line that still holds an empty placeholder is dropped.

import { createReadStream, existsSync, mkdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { readFile, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { basename, join } from "node:path";
import { launch } from "./browser.mjs";

const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, token, i, all) => (token.startsWith("--") ? [...pairs, [token.slice(2), all[i + 1]]] : pairs), []));
const url = args.url;
const out = args.out;
const width = Number(args.width ?? 1920);
const height = Number(args.height ?? 1080);
const tryUrl = args["try-url"] ?? "";
const repoUrl = args["repo-url"] ?? "";
if (!url || !args.scenario || !out) {
  console.error("usage: node scripts/ui/record.mjs --url URL --scenario FILE --out DIR [--width 1920 --height 1080 --try-url URL --repo-url URL --clips DIR]");
  process.exit(2);
}
const scenario = JSON.parse(await readFile(args.scenario, "utf-8"));

const fill = (text) => String(text ?? "").replaceAll("{try_url}", tryUrl).replaceAll("{repo_url}", repoUrl);
const missing = (text) => (!tryUrl && String(text).includes("{try_url}")) || (!repoUrl && String(text).includes("{repo_url}"));

const framesDir = join(out, "frames");
rmSync(out, { recursive: true, force: true });
mkdirSync(framesDir, { recursive: true });

// --clips DIR: what a film { src } step plays, served from that folder on a free local port while the recording runs
let clipBase = "";
let clipServer = null;
if (args.clips) {
  clipServer = createServer((req, res) => {
    const file = join(args.clips, basename(decodeURIComponent(new URL(req.url, "http://clips").pathname))); // a bare name: nothing outside the folder
    if (!existsSync(file) || !statSync(file).isFile()) { res.writeHead(404).end(); return; }
    const size = statSync(file).size;
    const range = /bytes=(\d*)-(\d*)/.exec(req.headers.range ?? "");
    const start = range?.[1] ? Number(range[1]) : 0;
    const end = range?.[2] ? Number(range[2]) : size - 1;
    res.writeHead(range ? 206 : 200, { "Content-Type": "video/mp4", "Accept-Ranges": "bytes", "Content-Length": end - start + 1, ...(range ? { "Content-Range": `bytes ${start}-${end}/${size}` } : {}) });
    createReadStream(file, { start, end }).pipe(res);
  });
  await new Promise((ready) => clipServer.listen(0, "127.0.0.1", ready));
  clipBase = `http://127.0.0.1:${clipServer.address().port}`;
}

// What is drawn on top of the page: a cursor that glides, a ripple where it clicks, a badge, attention rings.
// It lives only in the recording browser's pages; the app itself knows nothing about it.
const OVERLAY = `(() => {
  const css = \`
    #demo-cursor { position: fixed; left: 0; top: 0; width: 24px; height: 24px; z-index: 2147483647; pointer-events: none;
      transform: translate(-200px, -200px); transition: transform 520ms cubic-bezier(.22, 1, .36, 1); }
    #demo-cursor svg { display: block; filter: drop-shadow(0 1px 2px rgba(0, 0, 0, .65)); }
    #demo-ripple { position: fixed; width: 46px; height: 46px; margin: -23px 0 0 -23px; border-radius: 50%; border: 2px solid #ff7a1a;
      z-index: 2147483646; pointer-events: none; opacity: 0; }
    @keyframes demo-ripple { from { opacity: .95; transform: scale(.3); } to { opacity: 0; transform: scale(1.5); } }
    #demo-badge { position: fixed; right: 20px; bottom: 20px; z-index: 2147483647; display: none; padding: 8px 14px; border-radius: 999px;
      background: rgba(8, 9, 11, .9); border: 1px solid rgba(255, 122, 26, .6); color: #f3eee8; font: 600 15px Barlow, system-ui, sans-serif; letter-spacing: .02em; }
    .demo-ring { position: fixed; z-index: 2147483645; pointer-events: none; border: 2px solid #ff7a1a; border-radius: 6px; box-shadow: 0 0 0 5px rgba(255, 122, 26, .22); }
    #demo-caption { position: fixed; left: 0; right: 0; bottom: 0; padding: 150px 64px 52px; max-width: none; color: #f4f1ec;
      font: 800 88px/0.96 "Barlow Condensed", "Barlow", system-ui, sans-serif; text-transform: uppercase; letter-spacing: .004em;
      background: linear-gradient(to top, rgba(8, 8, 7, .8) 0%, rgba(8, 8, 7, .52) 42%, rgba(8, 8, 7, 0) 100%);
      opacity: 0; transition: opacity 180ms; pointer-events: none; z-index: 2147483647; }
    .demo-caption-line { max-width: 74vw; text-shadow: 0 2px 20px rgba(0, 0, 0, .6); }
    .demo-caption-line .demo-caption-second { display: block; color: #ff7a1a; }
    .demo-caption-tag { display: none; margin: 0 0 16px 4px; color: #ffa35f; font: 500 17px/1.3 "Overpass Mono", ui-monospace, monospace;
      letter-spacing: .14em; text-transform: uppercase; }
    .demo-caption-tag::before { content: "· "; color: #ff7a1a; }
    #demo-card { position: fixed; inset: 0; z-index: 2147483646; background: rgba(10, 10, 9, .86); display: grid; place-items: center;
      text-align: center; color: #f4f1ec; opacity: 0; transition: opacity 240ms; pointer-events: none; }
    .demo-card-inner { display: grid; justify-items: center; gap: 18px; max-width: 68vw; }
    .demo-card-mark { width: 56px; height: 56px; fill: #ff7a1a; }
    .demo-card-title { font: 600 48px/1.15 Barlow, system-ui, sans-serif; }
    .demo-card-statement { display: none; margin-top: 6px; font: 800 58px/1.0 "Barlow Condensed", "Barlow", system-ui, sans-serif; text-transform: uppercase; letter-spacing: .005em; }
    .demo-card-statement .demo-caption-second { display: block; color: #ff7a1a; }
    .demo-card-lines { display: grid; gap: 2px; }
    .demo-card-line { font: 400 22px/1.4 Barlow, system-ui, sans-serif; color: #aba59d; }
    .demo-card-mono { font: 500 16px/1.8 "Overpass Mono", ui-monospace, monospace; letter-spacing: .04em; color: #aba59d; white-space: pre-line; }
    #demo-film { position: fixed; inset: 0; z-index: 2147483640; background: #000; opacity: 0; transform-origin: 0 0; pointer-events: none; }
    #demo-film video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: 0; }
    #demo-film video.on { opacity: 1; }
    #demo-chip { position: fixed; right: 64px; bottom: 60px; z-index: 2147483647; padding: 8px 14px 9px; background: rgba(10, 10, 9, .78);
      border-left: 3px solid #4fbf7a; border-radius: 2px; color: #f4f1ec; font: 500 20px/1.3 "Overpass Mono", ui-monospace, monospace;
      opacity: 0; transform: translateX(28px); transition: opacity 260ms, transform 320ms cubic-bezier(.22, 1, .36, 1); pointer-events: none; }
    #demo-tracker { position: fixed; top: 60px; right: 20px; z-index: 2147483644; min-width: 236px; padding: 10px 14px 12px;
      background: rgba(10, 10, 9, .8); border-radius: 2px; color: #908a82; font: 500 15px/1.55 Barlow, system-ui, sans-serif;
      opacity: 0; transition: opacity 220ms, right 300ms; pointer-events: none; }
    .demo-tracker-title { color: #f4f1ec; font-weight: 600; margin-bottom: 4px; }
    .demo-tracker-item::before { content: "·"; display: inline-block; width: 18px; }
    .demo-tracker-item.done { color: #f4f1ec; }
    .demo-tracker-item.done::before { content: "✓"; color: #ff7a1a; }
  \`;
  const mount = () => {
    if (document.getElementById("demo-cursor")) return;
    const style = Object.assign(document.createElement("style"), { textContent: css });
    const cursor = document.createElement("div");
    cursor.id = "demo-cursor";
    cursor.innerHTML = '<svg viewBox="0 0 24 24" width="24" height="24"><path d="M4 2 L4 19 L8.6 14.8 L11.6 21.6 L14.2 20.4 L11.2 13.8 L17.4 13.4 Z" fill="#fff" stroke="#0f1115" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    const ripple = Object.assign(document.createElement("div"), { id: "demo-ripple" });
    const badge = Object.assign(document.createElement("div"), { id: "demo-badge" });
    const caption = Object.assign(document.createElement("div"), { id: "demo-caption" });
    caption.innerHTML = '<div class="demo-caption-tag"></div><div class="demo-caption-line"></div>'; // the tag sits above the line
    const card = Object.assign(document.createElement("div"), { id: "demo-card" });
    card.innerHTML = '<div class="demo-card-inner"><svg class="demo-card-mark" viewBox="0 0 20 20" aria-hidden="true"><rect x="2" y="4" width="16" height="3" rx="0.5"/><rect x="8.5" y="7" width="3" height="9" rx="0.5"/></svg><div class="demo-card-title"></div><div class="demo-card-lines"></div><div class="demo-card-statement"></div><div class="demo-card-mono"></div></div>';
    const film = Object.assign(document.createElement("div"), { id: "demo-film" });
    const chip = Object.assign(document.createElement("div"), { id: "demo-chip" });
    const tracker = Object.assign(document.createElement("div"), { id: "demo-tracker" });
    document.documentElement.append(style, cursor, ripple, badge, caption, card, film, chip, tracker);
    setInterval(() => window.__demo?.place(), 400); // the tracker follows the dock as it opens and closes
  };
  document.addEventListener("DOMContentLoaded", mount);
  if (document.readyState !== "loading") mount();
  window.__demo = {
    move(x, y) { mount(); document.getElementById("demo-cursor").style.transform = "translate(" + x + "px, " + y + "px)"; },
    click(x, y) { mount(); const r = document.getElementById("demo-ripple"); r.style.left = x + "px"; r.style.top = y + "px"; r.style.animation = "none"; void r.offsetWidth; r.style.animation = "demo-ripple 520ms ease-out"; },
    badge(text) { mount(); const b = document.getElementById("demo-badge"); b.textContent = text ?? ""; b.style.display = text ? "block" : "none"; },
    ring(rect, ms) { const el = document.createElement("div"); el.className = "demo-ring"; Object.assign(el.style, { left: rect.x - 6 + "px", top: rect.y - 6 + "px", width: rect.width + 12 + "px", height: rect.height + 12 + "px" }); document.documentElement.append(el); setTimeout(() => el.remove(), ms); },
    caption(text, tag) { // no text clears the caption and its tag together; a caption without a tag shows none
      mount();
      const el = document.getElementById("demo-caption");
      const line = el.querySelector(".demo-caption-line");
      const label = el.querySelector(".demo-caption-tag");
      clearTimeout(el._demoTimer);
      if (text == null || text === "") {
        el.style.opacity = "0";
        el._demoTimer = setTimeout(() => { line.textContent = ""; label.textContent = ""; label.style.display = "none"; }, 200);
        return;
      }
      // a " / " breaks the headline into two lines, the second in the accent colour, the way the promo sets its titles
      const [first, ...rest] = String(text).split(" / ");
      line.textContent = first;
      if (rest.length) line.append(Object.assign(document.createElement("span"), { className: "demo-caption-second", textContent: rest.join(" / ") }));
      label.textContent = tag ?? "";
      label.style.display = tag ? "block" : "none";
      el.style.opacity = "1";
    },
    card(content) {
      mount();
      const el = document.getElementById("demo-card");
      clearTimeout(el._demoTimer);
      if (!content) {
        el.style.opacity = "0";
        el._demoTimer = setTimeout(() => {
          el.querySelector(".demo-card-title").textContent = "";
          el.querySelector(".demo-card-lines").textContent = "";
          el.querySelector(".demo-card-statement").textContent = "";
          el.querySelector(".demo-card-mono").textContent = "";
        }, 240);
        return;
      }
      window.__demo.caption(null); // a card is the whole statement: no caption or chip stays over it
      window.__demo.chip(null);
      el.querySelector(".demo-card-title").textContent = content.title ?? "";
      const statement = el.querySelector(".demo-card-statement");
      statement.textContent = "";
      if (content.statement) { // "first / second": the second line in the accent colour, like a caption
        const [first, ...rest] = String(content.statement).split(" / ");
        statement.append(first);
        if (rest.length) statement.append(Object.assign(document.createElement("span"), { className: "demo-caption-second", textContent: rest.join(" / ") }));
      }
      statement.style.display = content.statement ? "block" : "none";
      const lines = el.querySelector(".demo-card-lines");
      lines.textContent = "";
      for (const line of (content.lines ?? []).slice(0, 4)) {
        lines.append(Object.assign(document.createElement("div"), { className: "demo-card-line", textContent: line }));
      }
      const mono = el.querySelector(".demo-card-mono");
      mono.textContent = content.mono ?? "";
      mono.style.display = content.mono ? "block" : "none";
      el.style.background = content.dim != null ? "rgba(10, 10, 9, " + content.dim + ")" : "";
      el.style.opacity = "1";
    },
    cover() {
      mount();
      const el = document.getElementById("demo-film");
      el.style.transition = "none";
      el.style.transform = "none";
      el.style.opacity = "1";
      window.__demo.place();
    },
    film(src, from, loop) {
      window.__demo.cover();
      const el = document.getElementById("demo-film");
      const v = document.createElement("video");
      v.muted = true;
      v.playsInline = true;
      v.loop = Boolean(loop);
      el.append(v);
      return new Promise((done) => {
        const fail = setTimeout(() => done(false), 15000);
        v.onerror = () => { clearTimeout(fail); done(false); };
        v.onplaying = () => {
          clearTimeout(fail);
          v.onplaying = null;
          v.classList.add("on"); // the new picture covers the last one only once it moves: no black between films
          for (const old of el.querySelectorAll("video")) if (old !== v) { old.pause(); old.remove(); }
          done(true);
        };
        v.onloadedmetadata = () => {
          v.onloadedmetadata = null;
          if (from > 0) { v.onseeked = () => { v.onseeked = null; v.play().catch(() => {}); }; v.currentTime = from; }
          else v.play().catch(() => {});
        };
        v.preload = "auto";
        v.src = src;
      });
    },
    filmOut(rect) {
      const el = document.getElementById("demo-film");
      if (!el) return;
      el.style.transition = rect ? "transform 700ms cubic-bezier(.22, 1, .36, 1), opacity 260ms ease 480ms" : "opacity 220ms";
      if (rect) el.style.transform = "translate(" + rect.x + "px, " + rect.y + "px) scale(" + rect.width / innerWidth + ", " + rect.height / innerHeight + ")";
      el.style.opacity = "0";
      window.__demo.chip(null);
      setTimeout(() => { if (el.style.opacity === "0") for (const v of el.querySelectorAll("video")) { v.pause(); v.remove(); } window.__demo.place(); }, 760);
    },
    chip(text) {
      mount();
      const el = document.getElementById("demo-chip");
      if (text) el.textContent = text;
      el.style.opacity = text ? "1" : "0";
      el.style.transform = text ? "none" : "translateX(28px)";
    },
    tracker(op) {
      mount();
      const el = document.getElementById("demo-tracker");
      if (op.items) {
        el.textContent = "";
        el.append(Object.assign(document.createElement("div"), { className: "demo-tracker-title", textContent: op.title ?? "" }));
        for (const text of op.items) {
          const item = Object.assign(document.createElement("div"), { className: "demo-tracker-item", textContent: text });
          item.dataset.key = String(text).split(" ")[0];
          el.append(item);
        }
        el.style.opacity = "1";
      }
      if (op.tick) for (const item of el.querySelectorAll(".demo-tracker-item")) if (item.dataset.key === op.tick) item.classList.add("done");
      if (op.clear) el.style.opacity = "0";
      window.__demo.place();
    },
    place() { // top right of the workspace: beside the dock while it is open, at the edge over a film or in cinema
      const el = document.getElementById("demo-tracker");
      if (!el) return;
      const app = document.querySelector(".app");
      const film = document.getElementById("demo-film");
      const dock = app && app.dataset.dock === "open" && app.dataset.cinema !== "true" && !(film && film.style.opacity === "1") ? document.querySelector(".dock") : null;
      el.style.right = (dock ? dock.getBoundingClientRect().width + 20 : 20) + "px";
    },
  };
})();`;

const b = await launch({ width, height });
const frames = [];
const lapses = [];
const cues = [];
const now = () => Date.now() / 1000;
let startedAt = null;

const writing = new Set(); // frame files still being written: a slow disk must never hold up the screencast or the steps
// OPENFIELD_FRAME_CAP=30 drops a frame that comes less than 3/4 of a 30 fps interval after the last one kept (the cut is
// 30 fps): a page playing video sends 60, and the frames for a two-minute cut then need half the disk. Unset, all are kept.
const frameCap = Number(process.env.OPENFIELD_FRAME_CAP ?? 0) || 0;
const minGap = frameCap > 0 ? 1 / frameCap - 1 / (4 * frameCap) : 0;
b.on("Page.screencastFrame", (p) => {
  b.send("Page.screencastFrameAck", { sessionId: p.sessionId }).catch(() => {});
  if (minGap && frames.length && p.metadata.timestamp - frames.at(-1).ts < minGap) return; // too soon after the last kept frame
  const file = `frame-${String(frames.length + 1).padStart(6, "0")}.jpg`;
  frames.push({ file, ts: p.metadata.timestamp });
  const job = writeFile(join(framesDir, file), Buffer.from(p.data, "base64")).finally(() => writing.delete(job));
  writing.add(job);
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
  async say(s) {
    const caption = s.caption == null ? null : fill(s.caption);
    const tag = caption && s.tag ? fill(s.tag) : null; // a tag belongs to a caption that is on screen
    cues.push({ at: now(), text: fill(s.text), caption, tag });
    if (typeof s.caption === "string") await ev(`window.__demo.caption(${JSON.stringify(caption)}, ${JSON.stringify(tag)})`);
    else if (s.caption === null) await ev("window.__demo.caption(null)");
  },
  async caption(s) {
    const text = s.text == null ? null : fill(s.text);
    const tag = text && s.tag ? fill(s.tag) : null; // no text clears the tag with it
    await ev(`window.__demo.caption(${JSON.stringify(text)}, ${JSON.stringify(tag)})`);
    cues.push({ at: now(), text: null, caption: text, tag });
  },
  async card(s) {
    if (s.clear) {
      await ev("window.__demo.card(null)");
      return;
    }
    const lines = (s.lines ?? []).filter((line) => !missing(line)).map(fill).slice(0, 4);
    const mono = s.mono && !missing(s.mono) ? fill(s.mono) : "";
    const statement = s.statement ? fill(s.statement) : null;
    await ev(`window.__demo.card(${JSON.stringify({ title: fill(s.title), lines, mono, statement, dim: s.dim ?? null })})`);
    if (!s.hold) {
      await b.sleep(s.ms ?? 3000);
      await ev("window.__demo.card(null)");
    }
  },
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
  async hover(s) {
    const r = await need(s.selector, s.text);
    await glideTo(r);
    await b.sleep(s.ms ?? 1600);
  },
  async sweep(s) {
    const r = await need(s.selector, s.text);
    const y = r.y + r.height / 2;
    const at = (f) => r.x + r.width * f;
    const from = s.from ?? 0.1;
    const to = s.to ?? 0.9;
    const ms = s.ms ?? 1600;
    const n = Math.max(12, Math.round(ms / 40));
    await glideTo({ cx: at(from), cy: y });
    for (const [a, z] of [[from, to], ...(s.back ? [[to, from]] : [])]) {
      for (let i = 1; i <= n; i += 1) {
        const x = at(a + ((z - a) * i) / n);
        await ev(`window.__demo.move(${x}, ${y})`);
        await b.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
        await b.sleep(ms / n);
      }
    }
  },
  async ring(s) {
    const r = await need(s.selector, s.text);
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
  async film(s) {
    if (s.clear) {
      const rect = s.into ? await box(s.into) : null;
      await ev(`window.__demo.filmOut(${JSON.stringify(rect)})`);
      await b.sleep(rect ? 760 : 260);
      return;
    }
    await ev("window.__demo.cover()"); // black at once: the app never flashes before the picture
    let src = null;
    if (s.take) {
      // the app opens the take behind the picture, so its receipt is the one on screen (and in the chip)
      if (!(await ev(`window.openfield.ui.openTake(${JSON.stringify(s.take)})`))) throw new Error(`no such take: ${s.take}`);
      src = await ev(`(() => { const st = window.openfield.store.get(); const t = [...st.takes, ...st.recorded].find((x) => x.id === ${JSON.stringify(s.take)}); return t ? window.openfield.api.media(t, (t.outputs ?? []).find((o) => o.role === "video")?.file ?? "take.mp4") : null; })()`);
    } else if (s.src && clipBase) src = `${clipBase}/${encodeURIComponent(s.src)}`;
    if (!src) throw new Error(s.take ? `no video for ${s.take}` : "film { src } needs --clips");
    let verdict = null;
    if (s.chip) { // the verdict as the take's receipt pane prints it: audit, identity, checksum
      await b.waitFor("/Checksum/.test(document.querySelector('.dock-pane[data-pane=take] .seal-line')?.textContent ?? '')", { timeout: 15000, label: "the take's receipt" });
      verdict = await ev(`(() => { const v = document.querySelector('.dock-pane[data-pane=take] .verdict'); const pass = v.querySelector('.id-reading')?.dataset.status === 'pass'; return [v.querySelector('.audit-head .pill')?.textContent.trim(), pass ? v.querySelector('.identity-top strong').textContent.trim() + ' ' + v.querySelector('.id-score').textContent.trim() : null, v.querySelector('.seal-line .pill')?.textContent.trim()].filter(Boolean).join('  ·  '); })()`);
    }
    if (!(await ev(`window.__demo.film(${JSON.stringify(src)}, ${Number(s.from ?? 0)}, ${Boolean(s.loop)})`))) throw new Error(`could not play ${s.take ?? s.src}`);
    // `ms` lets record_demo.py cut the film's sound to the length of the film: the time it really stays, which a caption or
    // chip timed after `ms` stretches; a take's sound is `sound`, a clip's is `clip_sound`
    const stays = Math.max(Number(s.ms ?? 5000), s.caption !== undefined ? Number(s.captionAt ?? 0) : 0, verdict ? Number(s.chipAt ?? 0) : 0);
    cues.push({ at: now(), text: null, caption: null, film: s.take ?? s.src, from: Number(s.from ?? 0), ms: stays,
      sound: s.sound && s.take ? s.take : null, clip_sound: s.sound && !s.take && s.src ? s.src : null });
    const events = [];
    if (s.caption !== undefined) events.push([s.captionAt ?? 0, async () => {
      const text = s.caption == null ? null : fill(s.caption);
      const tag = text && s.captionTag ? fill(s.captionTag) : null;
      await ev(`window.__demo.caption(${JSON.stringify(text)}, ${JSON.stringify(tag)})`);
      cues.push({ at: now(), text: null, caption: text, tag });
    }]);
    if (verdict) events.push([s.chipAt ?? 0, () => ev(`window.__demo.chip(${JSON.stringify(verdict)})`)]);
    let elapsed = 0;
    for (const [at, run] of events.sort((x, y) => x[0] - y[0])) { await b.sleep(Math.max(0, at - elapsed)); elapsed = Math.max(elapsed, at); await run(); }
    await b.sleep(Math.max(0, stays - elapsed));
    if (!s.hold) { await ev("window.__demo.filmOut(null)"); await b.sleep(260); }
  },
  async tracker(s) {
    await ev(`window.__demo.tracker(${JSON.stringify({ title: s.title == null ? null : fill(s.title), items: s.items ? s.items.map(fill) : null, tick: s.tick ?? null, clear: Boolean(s.clear) })})`);
  },
};

try {
  await b.addInitScript(OVERLAY);
  await b.emulate([{ name: "prefers-reduced-motion", value: "no-preference" }]); // the recording shows the app with its motion
  await b.goto(url);
  await b.waitFor("window.openfield?.store.get().loaded", { timeout: 30000, label: "the app loads" });
  await b.sleep(800);
  // OPENFIELD_JPEG_QUALITY lowers the captured frames' quality when the disk is short (about 1 GB of frames at 92)
  const quality = Math.min(100, Math.max(50, Number(process.env.OPENFIELD_JPEG_QUALITY ?? 92) || 92));
  await b.send("Page.startScreencast", { format: "jpeg", quality, maxWidth: width, maxHeight: height, everyNthFrame: 1 });
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
  clipServer?.close();
}

if (!frames.length) {
  console.error("the browser sent no frames");
  process.exit(1);
}
await Promise.all(writing); // every frame on disk before the concat list names it

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
  cues: cues.map((c) => ({ video_s: +videoTimeAt(c.at).toFixed(2), text: c.text, caption: c.caption ?? null, tag: c.tag ?? null,
    ...(c.film ? { film: c.film, from: c.from, ms: c.ms, sound: c.sound, clip_sound: c.clip_sound } : {}) })),
}, null, 2));
console.log(`recorded ${frames.length} frames, ${video.toFixed(1)} s of video, ${cues.length} narration cue(s), backend: ${backend || "unknown"}`);
