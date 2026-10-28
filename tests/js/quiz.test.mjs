import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { buildQuiz, mulberry32, scoreLine, shareText, xIntent } from "../../openfield/web/js/lib/quiz.js";

const catalog = JSON.parse(readFileSync(new URL("./fixtures/catalog.json", import.meta.url), "utf8"));
const moves = catalog.moves;
const validated = moves.filter((m) => m.validated);

function previewsFor(list) {
  const takes = {};
  const map = {};
  for (const m of list) {
    const takeId = `tk_${m.id}`;
    takes[takeId] = { video: `showcase/${m.id}.mp4`, poster: `showcase/${m.id}.webp` };
    map[m.id] = takeId;
  }
  return { takes, moves: map };
}

const all = previewsFor(validated);

test("mulberry32 replays the same numbers from one seed", () => {
  const a = mulberry32(42);
  const b = mulberry32(42);
  assert.deepEqual([a(), a(), a()], [b(), b(), b()]);
  assert.notEqual(mulberry32(1)(), mulberry32(2)());
});

test("a seed builds the same quiz twice", () => {
  assert.deepEqual(buildQuiz({ moves, previews: all, seed: 7 }), buildQuiz({ moves, previews: all, seed: 7 }));
});

test("every round offers four distinct moves, one of them the answer", () => {
  const quiz = buildQuiz({ moves, previews: all, seed: 7 });
  assert.equal(quiz.length, 10, "the default quiz is ten rounds");
  for (const q of quiz) {
    assert.equal(q.choices.length, 4);
    assert.equal(new Set(q.choices).size, 4);
    assert.ok(q.choices.includes(q.answer), q.answer);
    assert.equal(all.moves[q.answer], q.takeId);
    assert.ok(all.takes[q.takeId]);
  }
});

test("answers are only validated moves whose take has a preview", () => {
  const bad = moves.filter((m) => !m.validated).map((m) => m.id);
  const quiz = buildQuiz({ moves, previews: all, seed: 11, rounds: 99 });
  assert.equal(quiz.length, validated.length, "as many rounds as qualify");
  for (const q of quiz) {
    const answer = moves.find((m) => m.id === q.answer);
    assert.ok(answer.validated, `${q.answer} is not validated`);
    assert.ok(!bad.includes(q.answer));
    assert.ok(all.moves[q.answer] && all.takes[all.moves[q.answer]]);
  }
});

test("a quiz never asks the same answer twice", () => {
  const quiz = buildQuiz({ moves, previews: all, seed: 3, rounds: 10 });
  assert.equal(new Set(quiz.map((q) => q.answer)).size, 10);
  assert.equal(new Set(quiz.map((q) => q.takeId)).size, 10);
});

test("when fewer moves qualify, the quiz uses them all", () => {
  const few = validated.slice(0, 3);
  const quiz = buildQuiz({ moves, previews: previewsFor(few), seed: 5, rounds: 10 });
  assert.deepEqual(quiz.map((q) => q.answer).sort(), few.map((m) => m.id).sort());
});

test("distractors come from the answer's own group first", () => {
  const mk = (id, group) => ({ id, label: `Move ${id}`, group, group_label: group, validated: true });
  const a = ["a1", "a2", "a3", "a4", "a5"].map((id) => mk(id, "g1"));
  const b = ["b1", "b2", "b3"].map((id) => mk(id, "g2"));
  const list = [...a, ...b];
  const quiz = buildQuiz({ moves: list, previews: previewsFor(list), seed: 9, rounds: 8 });
  for (const q of quiz) {
    const same = list.filter((m) => m.group === "g1").map((m) => m.id);
    const fromG1 = q.choices.filter((id) => same.includes(id));
    if (same.includes(q.answer)) assert.equal(fromG1.length, 4, "three same-group distractors");
    else assert.equal(fromG1.length, 1, "two same-group distractors, then one from elsewhere");
    for (const id of q.choices.filter((c) => c !== q.answer)) assert.notEqual(list.find((m) => m.id === id).label, list.find((m) => m.id === q.answer).label);
  }
});

test("the score, the share line and the X intent", () => {
  assert.equal(scoreLine(8, 10), "8/10");
  assert.equal(shareText(8, 10), "I named 8/10 camera moves in the OpenField Studio quiz. Your turn. #OpenSourceHiggsfield");
  const text = "I named 8/10 & more? #OpenSourceHiggsfield";
  const url = "https://example.com/a b";
  const href = xIntent(text, url);
  assert.equal(href, `https://x.com/intent/post?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`);
  const parsed = new URL(href);
  assert.equal(parsed.origin + parsed.pathname, "https://x.com/intent/post");
  assert.equal(parsed.searchParams.get("text"), text);
  assert.equal(parsed.searchParams.get("url"), url);
  assert.ok(!href.includes(" "));
});

