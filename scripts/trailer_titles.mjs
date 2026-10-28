// Render the trailer's title cards as transparent PNGs with the site's own type, for scripts/make_trailer.py to lay
// over the cut. Each segment of showcase/trailer.spec.json with a "title" gets one: "First line / second line", the
// second line in the accent colour, set the way the demo's captions are. The spec's "card" (the end card: the mark, the
// name, a tagline and a two-tone statement) gets card.png with its own dark scrim baked in.
//
//   node scripts/trailer_titles.mjs --spec showcase/trailer.spec.json --out <folder> [--width 1280 --height 704]
//
// The fonts are served to the page from openfield/web by a throwaway local server, so no file:// font rule gets in the
// way; the browser is whichever Edge or Chrome scripts/ui/browser.mjs finds.
import { createServer } from "node:http";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { launch } from "./ui/browser.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const WEB = resolve(here, "..", "openfield", "web");
const args = Object.fromEntries(process.argv.slice(2).map((a, i, all) => (a.startsWith("--") ? [a.slice(2), all[i + 1]] : [])).filter((p) => p.length));
if (!args.spec || !args.out) {
  console.error("usage: node scripts/trailer_titles.mjs --spec showcase/trailer.spec.json --out <folder> [--width 1280 --height 704]");
  process.exit(2);
}
const width = Number(args.width ?? 1280);
const height = Number(args.height ?? 704);
const spec = JSON.parse(readFileSync(resolve(args.spec), "utf8"));
const out = resolve(args.out);
mkdirSync(out, { recursive: true });

const TYPES = { ".html": "text/html; charset=utf-8", ".css": "text/css", ".woff2": "font/woff2", ".svg": "image/svg+xml", ".webp": "image/webp", ".png": "image/png" };
// the page: the same measures as the demo recorder's captions at 1920 px, scaled to the trailer's frame
const k = width / 1920;
const page = `<!doctype html><html><head><meta charset="utf-8"><style>
@font-face { font-family: "Barlow"; src: url("/fonts/barlow-latin-400.woff2") format("woff2"); font-weight: 400; }
@font-face { font-family: "Barlow"; src: url("/fonts/barlow-latin-600.woff2") format("woff2"); font-weight: 600; }
@font-face { font-family: "Barlow Condensed"; src: url("/fonts/barlow-condensed-latin-800.woff2") format("woff2"); font-weight: 800; }
@font-face { font-family: "Overpass Mono"; src: url("/fonts/overpass-mono-latin-wght.woff2") format("woff2"); font-weight: 300 700; }
html, body { margin: 0; background: transparent; width: ${width}px; height: ${height}px; overflow: hidden; }
#title { position: absolute; left: 0; right: 0; bottom: 0; padding: ${Math.round(150 * k)}px ${Math.round(64 * k)}px ${Math.round(52 * k)}px; color: #f4f1ec;
  font: 800 ${Math.round(88 * k)}px/0.96 "Barlow Condensed", sans-serif; text-transform: uppercase; letter-spacing: .004em;
  background: linear-gradient(to top, rgba(8, 8, 7, .8) 0%, rgba(8, 8, 7, .52) 42%, rgba(8, 8, 7, 0) 100%); }
#title .line { max-width: 74%; text-shadow: 0 2px ${Math.round(20 * k)}px rgba(0, 0, 0, .6); }
#title .second { display: block; color: #ff7a1a; }
#card { position: absolute; inset: 0; display: none; place-items: center; text-align: center; color: #f4f1ec; background: rgba(8, 8, 7, .74); }
#card .inner { display: grid; justify-items: center; gap: ${Math.round(14 * k)}px; }
#card svg { width: ${Math.round(56 * k)}px; height: ${Math.round(56 * k)}px; fill: #ff7a1a; }
#card .name { font: 600 ${Math.round(48 * k)}px/1.15 "Barlow", sans-serif; }
#card .tagline { font: 400 ${Math.round(22 * k)}px/1.4 "Barlow", sans-serif; color: #aba59d; }
#card .statement { margin-top: ${Math.round(6 * k)}px; font: 800 ${Math.round(58 * k)}px/1.0 "Barlow Condensed", sans-serif; text-transform: uppercase; letter-spacing: .005em; }
#card .statement .second { display: block; color: #ff7a1a; }
#card .mono { font: 500 ${Math.round(16 * k)}px/1.8 "Overpass Mono", monospace; letter-spacing: .04em; color: #aba59d; white-space: pre-line; }
</style></head><body>
<div id="title"><div class="line"><span class="first"></span><span class="second"></span></div></div>
<div id="card"><div class="inner"><svg viewBox="0 0 20 20" aria-hidden="true"><rect x="2" y="4" width="16" height="3" rx="0.5"/><rect x="8.5" y="7" width="3" height="9" rx="0.5"/></svg>
<div class="name"></div><div class="tagline"></div><div class="statement"><span class="first"></span><span class="second"></span></div><div class="mono"></div></div></div>
</body></html>`;

