// The studio's sounds: a clapper on a room change, a tape tick on a rocker or toggle, a thunk on the one action, a bulb's
// ping on a right answer and a low tick on a wrong one. Opt-in: the Lobby's Sound switch turns them on together with the
// trailer's own sound, and the choice is remembered in this browser (openfield.sound). No audio files: five short cues from
// one oscillator or a breath of noise, never over -20 dBFS, none over 80 ms, none in a hidden tab, none twice within 60 ms,
// none on a held key. Nothing here touches the page or the audio system at import time.

const KEY = "openfield.sound";
const PEAK = 0.1; // -20 dBFS
const GAP = 60; // ms between two cues

/** name: [kind, frequency from, frequency to, seconds] */
export const CUES = {
  room: ["noise", 1800, 600, 0.06],
  tick: ["sine", 2400, 2400, 0.03],
  thunk: ["sine", 160, 70, 0.08],
  ping: ["triangle", 2637, 2637, 0.08],
  dull: ["square", 220, 180, 0.05],
};

let want = null; // the remembered choice, read once
let ctx = null; // one AudioContext, made at the first gesture after the switch is turned on
let last = -Infinity;
const listeners = new Set();

const stored = () => { try { return globalThis.localStorage?.getItem(KEY) === "on"; } catch { return false; } };

/** Whether the person turned the studio's sound on in this browser. */
export const soundOn = () => (want ??= stored());

/** Turn the studio's sound on or off and remember it (a private window forgets at its close). */
export function setSound(on) {
  want = Boolean(on);
  try { globalThis.localStorage?.setItem(KEY, want ? "on" : "off"); } catch { /* this visit only */ }
  if (want) wake();
  for (const fn of listeners) fn(want);
}

/** Call `fn(on)` when the switch changes; returns the function that stops the calls. */
export const onSoundChange = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };

function wake() {
  const AC = globalThis.AudioContext ?? globalThis.webkitAudioContext;
  if (!AC) return null;
  try {
    ctx ??= new AC();
    if (ctx.state === "suspended") ctx.resume?.()?.catch?.(() => {});
  } catch { return null; } // a browser that cannot start audio: the switch (the trailer's sound too) still works, the cues are silent
  return ctx;
}

/** Play one cue by name. False when sound is off, the tab is hidden, the key is held (`repeat`), another cue just played,
    or the browser has no audio. */
export function play(name, { repeat = false } = {}) {
  const cue = CUES[name];
  const now = globalThis.performance?.now?.() ?? Date.now();
  if (!cue || repeat || !soundOn() || globalThis.document?.hidden || now - last < GAP) return false;
  const ac = wake();
  if (!ac) return false;
  last = now;
  const [kind, f0, f1, s] = cue;
  const t = ac.currentTime;
  const gain = ac.createGain();
  gain.gain.setValueAtTime(0, t);
  gain.gain.linearRampToValueAtTime(PEAK, t + 0.004);
  gain.gain.exponentialRampToValueAtTime(0.001, t + s);
  gain.connect(ac.destination);
  let src;
  if (kind === "noise") {
    const buf = ac.createBuffer(1, Math.ceil(ac.sampleRate * s), ac.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < d.length; i += 1) d[i] = Math.random() * 2 - 1;
    src = ac.createBufferSource();
    src.buffer = buf;
    const band = ac.createBiquadFilter();
    band.type = "bandpass";
    band.Q.value = 0.8;
    band.frequency.setValueAtTime(f0, t);
    band.frequency.exponentialRampToValueAtTime(f1, t + s);
    src.connect(band).connect(gain);
  } else {
    src = ac.createOscillator();
    src.type = kind;
    src.frequency.setValueAtTime(f0, t);
    src.frequency.exponentialRampToValueAtTime(f1, t + s);
    src.connect(gain);
  }
  src.start(t);
  src.stop(t + s + 0.01);
  return true;
}

/** Wired once (main.js): rockers, switches, pressed toggles, tabs and gallery filters tick, the one primary action thunks,
    and the arrow keys inside a radio group tick once per press. It listens in the capture phase: a click's own cue comes
    before whatever the click starts (the room cue that follows within 60 ms is the one dropped, so Start directing is one
    thunk), and a control that repaints itself or stops the event is still heard. */
export function wireSounds(root = globalThis.document) {
  if (!root?.addEventListener) return;
  root.addEventListener("click", (e) => {
    const b = e.target?.closest?.("button, a, [role=radio], [role=switch]");
    if (!b || b.disabled) return;
    if (b.matches(".btn.primary")) play("thunk");
    else if (b.matches("[aria-pressed], [role=radio], [role=switch], [role=tab], .show-filter")) play("tick");
  }, true);
  root.addEventListener("keydown", (e) => {
    if (e.key?.startsWith("Arrow") && e.target?.closest?.("[role=radiogroup]")) play("tick", { repeat: e.repeat });
  }, true);
}
