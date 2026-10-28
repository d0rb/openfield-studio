import test from "node:test";
import assert from "node:assert/strict";

import { captionFor } from "../../openfield/web/js/lib/share.js";

const MOVES = {
  moves: [
    { id: "orbit_90", label: "Orbit 90" },
    { id: "push_in", label: "Push In" },
    { id: "pull_out", label: "Pull Out" },
  ],
};

const direct = (id, subject, movement) => ({ id, kind: "direct", created_at: "2026-10-16T12:00:00Z", recipe: { subject, rig: { movement } } });
const reshoot = (id, prompt) => ({ id, kind: "reshoot", created_at: "2026-10-16T12:00:00Z", recipe: { prompt } });
const lines = (caption) => caption.split("\n");

test("the hashtag is present and last", () => {
  const caption = captionFor({ takes: [direct("tk_1", "mara on the pier", "orbit_90")], url: "https://openfield.example/#/takes/tk_1", moves: MOVES });
  assert.ok(caption.includes("#OpenSourceHiggsfield"));
  assert.equal(lines(caption).at(-1), "#OpenSourceHiggsfield");
  assert.equal(lines(caption).at(-2), "https://openfield.example/#/takes/tk_1");
});

test("a direct take names its move and is built with Qwen", () => {
  const caption = captionFor({ takes: [direct("tk_1", "mara on the pier", "orbit_90")], moves: MOVES });
  assert.match(caption, /^Mara on the pier: Orbit 90$/m);
  assert.match(caption, /^Built with Qwen$/m);
});

test("a reshoot-only set never claims Qwen and keeps the motion line", () => {
  const caption = captionFor({ takes: [reshoot("tk_2", "a knight on a beach")] });
  assert.ok(caption.includes("same motion, new character"));
  assert.ok(!caption.includes("Built with Qwen"));
  assert.equal(lines(caption).at(-1), "#OpenSourceHiggsfield");
});

test("a shots board and an edit claim Qwen too: Qwen-Image made those", () => {
  const url = "https://openfield.example/#/takes/tk_3";
  const takes = [
    { id: "tk_3", kind: "shots", created_at: "2026-10-16T12:00:00Z", label: "nine setups of one still" },
    { id: "tk_4", kind: "edit", created_at: "2026-10-16T12:00:00Z", label: "a red raincoat" },
  ];
  for (const take of takes) {
    const caption = captionFor({ takes: [take], url });
    assert.match(caption, /^Built with Qwen$/m);
    assert.equal(lines(caption).at(-2), url);
    assert.equal(lines(caption).at(-1), "#OpenSourceHiggsfield");
  }
});

test("the url appears when given", () => {
  const url = "https://openfield.example/#/takes/tk_2";
  const caption = captionFor({ takes: [reshoot("tk_2", "a knight on a beach")], url });
  assert.ok(lines(caption).includes(url));
});

test("eight takes with long titles and all twelve moves still fit in 280 characters", () => {
  const moves = { moves: Array.from({ length: 12 }, (_, i) => ({ id: `move_${i}`, label: `A very long camera move name number ${i + 1}` })) };
  const takes = Array.from({ length: 8 }, (_, i) => direct(`tk_${i}`, `A deliberately long take title that goes on and on about scene ${i + 1}`, `move_${i}`));
  const caption = captionFor({ takes, moves, url: "https://openfield.example/#/takes/tk_0" });
  assert.ok(caption.length <= 280, `caption was ${caption.length} characters`);
  assert.equal(lines(caption).at(-1), "#OpenSourceHiggsfield");
});

test("several takes count and dedupe their moves in take order", () => {
  const caption = captionFor({
    takes: [direct("tk_1", "one", "orbit_90"), direct("tk_2", "two", "push_in"), direct("tk_3", "three", "orbit_90")],
    moves: MOVES,
  });
  assert.match(caption, /^3 takes: Orbit 90, Push In$/m);
});
