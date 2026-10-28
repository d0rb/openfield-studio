// The "Make your own" sheet: the three ways to start a studio of your own, with the commands to run.
//
// The hosted copy renders nothing, so this sheet is what a visitor there can act on: the commands to install
// the studio, what a render costs, and the repository to read when the site names one.

import { COST, installSteps } from "../lib/install.js";
import { copyText, fill, h, icon } from "./dom.js";
import { notify } from "./actions.js";
import { openSheet } from "./sheet.js";

/** One way in: its title, what it means, and the commands with a copy button. */
function step(ctx, { title, text, code }) {
  const pre = h("pre", { class: "code", tabindex: "0" }, code);
  const copy = h("button", { type: "button", class: "btn ghost sm" }, "Copy");
  copy.addEventListener("click", async () => notify(ctx, (await copyText(code)) ? "Copied." : "Could not copy.", "", "info"));
  return h("div", { class: "make-step" },
    h("b", null, title),
    h("p", { class: "hint" }, text),
    h("div", { class: "guide-code" }, pre, copy));
}

/** The sheet: the three ways in, the measured cost, and the repository when the site names one. */
export function openMakeSheet(ctx) {
  const body = h("div", { class: "stack make-body" });
  const paint = (repoUrl) => fill(body,
    ...installSteps(repoUrl).map((s) => step(ctx, s)),
    h("p", { class: "hint" }, COST),
    repoUrl ? h("a", { class: "btn secondary sm", href: repoUrl, target: "_blank", rel: "noopener noreferrer" },
      icon("link"), "Open the repository") : null);
  paint(null); // the placeholder address first; the site's own address follows when it answers
  openSheet({ title: "Make your own", body, className: "sheet-make" });
  Promise.resolve(ctx.api.site?.()).then((site) => paint(site?.repo_url ?? null)).catch(() => {});
}
