// OpenField Studio: boot the app. The same page is the live studio (HTTP api) and the hosted Replay (static api).

import { pickApi } from "./lib/boot.js";
import { createStore } from "./lib/store.js";
import { createController, initialState } from "./controller.js";
import { initialReshoot } from "./lib/reshoot.js";
import { initialCharacter, initialCast } from "./lib/cast.js";
import { linkFromHash } from "./lib/remix.js";
import { ROUTES, mountShell, routeFromHash } from "./ui/shell.js";
import { parseHash } from "./lib/route.js";
import { remixFrom } from "./ui/actions.js";
import { holdStill, onMotionChange } from "./lib/motion.js";
import { slots } from "./ui/wall.js";
import { wireSounds } from "./ui/sound.js";

// reduced motion or data saver: the stylesheet holds every loop still under :root.hold-still, as the scripts already do
// (not "still": that is the approval stills' own class, and its rules would then match the whole page)
const markStill = () => document.documentElement.classList.toggle("hold-still", holdStill());
markStill();
onMotionChange(markStill);

// the modules loaded and run: from here main() reports its own failures, so the page's start-up watchdog stands down
window.openfieldBooting = true;

async function main() {
  const api = await pickApi();
  const store = createStore({ ...initialState(), route: routeFromHash() });
  const controller = createController({ api, store });
  const forms = createStore({ direct: null, reshoot: initialReshoot(), character: initialCharacter(), castForm: initialCast() });
  const ui = Object.assign(createStore({ dockOpen: !matchMedia("(max-width: 1179px)").matches, dockTab: "settings" }), { go() {}, openDock() {}, shoot: null });
  // where the take on the wall is (0..1) and which move it shows: the stage views follow it frame by frame, so it is its
  // own store (setting it never wakes the main store's subscribers)
  const playhead = createStore({ t: 0, take: null, movement: null });
  const ctx = { root: document.body, api, store, forms, controller, ui, playhead };
  mountShell(ctx);
  wireSounds(); // one delegated listener for the whole document: the studio's clicks, silent until the Lobby's Sound switch is on
  // coming back to the tab is the moment it is most likely out of date
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { controller.refreshStatus(); controller.refreshTakes(); } });
  window.openfield = { api, store, forms, controller, ui, slots }; // slots: what the loops are doing (ui/wall.js) // for tests and for poking around in the console
  await controller.load();
  const { route, id } = parseHash(location.hash, ROUTES);
  if (id && route === "lobby") ui.openMove?.(id); // a move's link opens the move's own page in the Lobby
  else if (id) ui.openTake(id); // a take link lands on the take, playing, with its receipt open
  const link = linkFromHash(location.hash);
  if (link) {
    history.replaceState(null, "", `#/${store.get().route}`);
    await remixFrom(ctx, link);
  }
}

main().catch((error) => {
  document.body.replaceChildren(Object.assign(document.createElement("pre"), { id: "boot-fail", textContent: `OpenField could not start. Reload the page. Details below.\n\n${error.stack ?? error}`, style: "padding:24px;white-space:pre-wrap;color:var(--red)" }));
});
