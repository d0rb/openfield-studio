// How much a first visit to the hosted copy downloads: every response's size over the first `secs` seconds, with motion allowed,
// and what GitHub Pages would send for the same visit (it gzips text, so each text response counts at `gzip -9` of its body).
// usage: node transfer.mjs <url> [secs]
//   no option: the whole matrix, one fresh browser each: 1440x900 at 1x, 1440x900 at 2x, 390x844 mobile at 3x, and 1440x900
//   with Save-Data on, which must fetch no MP4 at all (the exit code is 1 when it does).
//   options (any of them runs that one setup instead): --scale N (device pixels per CSS pixel)  --mobile (390x844, touch)
//   --save-data  --width W  --height H
import { gzipSync } from "node:zlib";
import { launch } from "./browser.mjs";

const args = process.argv.slice(2);
const VALUE_FLAGS = ["--scale", "--width", "--height"];
const value = (name) => { const at = args.indexOf(name); return at >= 0 ? args[at + 1] : undefined; };
const positional = args.filter((a, i) => !a.startsWith("--") && !VALUE_FLAGS.includes(args[i - 1]));
const given = (positional[0] ?? "http://127.0.0.1:8899/");
const url = given.endsWith("/") ? given : `${given}/`;
const secs = Number(positional[1] ?? 12);

const MATRIX = [
  { width: 1440, height: 900, scale: 1 },
  { width: 1440, height: 900, scale: 2 },
  { width: 390, height: 844, scale: 3, mobile: true },
  { width: 1440, height: 900, scale: 1, saveData: true },
];
const mobile = args.includes("--mobile");
const chosen = ["--scale", "--width", "--height", "--mobile", "--save-data"].some((f) => args.includes(f));
const setups = chosen ? [{
  width: Number(value("--width") ?? (mobile ? 390 : 1440)), height: Number(value("--height") ?? (mobile ? 844 : 900)),
  scale: Number(value("--scale") ?? (mobile ? 3 : 1)), mobile, saveData: args.includes("--save-data"),
}] : MATRIX;

// a text response is sent gzipped by GitHub Pages: html, scripts, styles, json and svg, by extension (the page itself is the folder's address)
const TEXT = /\.(html|js|mjs|css|json|svg)$/i;
const isText = (address) => { const path = new URL(address).pathname; return TEXT.test(path) || path.endsWith("/"); };
const isVideo = (address) => /\.(mp4|webm)(\?|#|$)/.test(address);
const mb = (bytes) => `${(bytes / 1e6).toFixed(2)} MB`;

async function measure({ width, height, scale, mobile: phone = false, saveData = false }) {
  const label = `${width}x${height} @${scale}x${phone ? " mobile" : ""}${saveData ? ", Save-Data" : ""}`;
  const b = await launch({ width, height, mobile: phone, scale });
  let failed = false;
  try {
    await b.send("Network.enable", { maxTotalBufferSize: 200e6, maxResourceBufferSize: 60e6 });
    await b.send("Network.setCacheDisabled", { cacheDisabled: true });
    if (phone) await b.send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
    if (saveData) await b.addInitScript("Object.defineProperty(navigator,'connection',{value:{saveData:true},configurable:true})");
    const seen = new Map(); // request id -> what came back for it
    b.on("Network.requestWillBeSent", (e) => { if (!e.request.url.startsWith("data:")) seen.set(e.requestId, { url: e.request.url, status: 0, wire: 0, streamed: 0, done: false }); });
    b.on("Network.responseReceived", (e) => { const r = seen.get(e.requestId); if (r) r.status = e.response.status; });
    b.on("Network.dataReceived", (e) => { const r = seen.get(e.requestId); if (r) r.streamed += e.encodedDataLength || 0; });
    b.on("Network.loadingFinished", (e) => { const r = seen.get(e.requestId); if (r) { r.wire = e.encodedDataLength; r.done = true; } });
    await b.emulate([{ name: "prefers-reduced-motion", value: "no-preference" }]);
    await b.goto(`${url}#/lobby`);
    await new Promise((resolve) => setTimeout(resolve, secs * 1000));

    // a loop still downloading when the window ends counts for what has arrived; a text response for its body gzipped at -9
    const rows = [];
    for (const [id, r] of seen) {
      if (!r.status && !r.streamed && !r.wire) continue;
      const wire = r.done ? r.wire : r.streamed;
      let pages = wire;
      let raw = 0;
      if (r.done && r.status === 200 && isText(r.url)) {
        try {
          const { body, base64Encoded } = await b.send("Network.getResponseBody", { requestId: id });
          const bytes = Buffer.from(body, base64Encoded ? "base64" : "utf8");
          raw = bytes.length;
          pages = gzipSync(bytes, { level: 9 }).length;
        } catch { /* the browser no longer holds that body: it counts at its wire size */ }
      }
      rows.push({ url: r.url.replace(new URL(url).origin, ""), wire, pages, raw, status: r.status, video: isVideo(r.url) });
    }
    const wire = rows.reduce((n, r) => n + r.wire, 0);
    const pages = rows.reduce((n, r) => n + r.pages, 0);
    const timing = await b.eval("performance.getEntriesByType('resource').reduce((n, e) => n + (e.transferSize || 0), 0) + (performance.getEntriesByType('navigation')[0]?.transferSize || 0)");
    const videos = rows.filter((r) => r.video);
    const videoBytes = videos.reduce((n, r) => n + r.wire, 0);

    console.log(`${label}: ${mb(wire)} on the wire in ${secs} s, Pages estimate ${mb(pages)} (resource timing says ${mb(timing)})`);
    const texts = rows.filter((r) => r.raw);
    console.log(`   text: ${texts.length} file(s), ${mb(texts.reduce((n, r) => n + r.raw, 0))} raw, ${mb(texts.reduce((n, r) => n + r.pages, 0))} at gzip -9`);
    console.log(`   MP4: ${mb(videoBytes)} in ${videos.length} file(s)` + (videos.length ? `; ${videos.sort((p, q) => q.wire - p.wire).slice(0, 4).map((r) => `${r.url.replace(/^.*\//, "")} ${(r.wire / 1e6).toFixed(2)}`).join(", ")}` : ""));
    console.log(`   ${"wire".padStart(8)}  ${"Pages".padStart(8)}  response`);
    for (const r of [...rows].sort((p, q) => q.pages - p.pages).slice(0, 10)) console.log(`   ${mb(r.wire).padStart(8)}  ${mb(r.pages).padStart(8)}  ${r.url.slice(0, 90)}`);
    const bad = rows.filter((r) => r.status >= 400);
    if (bad.length) console.log(`   ${bad.length} answered 4xx or 5xx: ${bad.slice(0, 4).map((r) => `${r.status} ${r.url}`).join(", ")}`);
    if (saveData) {
      failed = videoBytes > 0;
      console.log(failed ? `   FAIL: Save-Data fetched ${videoBytes} bytes of MP4` : "   OK: Save-Data fetched 0 bytes of MP4");
    }
  } finally { await b.close(); }
  return !failed;
}

let ok = true;
for (const setup of setups) ok = (await measure(setup)) && ok;
process.exitCode = ok ? 0 : 1;