test("a round never offers a move beside its twin: the same motion under another name", async () => {
  const { buildQuiz, sameMotion } = await import("../../openfield/web/js/lib/quiz.js");
  assert.ok(sameMotion("track_right", "truck_right") && sameMotion("push_in", "dolly_in") && !sameMotion("track_left", "track_right"));
  const ids = ["track_left", "track_right", "truck_left", "truck_right", "dolly_in", "push_in", "dolly_out", "pull_out", "static", "crane_up", "pedestal_up", "orbit_90"];
  const moves = ids.map((id, i) => ({ id, label: id, group: i < 4 ? "track" : "dolly", validated: true }));
  const previews = { takes: Object.fromEntries(ids.map((id) => [`tk_${id}`, { video: "v", poster: "p" }])), moves: Object.fromEntries(ids.map((id) => [id, `tk_${id}`])) };
  for (let seed = 1; seed < 40; seed += 1) {
    for (const round of buildQuiz({ moves, previews, seed, rounds: 12 })) {
      assert.ok(round.choices.filter((c) => c !== round.answer).every((c) => !sameMotion(c, round.answer)), `seed ${seed}: ${round.answer} vs ${round.choices}`);
    }
  }
});

test("today's five: one day for the whole world, the same five clips for everyone that day", async () => {
  const { quizDay, dayLabel, dailyQuiz } = await import("../../openfield/web/js/lib/quiz.js");
  assert.equal(quizDay(Date.UTC(2026, 9, 1, 0, 0)), 1);
  assert.equal(quizDay(Date.UTC(2026, 9, 26, 23, 59)), 26);
  assert.equal(quizDay(Date.UTC(2026, 9, 27, 0, 0)), 27, "the day turns at midnight UTC");
  assert.equal(dayLabel(26), "Oct 26");
  assert.equal(dayLabel(32), "Nov 1");
  const a = dailyQuiz({ moves, previews: all, day: 26 });
  assert.equal(a.length, 5);
  assert.deepEqual(dailyQuiz({ moves, previews: all, day: 26 }), a, "everyone gets the same five");
  assert.notDeepEqual(dailyQuiz({ moves, previews: all, day: 27 }).map((r) => r.answer), a.map((r) => r.answer), "tomorrow is another five");
});

test("the day's line and the streak", async () => {
  const { squares, dailyShareText, nextRecord } = await import("../../openfield/web/js/lib/quiz.js");
  const results = [true, true, false, true, true].map((right, i) => ({ label: `Move ${i}`, right }));
  assert.equal(squares(results), "■■□■■");
  assert.equal(dailyShareText(26, results), "Name the move, Oct 26: 4/5 ■■□■■. The same five clips for everyone today. #OpenSourceHiggsfield");
  const first = nextRecord(null, 26, results);
  assert.deepEqual([first.day, first.correct, first.total, first.streak, first.best], [26, 4, 5, 1, 1]);
  assert.equal(nextRecord(first, 26, []), first, "a day counts once");
  const second = nextRecord(first, 27, results);
  assert.deepEqual([second.streak, second.best], [2, 2]);
  const gap = nextRecord(second, 30, results);
  assert.deepEqual([gap.streak, gap.best], [1, 2], "a missed day starts the streak again; the best stays");
  assert.equal(nextRecord(gap, 27, results), gap, "a five dealt on an earlier day and finished after a newer day was stored leaves the newer record");
  assert.deepEqual(gap.results[2], { label: "Move 2", right: false });
});

test("a stored day is trusted only when it holds the whole result", async () => {
  const { validDay } = await import("../../openfield/web/js/lib/quiz.js");
  const good = { day: 26, correct: 4, total: 5, results: [], streak: 1, best: 1 };
  assert.equal(validDay(good), good);
  for (const bad of [null, 0, "x", { day: 26 }, { day: "26", correct: 4, total: 5, results: [] }, { day: 26, correct: 4, total: 5, results: "x" }, { day: 26.5, correct: 4, total: 5, results: [] }]) {
    assert.equal(validDay(bad), null, JSON.stringify(bad));
  }
});

test("the quiz's day turns at midnight UTC, to the millisecond", async () => {
  const { quizDay } = await import("../../openfield/web/js/lib/quiz.js");
  assert.equal(quizDay(Date.UTC(2026, 9, 26, 23, 59, 59, 999)), 26, "the last millisecond of the 26th");
  assert.equal(quizDay(Date.UTC(2026, 9, 27)), 27, "the first of the 27th");
  assert.equal(quizDay(Date.UTC(2026, 9, 1)), 1, "October 1 is day 1");
  assert.equal(quizDay(Date.UTC(2026, 8, 30, 23, 59, 59, 999)), 0, "the day before counts down, not up to day 1 again");
});

test("a five dealt before midnight and finished after it counts for the day it was dealt, and the streak holds", async () => {
  const { quizDay, nextRecord } = await import("../../openfield/web/js/lib/quiz.js");
  const results = [true, false, true, true, false].map((right, i) => ({ label: `Move ${i}`, right }));
  // ui/quiz.js takes `day` once, in start(), and records that day when the last round is answered
  const dealt = quizDay(Date.UTC(2026, 9, 26, 23, 59, 30));
  const finished = quizDay(Date.UTC(2026, 9, 27, 0, 1));
  assert.deepEqual([dealt, finished], [26, 27], "the clock has turned over by the last answer");
  const yesterday = nextRecord(null, 25, results);
  const record = nextRecord(yesterday, dealt, results);
  assert.deepEqual([record.day, record.streak], [26, 2], "the result goes to the day the clips were dealt, so the streak goes on");
  const tomorrow = nextRecord(record, finished, results);
  assert.deepEqual([tomorrow.day, tomorrow.streak, tomorrow.best], [27, 3, 3], "and the next day's five, a minute later, takes it on again");
  assert.equal(nextRecord(record, dealt, []), record, "the same day is never counted twice, even if its five are finished again");
});
