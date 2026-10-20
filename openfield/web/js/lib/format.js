// Small formatting helpers shared by the views.

/** 00:03:12 style timecode at the given frame rate (frames after the last colon). */
export function timecode(seconds, fps = 24) {
  seconds = Math.max(0, Number.isFinite(seconds) ? seconds : 0);
  const whole = Math.floor(seconds);
  const frames = Math.min(fps - 1, Math.floor((seconds - whole) * fps));
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const s = whole % 60;
  const two = (n) => String(n).padStart(2, "0");
  return `${two(h)}:${two(m)}:${two(s)}:${two(frames)}`;
}

/** "3 min ago", "just now". */
export function ago(iso, now = Date.now()) {
  const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (seconds < 20) return "just now";
  if (seconds < 90) return `${seconds} s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return hours < 36 ? `${hours} h ago` : `${Math.round(hours / 24)} d ago`;
}

/** A take id shortened to something hash-like: tk_20261016_153012_ab12 -> 0f3a... style tail. */
export function shortId(id) {
  const m = /^tk_(\d{8})_(\d{6})_([0-9a-f]{4})$/.exec(id ?? "");
  return m ? `${m[3]}` : String(id ?? "").slice(-4);
}

/** Order-insensitive deep equality for plain JSON values (used to tell if a recipe was edited). */
export function sameRecipe(a, b) {
  if (Object.is(a, b)) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const ka = Object.keys(a);
  const kb = Object.keys(b);
  if (ka.length !== kb.length) return false;
  return ka.every((k) => Object.hasOwn(b, k) && sameRecipe(a[k], b[k]));
}

/** What changed between two flat-ish parameter objects, as {path, from, to} rows. */
export function diffParams(before, after, prefix = "") {
  const rows = [];
  for (const key of new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])) {
    const path = prefix ? `${prefix}.${key}` : key;
    const x = before?.[key];
    const y = after?.[key];
    if (x && y && typeof x === "object" && typeof y === "object" && !Array.isArray(x)) {
      rows.push(...diffParams(x, y, path));
    } else if (!sameRecipe(x, y)) {
      rows.push({ path, from: x, to: y });
    }
  }
  return rows;
}