const server = createServer((req, res) => {
  const path = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (path === "/__titles__.html") { res.writeHead(200, { "content-type": TYPES[".html"] }); res.end(page); return; }
  const file = join(WEB, ...path.split("/").filter((p) => p && p !== ".." && p !== "."));
  if (!file.startsWith(WEB) || !existsSync(file)) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { "content-type": TYPES[extname(file)] ?? "application/octet-stream" });
  res.end(readFileSync(file));
});
await new Promise((ready) => server.listen(0, "127.0.0.1", ready));
const port = server.address().port;

const split = (text) => { const [first, ...rest] = String(text).split(" / "); return [first, rest.join(" / ")]; };
const b = await launch({ width, height });
const made = [];
try {
  await b.goto(`http://127.0.0.1:${port}/__titles__.html`);
  await b.send("Emulation.setDefaultBackgroundColorOverride", { color: { r: 0, g: 0, b: 0, a: 0 } });
  await b.eval(`document.fonts.load('800 10px "Barlow Condensed"').then(() => document.fonts.load('600 10px "Barlow"')).then(() => document.fonts.load('400 10px "Barlow"')).then(() => document.fonts.load('500 10px "Overpass Mono"')).then(() => true)`);
  const ok = await b.eval(`document.fonts.check('800 10px "Barlow Condensed"') && document.fonts.check('600 10px "Barlow"')`);
  if (!ok) throw new Error("the site's fonts did not load in the title page");
  const shoot = async (file) => {
    await b.sleep(80);
    const { data } = await b.send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(out, file), Buffer.from(data, "base64"));
    made.push(file);
  };
  for (const [i, segment] of (spec.segments ?? []).entries()) {
    if (!segment.title) continue;
    const [first, second] = split(segment.title);
    await b.eval(`(() => { const t = document.getElementById("title"); t.style.display = "block"; document.getElementById("card").style.display = "none";
      t.querySelector(".first").textContent = ${JSON.stringify(first)}; t.querySelector(".second").textContent = ${JSON.stringify(second)}; return true; })()`);
    await shoot(`title-${String(i).padStart(2, "0")}.png`);
  }
  if (spec.card) {
    const [first, second] = split(spec.card.statement ?? "");
    await b.eval(`(() => { document.getElementById("title").style.display = "none"; const c = document.getElementById("card"); c.style.display = "grid";
      c.querySelector(".name").textContent = ${JSON.stringify(spec.card.title ?? "")}; c.querySelector(".tagline").textContent = ${JSON.stringify(spec.card.tagline ?? "")};
      c.querySelector(".statement .first").textContent = ${JSON.stringify(first)}; c.querySelector(".statement .second").textContent = ${JSON.stringify(second)};
      c.querySelector(".mono").textContent = ${JSON.stringify(spec.card.mono ?? "")}; return true; })()`);
    await shoot("card.png");
  }
} finally {
  await b.close();
  server.close();
}
console.log(`${made.length} title card(s) at ${width}x${height} in ${out}: ${made.join(", ")}`);
