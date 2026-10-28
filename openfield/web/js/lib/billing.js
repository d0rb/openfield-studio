// The billing order every stub and receipt keeps: seed, steps, length, recipe, audit. A field the take did not record
// is left out, never guessed; steps only for takes whose stills were rendered, read from the quality tier they used.

/** [label, value, pass?] rows, in order, for a take and the catalog it was made with. */
export function billing(take, catalog) {
  const audit = take?.audit?.result ? take.audit.result === "pass" : null; // the open-weights audit the take recorded
  // steps only when this take's own stills were rendered: a take that began from a person's photo (a dub, a "start from
  // my image" shot) may have rendered none, and the take alone cannot say, so it shows none
  const tier = ["direct", "edit", "shots"].includes(take?.kind) && !take.recipe?.source_sha256
    ? catalog?.quality?.find((q) => q.id === (take.recipe?.quality ?? "standard")) : null;
  return [
    take?.recipe?.seed != null ? ["Seed", String(take.recipe.seed)] : null,
    tier?.steps ? ["Steps", String(tier.steps)] : null,
    take?.seconds ? ["Length", `${take.seconds.toFixed(1)} s`] : null,
    take?.recipe_hash ? ["Recipe", take.recipe_hash.slice(0, 8)] : null,
    audit != null ? ["Audit", audit ? "Open weights" : "Failed", audit] : null,
  ].filter(Boolean);
}

/** How many distinct finished takes a copy holds: the recorded ones and this backend's own, each counted once. */
export function takeCount(state) {
  const ids = new Set((state.recorded ?? []).filter((r) => r.kind !== "portrait").map((r) => r.id));
  for (const t of state.takes ?? []) if (t.status === "succeeded" && t.kind !== "portrait" && !t.replay_of && !t.replay) ids.add(t.id);
  return ids.size;
}

/** The rate a take's GPU time is priced at on screen: a rented RTX 5090 at about $0.71 an hour (docs/benchmarks.md).
    Boxes cost between $0.71 and $0.79 an hour over the sessions, so the price is said with its rate. */
export const GPU_RATE = 0.71;

/** GPU seconds as money at `rate` dollars an hour: "2.6¢" under a dollar, "$1.20" above; null without a time. */
export function gpuCost(seconds, rate = GPU_RATE) {
  if (!(seconds > 0)) return null;
  const cents = (seconds / 3600) * rate * 100;
  return cents < 100 ? `${cents.toFixed(1)}¢` : `$${(cents / 100).toFixed(2)}`;
}

/** The GPU time a receipt recorded (the backend's whole run, in seconds), or null when it recorded none. */
export const gpuSeconds = (receipt) => {
  const s = receipt?.backend?.timings?.total_s;
  return typeof s === "number" && s > 0 ? s : null;
};

/** The recorded takes' GPU time in all (`status.gpu`, summed from their receipts) as "5.6 GPU hours, about $3.97", or
 * null without a total. */
export function ledgerLine(gpu, rate = GPU_RATE) {
  const seconds = gpu?.seconds;
  if (!(seconds > 0)) return null;
  const minutes = Math.max(1, Math.round(seconds / 60));
  const time = seconds >= 3600 ? `${(seconds / 3600).toFixed(1)} GPU hours` : `${minutes} GPU minute${minutes === 1 ? "" : "s"}`;
  return `${time}, about ${gpuCost(seconds, rate)}`;
}
