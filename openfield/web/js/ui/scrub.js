// The mouse drives the camera: over a playing loop, left to right across the frame is the take from its first frame to
// its last, so a camera move runs as fast as the hand moves. Leaving hands the frame back to its loop. Touch, the
// keyboard and reduced motion keep the plain loop, and lose nothing.

import { scrubTime } from "../lib/deck.js";
import { holdStill } from "../lib/motion.js";

/** Let the mouse scrub `video` across `box`. `onScrub(f)` hears where the scrub is (0..1), or null when it ends. */
export function scrubbable(box, video, { onScrub } = {}) {
  let on = false;
  let want = null;
  let frame = 0;
  const apply = () => {
    frame = 0;
    if (want === null || !(video.duration > 0)) return;
    try { video.currentTime = want; } catch { /* not seekable yet */ }
  };
  box.addEventListener("pointermove", (e) => {
    if (e.pointerType !== "mouse" || holdStill() || !(video.duration > 0)) return;
    const r = box.getBoundingClientRect();
    want = scrubTime(e.clientX - r.left, r.width, video.duration);
    if (!on) {
      on = true;
      video.pause();
      box.classList.add("scrubbing");
    }
    const f = want / video.duration;
    box.style.setProperty("--scrub", f.toFixed(4));
    onScrub?.(f);
    frame ||= requestAnimationFrame(apply);
  });
  box.addEventListener("pointerleave", () => {
    if (!on) return;
    on = false;
    want = null;
    box.classList.remove("scrubbing");
    if (video.isConnected && video.getAttribute("src") && !holdStill()) video.play().catch(() => {});
    onScrub?.(null);
  });
}
