// One answer to "may anything move here?": the person's preference, and their data saver.
// Safe in Node: the browser's globals are asked for, never assumed.

/** The person asked for less motion: nothing animates on its own. */
export const reducedMotion = () => Boolean(globalThis.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches);

/** Nothing may play or loop on its own: reduced motion, or a browser that is saving its data. */
export const holdStill = () => reducedMotion() || Boolean(globalThis.navigator?.connection?.saveData);

/** Call `listener` when the motion preference changes while the page is open (returns nothing; safe in Node). */
export const onMotionChange = (listener) => globalThis.matchMedia?.("(prefers-reduced-motion: reduce)")?.addEventListener?.("change", listener);
