// Frame pacing under the hand: the pointer sweeps the stage for ten seconds while the page counts its frames. Usage:
//   node scripts/ui/frames.mjs <url> [takes|lobby] [--rooms]
// On Takes it waits until twelve wall loops play first; --rooms switches between Takes and Direct every 2 s during the
// sweep. Prints the frames counted, the longest and the 95th-percentile frame, the frames over 32 ms (after the first
// 500 ms) and how busy the main thread was. Exits 1 when any frame took over 32 ms.

import { launch } from "./browser.mjs";

const args = process.argv.slice(2);
const rooms = args.includes("--rooms");
const [url, room = "takes"] = args.filter((a) => !a.startsWith("--"));
if (!url || !["takes", "lobby"].includes(room)) {
  console.error("usage: node scripts/ui/frames.mjs <url> [takes|lobby] [--rooms]");
  process.exit(2);
}

const SWEEP_MS = 10_000;
const HZ = 60;
const SKIP_MS = 500; // the first frames of a sweep pay for its start: they are counted, not judged

const b = await launch({ width: 1440, height: 900 });
const metric = async (name) => (await b.send("Performance.getMetrics")).metrics.find((m) => m.name === name)?.value ?? 0;
let failed = false;
try {
  await b.emulate([{ name: "prefers-reduced-motion", value: "no-preference" }]);
  await b.goto(`${url.replace(/#.*$/, "")}#/${room}`);
  await b.waitFor("window.openfield?.store.get().loaded", { label: "the app loads" });
  if (room === "takes") {
    await b.waitFor("[...document.querySelectorAll('.wall video.live-clip')].filter((v) => !v.paused && v.currentTime > 0).length >= 12",
      { timeout: 30000, label: "twelve wall loops play" });
  }
  await b.sleep(500); // the room settles before anything is measured
  await b.send("Performance.enable");
  const busyBefore = await metric("TaskDuration");
  // one [time since the sweep began, frame length] pair per frame, at most 600 (ten seconds at 60 Hz)
  await b.eval(`(() => {
    window.__frames = [];
    const t0 = performance.now();
    let last = 0;
    const step = (now) => {
      if (last) window.__frames.push([now - t0, now - last]);
      last = now;
      if (window.__frames.length < 600) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
    return true;
  })()`);
  const box = await b.eval("(() => { const r = document.querySelector('.stage').getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; })()");
  const start = Date.now();
  let sent = 0;
  let nextRoom = 2000;
  let away = false;
  while (Date.now() - start < SWEEP_MS) {
    const t = (Date.now() - start) / 1000;
    // a Lissajous figure (3 across to 2 down) inside the stage, 6% in from its edges
    const x = box.x + box.w * (0.5 + 0.44 * Math.sin(2 * Math.PI * 0.3 * t + Math.PI / 2));
    const y = box.y + box.h * (0.5 + 0.44 * Math.sin(2 * Math.PI * 0.2 * t));
    await b.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
    sent += 1;
    if (rooms && Date.now() - start >= nextRoom) {
      away = !away;
      nextRoom += 2000;
      await b.eval(`window.openfield.ui.go(${JSON.stringify(away ? "direct" : "takes")}); true`);
    }
    // paced against the clock: a slow round trip shortens the next wait instead of stretching the sweep
    const wait = start + (sent * 1000) / HZ - Date.now();
    if (wait > 0) await b.sleep(wait);
  }
  const seconds = (Date.now() - start) / 1000;
  const busy = (await metric("TaskDuration")) - busyBefore;
  const samples = await b.eval("window.__frames");
  const lengths = samples.map(([, d]) => d);
  const sorted = [...lengths].sort((a, z) => a - z);
  const max = sorted.at(-1) ?? 0;
  const p95 = sorted.length ? sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * 0.95) - 1)] : 0;
  const median = sorted[sorted.length >> 1] ?? 0;
  const over32 = samples.filter(([at, d]) => at >= SKIP_MS && d > 32).length;
  failed = over32 > 0;
  // the span: 600 frames are ten seconds at 60 Hz, less on a faster screen
  console.log(`${room}${rooms ? " --rooms" : ""}: frames ${samples.length} over ${((samples.at(-1)?.[0] ?? 0) / 1000).toFixed(1)} s  `
    + `median ${median.toFixed(1)} ms  max ${max.toFixed(1)} ms  p95 ${p95.toFixed(1)} ms  over32 ${over32}  `
    + `mainThreadBusy ${(busy / seconds).toFixed(3)} (${busy.toFixed(2)} s of ${seconds.toFixed(1)} s, ${sent} pointer moves)`);
  if (b.log.errors.length) console.log(`page errors: ${b.log.errors.slice(0, 3).join(" | ").slice(0, 300)}`);
} catch (error) {
  console.error(`the run stopped: ${error.message}`);
  failed = true;
} finally {
  await b.close();
}
process.exit(failed ? 1 : 0);
