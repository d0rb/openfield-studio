// OpenField Studio: boot the app. The same page is the live studio (HTTP api) and the hosted Replay (static api).

import { pickApi } from "./lib/boot.js";
import { createStore } from "./lib/store.js";
import { createController, initialState } from "./controller.js";
import { initialReshoot } from "./lib/reshoot.js";
import { initialCharacter, initialCast } from "./lib/cast.js";
import { linkFromHash } from "./lib/remix.js";
import { mountShell, routeFromHash } from "./ui/shell.js";
import { remixFrom } from "./ui/actions.js";

async function main() {
  const api = await pickApi();
  const store = createStore({ ...initialState(), route: routeFromHash() });
  const controller = createController({ api, store });
  const forms = createStore({ direct: null, reshoot: initialReshoot(), character: initialCharacter(), castForm: initialCast() });
  const ui = Object.assign(createStore({ dockOpen: !matchMedia("(max-width: 1179px)").matches, dockTab: "settings" }), { go() {}, openDock() {}, shoot: null });
  const ctx = { root: document.body, api, store, forms, controller, ui };
  mountShell(ctx);
  // coming back to the tab is the moment it is most likely out of date
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { controller.refreshStatus(); controller.refreshTakes(); } });
  window.openfield = { api, store, forms, controller, ui }; // for tests and for poking around in the console
  await controller.load();
  const link = linkFromHash(location.hash);
  if (link) {
    history.replaceState(null, "", `#/${store.get().route}`);
    await remixFrom(ctx, link);
  }
}

main().catch((error) => {
  document.body.replaceChildren(Object.assign(document.createElement("pre"), { textContent: `OpenField could not start.\n\n${error.stack ?? error}`, style: "padding:24px;white-space:pre-wrap;color:#f2727b" }));
});
