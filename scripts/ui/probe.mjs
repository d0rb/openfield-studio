// A look at the rooms at the widths where the layout changes: one JSON line per width and room, and a picture of each.
//   node scripts/ui/probe.mjs <url> <outdir>
// Each line says how the light layers are shown (their computed display, null when the page has none), whether the page
// scrolls sideways, and which rail item is marked current. From 900px wide two more pictures per width: the pointer on a
// wall tile (Takes) and the pointer on a rail item. Pictures go to <outdir>/<width>-<room>[-state].png. A probe, not a
// test: it exits 0 unless the run itself breaks, and ends with a count of the rows that scroll sideways.

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { launch } from "./browser.mjs";

const [url, outdir] = process.argv.slice(2);
if (!url || !outdir) {
  console.error("usage: node scripts/ui/probe.mjs <url> <outdir>");
  process.exit(2);
}
mkdirSync(outdir, { recursive: true });

const WIDTHS = [
  { width: 390, height: 844, mobile: true, scale: 2 },
  { width: 719, height: 900, mobile: true, scale: 1 },
  { width: 720, height: 900, mobile: false, scale: 1 },
  { width: 899, height: 900, mobile: false, scale: 1 },
  { width: 1179, height: 900, mobile: false, scale: 1 },
  { width: 1440, height: 900, mobile: false, scale: 1 },
];
const ROOMS = ["lobby", "direct", "takes", "cast"];
const SETTLE_MS = 1200; // a room's entrance and its first pictures

const READ = `(() => {
  const shown = (sel) => { const el = document.querySelector(sel); return el ? getComputedStyle(el).display : null; };
  return {
    ambient: shown(".ambient"),
    houseLight: shown(".house-light"),
    noSideScroll: document.documentElement.scrollWidth <= innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth,
    rail: document.querySelector(".rail-item[aria-current=page]")?.dataset.route ?? null,
    mark: document.querySelector(".rail-mark")?.closest(".rail-item")?.dataset.route ?? null,
  };
})()`;
/** The centre of the first element matching `selector`, scrolled into view, or null. */
const centre = (selector) => `(() => { const e = document.querySelector(${JSON.stringify(selector)}); if (!e) return null; e.scrollIntoView({ block: "nearest" }); const r = e.getBoundingClientRect(); return r.width ? { x: r.x + r.width / 2, y: r.y + r.height / 2 } : null; })()`;

const b = await launch({ width: 1440, height: 900 });
const shot = (name) => b.screenshot(join(outdir, `${name}.png`), { writeFileSync });
const pointAt = async (selector) => {
  const at = await b.eval(centre(selector));
  if (at) await b.send("Input.dispatchMouseEvent", { type: "mouseMoved", ...at });
  return Boolean(at);
};
const rest = () => b.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 1, y: 1 }); // off every tile and item
const rows = [];
try {
  await b.emulate([{ name: "prefers-reduced-motion", value: "no-preference" }]); // the rooms as they move
  for (const size of WIDTHS) {
    await b.viewport(size.width, size.height, size.mobile, size.scale);
    await b.goto(url.replace(/#.*$/, "")); // loaded again at each width: some choices are made as the page is built
    await b.waitFor("window.openfield?.store.get().loaded", { label: `the app loads at ${size.width}px` });
    for (const room of ROOMS) {
      const row = { width: size.width, room };
      try {
        await rest();
        await b.eval(`location.hash = "#/${room}"`);
        await b.waitFor(`window.openfield.store.get().route === "${room}"`, { label: `the ${room} room` });
        await b.sleep(SETTLE_MS);
        Object.assign(row, await b.eval(READ));
        await shot(`${size.width}-${room}`);
        if (size.width >= 900) {
          if (room === "takes") {
            row.wallTile = await pointAt(".wall .wall-tile");
            await b.sleep(400);
            await shot(`${size.width}-takes-hover`);
          }
          // a room that is not one of the four, so its hover shows against the current item's mark
          row.railItem = await pointAt(".rail-item[data-route=shots]");
          await b.sleep(300);
          await shot(`${size.width}-${room}-rail`);
        }
      } catch (error) {
        row.error = error.message.slice(0, 200);
      }
      rows.push(row);
      console.log(JSON.stringify(row));
    }
  }
  if (b.log.errors.length) console.log(`page errors: ${b.log.errors.slice(0, 3).join(" | ").slice(0, 300)}`);
} finally {
  await b.close();
}
const sideways = rows.filter((r) => r.noSideScroll === false);
const broken = rows.filter((r) => r.error);
console.log(`probe: ${rows.length} rows, ${sideways.length} with sideways scroll${sideways.length ? ` (${sideways.map((r) => `${r.width}-${r.room}`).join(", ")})` : ""}, `
  + `${broken.length} that failed${broken.length ? ` (${broken.map((r) => `${r.width}-${r.room}`).join(", ")})` : ""}`);
