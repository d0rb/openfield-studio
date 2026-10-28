// Which copy of a picture a frame gets. The previews are cut at three widths (384, 768 and the take's own up to 1280), and a
// frame drawn w CSS pixels wide gets the narrowest copy that fills its pixels on this screen, up to 2x, else the widest. A phone
// (under 720px) or a browser saving its data plays the 384px loop whatever its density and never asks for the 1280px poster.
// Pure: it asks the browser's globals and assumes none, so it runs in Node.

const PLAIN_WIDTH = 384;
const MID_WIDTH = 768;
const HD_WIDTH = 1280;

/** The screen's pixels per CSS pixel, 1 to 2: a 3x phone screen gains nothing from a third copy's bytes. */
export const density = () => Math.min(2, Math.max(1, Number(globalThis.devicePixelRatio) || 1));
/** A phone: narrower than 720px (the galleries' own line). */
export const phone = () => !globalThis.matchMedia?.("(min-width: 720px)")?.matches;
/** The browser asked for less data. */
export const savingData = () => Boolean(globalThis.navigator?.connection?.saveData);

/** A take's copies from its previews.json entry, narrowest first: [{ width, video, poster }]. The plain loop is 384 wide;
    `mid` and `hd` carry the width the builder recorded (the hd copy of a 896-wide take is 896 wide), else their nominal one. */
export function copies(entry) {
  if (!entry?.video) return [];
  const out = [{ width: PLAIN_WIDTH, video: entry.video, poster: entry.poster ?? null }];
  if (entry.mid?.video) out.push({ width: entry.mid.width ?? MID_WIDTH, video: entry.mid.video, poster: entry.mid.poster ?? null });
  if (entry.hd?.video) out.push({ width: entry.hd.width ?? HD_WIDTH, video: entry.hd.video, poster: entry.hd.poster ?? null });
  return out.sort((a, b) => a.width - b.width);
}

/** The copy for a frame `cssWidth` px wide on this screen; the plain one for no width, on a phone or when saving data. */
export function pick(entry, cssWidth = 0) {
  const all = copies(entry);
  if (!all.length) return null;
  if (!(cssWidth > 0) || phone() || savingData()) return all[0];
  const need = cssWidth * density();
  return all.find((c) => c.width >= need) ?? all[all.length - 1];
}

/** What a poster <img> needs to pick its own copy: `src` (the smallest), `srcset` with every copy's width and `sizes`;
    a phone or a data saver is offered the small copies only. `url` turns a previews path into an address. */
export function posterSet(entry, sizes, url = (path) => path) {
  const all = copies(entry).filter((c) => c.poster);
  if (!all.length) return null;
  const small = all.filter((c) => c.width <= MID_WIDTH);
  const offered = (phone() || savingData()) && small.length ? small : all;
  return { src: url(offered[0].poster), srcset: offered.map((c) => `${url(c.poster)} ${c.width}w`).join(", "), sizes };
}
