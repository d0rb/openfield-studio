import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { SHEET, modelFamilies, sheetFacts, sheetLayout, sheetTimes, stamp, wrap } from "../../openfield/web/js/lib/shotsheet.js";
import { drawStage, planOf } from "../../openfield/web/js/lib/overlay.js";

const receipt = JSON.parse(readFileSync(new URL("./fixtures/receipt-bullet-time.json", import.meta.url), "utf8"));

const catalog = JSON.parse(readFileSync(new URL("./fixtures/catalog.json", import.meta.url), "utf8"));

test("the sheet names the model families, not every file", () => {
  assert.deepEqual(modelFamilies(receipt), ["Qwen-Image 2.1", "LTX 2.5"]);
  assert.deepEqual(modelFamilies({ models: [{ role: "animate:wan-animate-2" }, { role: "vae" }, { role: "upscale:some-new-model" }] }), ["Wan Animate 2", "Some New Model"]);
  assert.deepEqual(modelFamilies(null), []);
});

test("the receipt's facts, in order, and nothing the receipt does not hold", () => {
  const rows = Object.fromEntries(sheetFacts({ seconds: 5 }, receipt));
  assert.equal(rows.Seed, "1160");
  assert.equal(rows.Length, "5 s");
  assert.equal(rows.Quality, "Standard");
  assert.equal(rows.Models, "Qwen-Image 2.1 · LTX 2.5");
  assert.equal(rows["GPU time"], "217 s");
  assert.match(rows.Cost, /^about \d/);
  assert.equal(rows.Checked, "Open weights only");
  assert.equal(rows.Receipt, receipt.integrity.digest.slice(0, 16));
  assert.deepEqual(sheetFacts({ seconds: 3 }, null), [["Length", "3 s"]]);
});

test("frames, stamps and lines that fit", () => {
  assert.deepEqual(sheetTimes(5), [0.05, 2.5, 4.85]);
  assert.deepEqual(sheetTimes(0), [0, 0, 0]);
  assert.equal(stamp(2.5), "00:02.5");
  assert.equal(stamp(75.25), "01:15.3");
  const measure = (t) => t.length * 10;
  assert.deepEqual(wrap("one two three four five six seven", 100, measure, 2), ["one two", "three…"]);
  assert.deepEqual(wrap("short", 100, measure), ["short"]);
  assert.deepEqual(wrap("", 100, measure), []);
});

test("no receipt: the length alone, and nothing said to be checked", () => {
  assert.deepEqual(sheetFacts({ seconds: 3 }, null), [["Length", "3 s"]]);
  assert.deepEqual(sheetFacts({ seconds: 3, audit: { result: "pass" } }, null), [["Length", "3 s"]], "only the receipt's audit counts");
  assert.deepEqual(sheetFacts({}, null), []);
});

test("a receipt with no GPU timings shows no GPU time and no cost", () => {
  const bare = { inputs: { seed: 7, quality: "fast", rig: { duration_seconds: 4 } }, models: [{ role: "image:qwen-image-2.1" }],
    audit: { result: "pass" }, integrity: { alg: "sha256", digest: "ab".repeat(32) } };
  assert.deepEqual(sheetFacts({ seconds: 4 }, bare).map(([label]) => label), ["Seed", "Length", "Quality", "Models", "Checked", "Receipt"]);
  for (const backend of [{}, { timings: {} }, { timings: { total_s: 0 } }, { timings: { total_s: "217" } }]) {
    const labels = sheetFacts({ seconds: 4 }, { ...bare, backend }).map(([label]) => label);
    assert.ok(!labels.includes("GPU time") && !labels.includes("Cost"), JSON.stringify(backend));
  }
});

test("a word longer than the line is broken with a hyphen, so no line runs past the edge", () => {
  const measure = (t) => t.length * 10;
  assert.deepEqual(wrap("a supercalifragilistic word", 100, measure), ["a", "supercali-", "fragilist-", "ic word"]);
  assert.deepEqual(wrap("supercalifragilistic", 100, measure, 1), ["supercali…"], "a cut line ends in the ellipsis, not the hyphen");
  // type of uneven widths: narrow i and l, wide m and w
  const uneven = (t) => [...t].reduce((sum, c) => sum + ({ i: 4, l: 4, m: 14, w: 14, " ": 5, "-": 6, "…": 12 }[c] ?? 9), 0);
  const text = "mmmmmmmmmmmmmmmmmmmmmmmmm illllllllliiiiiiiiiiiiiiiiiil https://openfield.example/takes/tk_20261025_143143_2192 wow";
  for (const max of [60, 97, 150]) {
    for (const lines of [Infinity, 2]) {
      const out = wrap(text, max, uneven, lines);
      assert.ok(out.length && out.every((line) => uneven(line) <= max), `${max}/${lines}: ${JSON.stringify(out)}`);
      if (lines === Infinity) assert.equal(out.join(" ").replace(/- /g, ""), text, "nothing is lost: the pieces join back up");
    }
  }
});

test("a portrait take's stage fits the sheet: the camera's 9:16 frame, its path and the marks stay in the box", () => {
  const L = sheetLayout();
  const box = { x: L.stage.x, y: L.stage.y + 16, w: L.stage.w, h: L.stage.h }; // where ui/shotsheet.js draws it
  const colors = new Proxy({}, { get: () => "#000" });
  for (const aspect of [9 / 16, 16 / 9]) {
    for (const move of catalog.moves) {
      const points = [];
      let strokes = 0; // the floor's grid is the first stroke and runs past the edges on purpose
      const g = new Proxy({}, {
        get: (own, name) => (name in own ? own[name] : (...a) => {
          if (name === "stroke") strokes++;
          if (["arc", "ellipse"].includes(name) || (strokes && ["moveTo", "lineTo"].includes(name))) points.push({ x: a[0], y: a[1], r: name === "arc" || name === "ellipse" ? a[2] : 0 });
        }),
        set: (own, name, value) => { own[name] = value; return true; },
      });
      const { hollow, anchors } = planOf(move, null, {});
      drawStage(g, { poses: move.path, anchors, t: 0.85, hollow, aspect, box, colors });
      const outside = points.filter((p) => p.x - p.r < box.x || p.x + p.r > box.x + box.w || p.y - p.r < box.y || p.y + p.r > box.y + box.h);
      assert.deepEqual(outside, [], `${move.id} at ${aspect < 1 ? "9:16" : "16:9"}`);
    }
  }
});

test("the sheet's boxes stay apart and inside the card", () => {
  const L = sheetLayout();
  const right = (b) => b.x + (b.w ?? b.width);
  assert.ok(right(L.frames[2]) <= SHEET.width - SHEET.pad);
  assert.ok(L.frames.every((f, i) => i === 0 || f.x >= right(L.frames[i - 1])));
  assert.ok(right(L.words) <= L.facts.x && right(L.facts) <= L.stage.x, "words, facts and stage side by side");
  assert.ok(L.stage.y + L.stage.h + 16 < L.footer.y - 20, "the stage ends above the footer");
  assert.ok(L.frames[0].y + L.frames[0].h < L.words.y, "the frames above the words");
});
