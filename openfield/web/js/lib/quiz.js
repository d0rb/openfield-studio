// "Name the move": seeded quiz over moves with checked preview loops. Pure logic.

export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), a | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const draw = (list, rng) => {
  const out = [...list];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
};

/** Moves a short clip cannot tell apart: the same motion under two names. A round never offers one beside its twin. */
export const SAME_MOTION = [
  ["dolly_in", "push_in", "super_dolly_in"], ["dolly_out", "pull_out"], ["track_left", "truck_left"], ["track_right", "truck_right"],
  ["crane_up", "pedestal_up"], ["crane_down", "pedestal_down"], ["crash_zoom_in", "eyes_in"],
];
export const sameMotion = (a, b) => a === b || SAME_MOTION.some((set) => set.includes(a) && set.includes(b));

export function buildQuiz({ moves = [], previews, seed = 0, rounds = 10 } = {}) {
  const takes = previews?.takes ?? {}, loops = previews?.moves ?? {}, rng = mulberry32(seed);
  const answers = moves.filter((m) => m.validated && loops[m.id] && takes[loops[m.id]]); // the question is the loop
  return draw(answers, rng).slice(0, rounds).map((answer) => {
    const usable = (m) => m.validated && !sameMotion(m.id, answer.id) && m.label !== answer.label;
    const same = draw(moves.filter((m) => usable(m) && m.group === answer.group), rng); // the own group first
    const rest = draw(moves.filter((m) => usable(m) && m.group !== answer.group), rng);
    return { takeId: loops[answer.id], answer: answer.id, choices: draw([answer.id, ...same.concat(rest).slice(0, 3).map((m) => m.id)], rng) };
  });
}

export const scoreLine = (correct, total) => `${correct}/${total}`;

export const shareText = (correct, total) => `I named ${scoreLine(correct, total)} camera moves in the OpenField Studio quiz. Your turn. #ComfyUI`;

export const xIntent = (text, url) => `https://x.com/intent/post?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`;

// -- today's five: the same five rounds for everyone on a day, a streak kept in the browser ---------------------------

const DAY_ZERO = Date.UTC(2026, 9, 1); // October 1, 2026 is day 1
const DAY_MS = 86_400_000;

/** The quiz's day for a moment, counted in UTC so the whole world shares a day's five. */
export const quizDay = (time = Date.now()) => Math.floor((time - DAY_ZERO) / DAY_MS) + 1;

/** "Oct 26": the date a quiz day falls on. */
export const dayLabel = (day) => new Date(DAY_ZERO + (day - 1) * DAY_MS).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

/** Today's five: the same five rounds for everyone on `day`. */
export const dailyQuiz = ({ moves = [], previews, day }) => buildQuiz({ moves, previews, seed: 0x5eed0000 + day * 7919, rounds: 5 });

/** One square per round: filled for a move named, hollow for one missed. */
export const squares = (results) => results.map((r) => (r.right ? "■" : "□")).join("");

/** The day's line to post. */
export const dailyShareText = (day, results) =>
  `Name the move, ${dayLabel(day)}: ${scoreLine(results.filter((r) => r.right).length, results.length)} ${squares(results)}. The same five clips for everyone today. #ComfyUI`;

/** The record after a finished day: the streak grows when the day before was played too, else it starts again at one. A day
 * counts once. `day` is the day the five were dealt (ui/quiz.js keeps it from start()): finished after midnight, it still counts for that day. */
export function nextRecord(record, day, results) {
  const before = record && Number.isFinite(record.day) ? record : null;
  if (before && before.day >= day) return before; // a day counts once, and a newer day stored meanwhile (another tab) stands
  const streak = before?.day === day - 1 ? (before.streak ?? 0) + 1 : 1;
  return {
    day, correct: results.filter((r) => r.right).length, total: results.length, results: results.map((r) => ({ label: r.label, right: Boolean(r.right) })),
    streak, best: Math.max(streak, before?.best ?? 0),
  };
}

/** A stored day, trusted only when it holds everything its result shows; anything else (an old shape, garbage) is null. */
export const validDay = (record) =>
  (record && [record.day, record.correct, record.total].every(Number.isInteger) && Array.isArray(record.results) ? record : null);
