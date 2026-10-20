// Drives the real interface in a real browser. Usage:
//   node tests/ui/smoke.mjs live   http://127.0.0.1:PORT/   (the app on the offline fake of the Comfy API)
//   node tests/ui/smoke.mjs static http://127.0.0.1:PORT/   (the hosted Replay: plain files, no server)
// Exits 1 if any check fails. tests/test_ui_smoke.py starts the servers and calls this.

import { launch } from "../../scripts/ui/browser.mjs";

const [mode, url] = process.argv.slice(2);
if (!["live", "static"].includes(mode) || !url) {
  console.error("usage: node tests/ui/smoke.mjs <live|static> <url>");
  process.exit(2);
}

let failures = 0;
const check = (name, ok, detail = "") => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
  if (!ok) failures += 1;
};

/** What a keyboard or screen-reader user needs: names, unique ids, targets big enough to hit. */
const AUDIT = `(() => {
  const problems = [];
  const shown = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && !el.closest("[hidden]"); };
  const labelled = (el) => (el.getAttribute("aria-labelledby") ?? "").split(" ").map((id) => document.getElementById(id)?.textContent ?? "").join(" ").trim();
  const name = (el) => el.getAttribute("aria-label") || labelled(el) || (el.labels?.length ? [...el.labels].map((l) => l.textContent).join(" ") : "") || el.getAttribute("title") || el.textContent.trim() || el.querySelector("img[alt]")?.alt || "";
  for (const el of document.querySelectorAll("button, a[href], input:not([type=hidden]), select, textarea, [role=radio], [role=switch], [role=tab]")) {
    if (el.type !== "file" && !shown(el)) continue;
    if (!name(el)) problems.push("no accessible name: " + el.outerHTML.slice(0, 80));
  }
  const ids = new Map();
  for (const el of document.querySelectorAll("[id]")) ids.set(el.id, (ids.get(el.id) ?? 0) + 1);
  for (const [id, n] of ids) if (n > 1) problems.push("duplicate id: " + id);
  for (const el of document.querySelectorAll("button, a[href], [role=radio], [role=switch], [role=tab], select")) {
    if (!shown(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 24 || r.height < 24) problems.push("target under 24px: " + el.outerHTML.slice(0, 70) + " " + Math.round(r.width) + "x" + Math.round(r.height));
  }
  for (const img of document.querySelectorAll("img")) if (!img.hasAttribute("alt")) problems.push("image without alt");
  return problems;
})()`;

const b = await launch({ width: 1440, height: 900 });
const ev = (js) => b.eval(js);
const route = async (name) => { await ev(`location.hash = "#/${name}"`); await b.waitFor(`window.openfield.store.get().route === "${name}"`); await b.sleep(250); };

