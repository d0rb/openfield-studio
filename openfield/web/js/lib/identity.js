// The Identity Ring's values: how a face-check report becomes something to draw.
// A report is { status: "pass" | "drift" | "n/a" | "unavailable", score, threshold, retried?, refs_used }.

const SCALE_MAX = 1; // cosine similarity runs to 1; the ring maps 0..1 onto its sweep

export function ringState(report) {
  if (!report) return { status: "none", label: "No face check", fraction: 0, tick: null, score: null };
  const threshold = report.threshold ?? 0.363;
  const tick = Math.min(1, threshold / SCALE_MAX);
  const base = { threshold, tick, score: report.score ?? null, retried: Boolean(report.retried) };
  switch (report.status) {
    case "pass":
      return { ...base, status: "pass", label: "Same person", fraction: clamp(report.score) };
    case "drift":
      return { ...base, status: "drift", label: "Drifted from the reference", fraction: clamp(report.score) };
    case "n/a":
      return { ...base, status: "na", label: "No real face to compare", fraction: 0, score: null };
    default:
      return { ...base, status: "unavailable", label: "Face check unavailable", fraction: 0, score: null };
  }
}

const clamp = (value) => Math.max(0, Math.min(1, (value ?? 0) / SCALE_MAX));

/** The worst result across a take's stages: drift beats pass beats n/a; used for the take-level badge. */
export function overall(identity) {
  const reports = Object.values(identity ?? {});
  if (!reports.length) return ringState(null);
  const worst = reports.find((r) => r.status === "drift") ?? reports.find((r) => r.status === "pass") ?? reports[0];
  return ringState(worst);
}

/** Stages in the order they happened, for the per-stage list under the ring. */
export function perStage(identity) {
  return Object.entries(identity ?? {}).map(([stage, report]) => ({ stage, ...ringState(report) }));
}

/** Format a score for display: two decimals, or an em dash when there is none. */
export const formatScore = (score) => (score == null ? "—" : score.toFixed(2));