try {
  await b.goto(url);
  await b.waitFor("window.openfield?.store.get().loaded", { label: "the app loads" });
  await b.sleep(400);

  // -- the shell ----------------------------------------------------------------------------------
  check("the page has a title", /OpenField Studio/.test(await ev("document.title")));
  check("four stations in the rail", (await ev("document.querySelectorAll('.rail-item').length")) === 4);
  check("it runs on the " + mode + " api", (await ev("window.openfield.api.kind")) === (mode === "static" ? "static" : "http"));

  if (mode === "live") {
    // -- the Move Pad ---------------------------------------------------------------------------------
    await ev("document.querySelector('.move-tile[aria-checked=true]').focus()");
    await b.key("ArrowRight");
    check("arrow keys move along the Move Pad", (await ev("window.openfield.forms.get().direct.rig.movement")) === "dolly_out");
    await ev("[...document.querySelectorAll('.move-tile')].find((t) => t.textContent.includes('Orbit 180')).click()");
    await b.sleep(150);
    check("the plan line counts the renders for the move", /3 stills, 2 shots/.test(await ev("document.querySelector('.plan').innerText")), await ev("document.querySelector('.plan').innerText"));
    await ev("[...document.querySelectorAll('.move-tile')].find((t) => t.textContent.includes('Dolly in')).click()");

    // -- validation ------------------------------------------------------------------------------------
    await ev("document.querySelectorAll('.section-head').forEach((h) => h.getAttribute('aria-expanded') === 'false' && h.click())");
    await b.type("#seed", "-5");
    await b.sleep(200);
    check("a bad seed is explained and blocks Shoot", /whole number/.test(await ev("document.querySelector('#seed').closest('.field').innerText")) && (await ev("document.querySelector('.prompt .btn.primary').disabled")));
    await ev("const s = document.querySelector('#seed'); s.value = ''; s.dispatchEvent(new Event('input', { bubbles: true }))");

    // -- a whole Direct take: stills, approval, shot, receipt ---------------------------------------------
    check("Shoot waits for a subject", await ev("document.querySelector('.prompt .btn.primary').disabled"));
    await b.type("#subject", "A white lighthouse on a cliff at dusk, waves breaking below");
    await b.click(".prompt .btn.primary");
    await b.waitFor("document.querySelector('.screen[data-mode=approval]')", { timeout: 60000, label: "the stills wait for approval" });
    check("the stills stop for approval before any video", (await ev("document.querySelectorAll('.approve-row .still').length")) === 2);
    await b.click(".approve-actions .btn.primary");
    await b.waitFor("document.querySelector('.screen[data-mode=running]')", { label: "the render shows its progress" });
    check("a render shows its steps", (await ev("document.querySelectorAll('.steps li').length")) >= 4);
    await b.waitFor("document.querySelector('.screen[data-mode=ready] video.player')", { timeout: 90000, label: "the take is ready" });
    check("the finished take plays in the Monitor", /^blob:|\/media\/take\.mp4/.test(await ev("document.querySelector('video.player').src")));
    check("with a transport bar", /\d\d:\d\d:\d\d:\d\d/.test(await ev("document.querySelector('.transport').innerText")));
    await b.click(".monitor-head .btn:last-child");
    await b.waitFor("document.querySelector('.audit-head .pill')", { label: "the receipt loads" });
    check("its audit says open weights only", /Open weights only/.test(await ev("document.querySelector('.audit-head').innerText")));
    check("and its workflow can be downloaded for ComfyUI", await ev("[...document.querySelectorAll('.dock-actions a')].some((a) => /Download workflow/.test(a.textContent) && a.href.endsWith('workflows.zip'))"));

    // -- keyboard and the dock -------------------------------------------------------------------------------
    await b.key("[");
    check("[ hides the settings panel", (await ev("document.querySelector('.app').dataset.dock")) === "closed");
    await b.key("[");

    // -- the other stations ----------------------------------------------------------------------------------
    for (const name of ["takes", "cast", "reshoot"]) {
      await route(name);
      check(`the ${name} station opens`, await ev(`!document.querySelector('[data-station=${name}]').hidden`));
    }
    await route("takes");
    check("Takes lists the take with its receipt one click away", (await ev("document.querySelectorAll('.take-row').length")) >= 1);
  } else {
    // -- the hosted Replay ----------------------------------------------------------------------------------------
    await b.sleep(600);
    check("the first screen shows a recorded take", /Recorded take/.test(await ev("document.querySelector('.monitor-head').innerText")));
    check("with Recreate (replay) in the prompt bar", /Recreate \(replay\)/.test(await ev("document.querySelector('.prompt .btn.primary').innerText")));
    await b.click(".prompt .btn.primary");
    await b.waitFor("document.querySelector('.screen[data-mode=running]')", { label: "the recording plays back" });
    check("a replay says it is a recording", /Nothing is rendering now/.test(await ev("document.querySelector('.run-note').innerText")));
    await b.waitFor("window.openfield.store.get().takes.some((t) => t.replay && t.status === 'succeeded')", { timeout: 40000, label: "the replay finishes" });
    await b.waitFor("document.querySelector('.screen[data-mode=ready] video.player')", { label: "the replayed take plays" });
    check("the replayed take carries the Replay pill", /Replay/.test(await ev("document.querySelector('.monitor-head').innerText")));
    // anything that was not recorded cannot be shot
    await ev("window.openfield.forms.set((s) => ({ direct: { ...s.direct, subject: 'Something that was never recorded' } }))");
    await b.sleep(250);
    check("an edited recipe says Needs a backend", /Needs a backend/.test(await ev("document.querySelector('[data-station=direct] .prompt .btn.primary').innerText")));
    check("and the plan line explains why", /not recorded/.test(await ev("document.querySelector('[data-station=direct] .plan').innerText")));
    await ev("window.openfield.ui.openDock('take')");
    await b.waitFor("document.querySelector('.audit-head .pill')", { label: "a recorded receipt loads" });
    check("a recorded take shows its audit and licences", /Open weights only/.test(await ev("document.querySelector('.audit-head').innerText")));
  }

  // -- accessibility basics on every station ------------------------------------------------------------------------
  for (const name of ["direct", "reshoot", "cast", "takes"]) {
    await route(name);
    await ev("document.querySelectorAll('.section-head').forEach((h) => h.getAttribute('aria-expanded') === 'false' && h.click())");
    await b.sleep(150);
    const problems = await ev(AUDIT);
    check(`${name}: names, unique ids and target sizes`, problems.length === 0, problems.slice(0, 3).join("; "));
  }

  // -- a phone ---------------------------------------------------------------------------------------------------------
  await b.viewport(390, 844, true, 2);
  await b.goto(url);
  await b.waitFor("window.openfield?.store.get().loaded");
  await b.sleep(500);
  const width = await ev("({ inner: innerWidth, scroll: document.documentElement.scrollWidth })");
  check("a phone gets no sideways scroll", width.scroll <= width.inner, JSON.stringify(width));
  check("and a bottom station bar", (await ev("getComputedStyle(document.querySelector('.rail')).flexDirection")) === "row");

  // -- reduced motion -----------------------------------------------------------------------------------------------------
  await b.viewport(1440, 900, false, 1);
  await b.emulate([{ name: "prefers-reduced-motion", value: "reduce" }]);
  await b.goto(url);
  await b.waitFor("window.openfield?.store.get().loaded");
  check("reduced motion is honoured (no animation runs)", await ev("[...document.querySelectorAll('*')].every((e) => parseFloat(getComputedStyle(e).animationDuration) < 0.01)"));

  check("the page raised no script errors", b.log.errors.length === 0, b.log.errors.join(" | ").slice(0, 200));
  check("and no console errors", b.log.console.length === 0, b.log.console.join(" | ").slice(0, 200));
  const bad = b.log.bad.filter((u) => !u.includes("preview.jpg"));
  check("and no failed requests", bad.length === 0, bad.join(" | ").slice(0, 200));
} catch (error) {
  console.log(`FAIL  the run stopped: ${error.message}`);
  failures += 1;
} finally {
  await b.close();
}

console.log(failures ? `\n${failures} check(s) failed` : "\nall checks passed");
process.exit(failures ? 1 : 0);
