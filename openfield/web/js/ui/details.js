// The Take tab of the dock: what a person can do with a take, and how it was made and whether to trust it:
// identity check, open-weights audit, receipt.

import { ago } from "../lib/format.js";
import { billing, gpuCost, gpuSeconds } from "../lib/billing.js";
import { checkSeal } from "../lib/canonical.js";
import { formatScore, perStage, ringState } from "../lib/identity.js";
import { fileOf, focusTake, stageStrip, stepName, stillThumb, thumbOf, titleOf } from "../lib/stages.js";
import { captionFor } from "../lib/share.js";
import { sharePageUrl, shareTargets } from "../lib/shareurls.js";
import { FILM_KINDS, cropFocus } from "../lib/takes.js";
import { copyText, h, icon } from "./dom.js";
import { pill, section, segmented } from "./controls.js";
import { animateStill, loadTake, notify } from "./actions.js";
import { openTransitionSheet } from "./transition.js";
import { canCompare, openCompareSheet } from "./compare.js";
import { canSaveWithPath, savePathButton } from "./overlay.js";
import { shotSheetButton } from "./shotsheet.js";
import { openDubSheet, openEditSheet, openExtendSheet, openUpscaleSheet } from "./edit.js";
import { upscalable } from "../lib/edit.js";
import { openSheet } from "./sheet.js";

const TONE = { pass: "green", drift: "amber" };
// the Take tab shows what its station's monitor plays
const KINDS = { direct: ["direct", "transition", "extend", "upscale"], reshoot: ["reshoot"], takes: [...FILM_KINDS] };
const cropFocusByTake = new Map(); // the 9:16 crop focus chosen per take, kept across pane rebuilds

/** The identity reading: the score as a figure over a hairline scale with the pass line (0.363) as a tick. A gate-board readout, not a gauge. */
export function identityReading(report) {
  const state = ringState(report);
  const score = state.score == null ? (state.status === "na" ? "n/a" : "\u2013") : formatScore(state.score);
  const scale = h("span", { class: "id-scale", "aria-hidden": "true" },
    state.fraction > 0 ? h("span", { class: "id-fill", style: { width: `${Math.round(Math.min(1, state.fraction) * 100)}%` } }) : null,
    state.tick != null ? h("span", { class: "id-tick", style: { left: `${Math.round(state.tick * 100)}%` } }) : null);
  return h("div", { class: "id-reading", "data-status": state.status, role: "img", "aria-label": `${state.label}${state.score != null ? `, score ${formatScore(state.score)}` : ""}` },
    h("span", { class: "id-score num" }, score), scale);
}

const kv = (rows) => h("dl", { class: "kv" }, rows.filter(Boolean).flatMap(([k, v]) => [h("dt", null, k), h("dd", null, v)]));
const short = (s, n = 14) => (s && s.length > n ? `${s.slice(0, n)}…` : s);

/** "LTX-2.x Community License (4), Qwen Research License (3)", the counts as figures */
function licenceSummary(models) {
  const counts = new Map();
  for (const m of models) counts.set(m.license ?? "licence unknown", (counts.get(m.license ?? "licence unknown") ?? 0) + 1);
  return [...counts].flatMap(([name, n], i) => [i ? ", " : "", name, " ", h("span", { class: "num" }, `(${n})`)]);
}

/** A take note as a reader should see it: the notes written before round 11 said which parts were untested then. */
const plainNote = (note) => (/^experimental move:/i.test(note) ? null : note.replace(/\s*\([^)]*not yet tested[^)]*\)/i, ""));

export function createDetails(ctx) {
  const { api, store, controller, ui } = ctx;
  // the Take pane is the studio's one printed surface: card stock, dark ink, torn off at the foot (css/lobby.css)
  const el = h("div", { class: "dock-pane on-stock", "data-pane": "take", hidden: true });
  const receipts = new Map();
  let shownKey = null;
  let armed = null; // a take whose delete button was pressed once

  async function receiptOf(take) {
    if (!receipts.has(take.id)) receipts.set(take.id, api.receipt(take).catch(() => null));
    return receipts.get(take.id);
  }

  /** The verdict: the three things a reader wants to know, one hairline row each, before any detail. */
  function verdict(take, view) {
    const audit = view?.receipt?.audit ?? take.audit;
    const pass = audit?.result === "pass";
    const auditRow = h("div", { class: "verdict-row audit-head" },
      audit ? pill(pass ? "Open weights only" : "Audit failed", pass ? "green" : "red", { dot: true, size: "lg" }) : pill(take.replay ? "Audit recorded" : "Audit pending", null, { size: "lg" }),
      h("p", { class: "hint" }, audit ? (pass ? "Every model file open weights, checked before the render." : `Not allowed: ${(audit.disallowed ?? []).join(", ") || "see the receipt"}.`) : take.replay ? "The audit was recorded with the original take." : "Audit runs before the render."));
    const reports = Object.values(take.identity ?? {});
    const worst = reports.find((r) => r.status === "drift") ?? reports[0];
    const total = ringState(worst);
    const idRow = h("div", { class: "verdict-row identity-top" }, identityReading(worst),
      h("div", null, h("strong", null, total.label), h("p", { class: "hint" }, reports.length ? `Passes at ${total.threshold ?? 0.363} or higher.` : "No face check ran. Shots with no face show n/a.")));
    const digest = view?.receipt?.integrity?.digest ?? view?.receipt?.integrity?.sha256 ?? null;
    const receiptFile = take.outputs?.some((o) => o.role === "receipt") ? api.media(take, "receipt.json") : null;
    const sealHint = h("p", { class: "hint seal-hint", "aria-live": "polite" }, "Unchanged since it was written.");
    const checkHere = h("button", { type: "button", class: "link-btn seal-check" }, "Check it in this browser");
    const sealRow = h("div", { class: "verdict-row" },
      h("div", { class: "seal-line" },
        view ? (view.verified === true ? pill("Checksum matches", "green", { dot: true, size: "lg" }) : pill("Checksum does not match", "amber", { dot: true, size: "lg" })) : pill(take.status === "succeeded" ? "No receipt here" : "Receipt pending", null, { size: "lg" }),
        h("span", { class: "seal-ref" }, digest ? h("span", { class: "mono seal-hash", title: digest }, short(digest, 16)) : null,
          receiptFile ? h("a", { class: "link-btn", href: receiptFile, target: "_blank", rel: "noopener" }, "receipt.json") : null)),
      sealHint,
      receiptFile && digest ? checkHere : null);
    // anyone can check the seal themselves: this browser fetches receipt.json and hashes it the way openfield verify does;
    // what it cannot tell is an error, never a fail
    const answer = (result, words) => {
      sealHint.dataset.result = result;
      sealHint.replaceChildren(...(result === "pass" ? [icon("check", "sm")] : result === "fail" ? [icon("x", "sm")] : []), h("span", null, words));
    };
    checkHere.addEventListener("click", async () => {
      checkHere.disabled = true;
      delete sealHint.dataset.result;
      sealHint.textContent = "Checking in this browser…";
      try {
        const res = await fetch(receiptFile, { cache: "no-store", signal: AbortSignal.timeout?.(15_000) });
        if (!res.ok) throw new Error(`receipt.json answered ${res.status}`);
        const result = await checkSeal(await res.text());
        if (result.ok) answer("pass", `Checked in this browser: receipt.json matches its seal (${short(result.actual, 12)}).`);
        else if (result.reason === "not a receipt") { console.warn("Not a receipt:", result.detail); answer("error", "What came back for receipt.json was not a receipt."); } // a page served in its place
        else if (result.reason === "unavailable") answer("error", "This browser cannot hash here (it needs https or localhost).");
        else if (result.reason === "hashing failed") answer("error", "This browser could not hash the receipt just now. Try again.");
        else answer("fail", "Checked in this browser: receipt.json does not match its seal.");
      } catch (error) {
        console.warn("Could not check the receipt:", error);
        answer("error", "Could not fetch the receipt.");
      }
      checkHere.disabled = false;
    });
    // the receipt reads as a ticket stub: its head names the take it admits, then the billing order every stub keeps
    // (seed, steps, length, recipe), then the checks
    const head = h("div", { class: "verdict-head" }, h("span", null, "Receipt"), h("span", { class: "num" }, take.id));
    const rows = billing(take, store.get().moves).filter(([label]) => label !== "Audit"); // the audit has its own row
    // what the take cost: the GPU time its receipt recorded, priced at the rate a rented RTX 5090 costs
    const gpu = gpuSeconds(view?.receipt);
    if (gpu) rows.push(["GPU", `${Math.round(gpu)} s`], ["Cost", `≈ ${gpuCost(gpu)}`, null, `${Math.round(gpu)} s of GPU time from the receipt. An estimate.`]);
    const bill = rows.length ? h("dl", { class: "verdict-billing" }, rows.map(([label, value, , note]) => h("div", note ? { title: note } : null, h("dt", null, label), h("dd", { class: "num" }, value)))) : null;
    return h("div", { class: "verdict" }, head, bill, auditRow, idRow, sealRow);
  }

  /** Stills first, then the shot: the mechanism, visible on every finished take. */
  function stagesStrip(take, view) {
    const items = stageStrip(take, view?.receipt);
    if (!items.length) return null;
    return h("div", { class: "stages-strip" }, h("div", { class: "strip-label" }, take.edit ? "Before and after" : "Stills first, then the shot"),
      h("div", { class: "stages-row" }, items.map((s) => {
        const tone = s.report?.status === "pass" ? "green" : s.report?.status === "drift" ? "amber" : null;
        const src = s.id === "shot" ? thumbOf(store.get(), take, api) : stillThumb(store.get(), take, s.file, api); // cards, not the full stills
        return h("figure", { class: "stage-card" }, h("img", { "data-src": src, alt: s.name, loading: "lazy", decoding: "async" }), // wake() sets it
          h("figcaption", null, h("span", { class: "stage-name" }, s.approved ? icon("check", "sm") : null, s.name),
            tone ? h("span", { class: "num", "data-tone": tone }, formatScore(s.report.score)) : null));
      })));
  }

  function identitySection(take) {
    const stages = perStage(take.identity);
    if (!stages.length) return null;
    return section("Identity", h("div", { class: "identity" }, h("ul", { class: "stages" }, stages.map((s) => h("li", null, h("span", null, stepName(s.stage)), h("span", { class: "num" }, formatScore(s.score)),
      pill(s.status === "pass" ? "Same" : s.status === "drift" ? (s.retried ? "Drifted, retried" : "Drifted") : s.status === "na" ? "n/a" : "Unavailable", TONE[s.status]))))), { open: false });
  }

  function auditSection(receipt) {
    const models = receipt?.models ?? [];
    if (!models.length) return null;
    const list = h("ul", { class: "models", hidden: true }, models.map((m) => h("li", null, h("span", { class: "model-file mono", title: m.file }, m.file), h("span", { class: "hint" }, m.role), pill(m.license ?? "licence unknown"))));
    const toggle = h("button", { type: "button", class: "link-btn", "aria-expanded": "false" }, `Show the ${models.length} model files`);
    toggle.addEventListener("click", () => {
      const open = list.hidden;
      list.hidden = !open;
      toggle.setAttribute("aria-expanded", String(open));
      toggle.textContent = open ? "Hide the model files" : `Show the ${models.length} model files`;
    });
    const attribution = [...new Set(models.map((m) => m.attribution).filter(Boolean))];
    return section("Open weights", h("div", { class: "stack" }, h("p", { class: "hint" }, ...licenceSummary(models)), h("div", null, toggle), list,
      ...attribution.map((a) => h("p", { class: "hint" }, a))));
  }

  function receiptSection(take, view) {
    if (!view) return section("Receipt", h("p", { class: "hint" }, take.status === "succeeded" ? "This take has no receipt on this computer." : take.replay ? "The receipt was written with the original take." : "The receipt is written when the take finishes."), { open: false });
    const r = view.receipt;
    const rows = kv([
      ["Take", h("span", { class: "mono" }, r.take?.id)],
      ["Made", r.take?.created_at ? new Date(r.take.created_at).toLocaleString() : null],
      ["Rendered on", r.backend?.label || r.backend?.kind],
      r.backend?.job_id && ["Job", h("span", { class: "mono", title: r.backend.job_id }, short(r.backend.job_id, 24))],
      r.workflow?.sha256 && ["Workflow", h("span", { class: "mono", title: r.workflow.sha256 }, short(r.workflow.sha256, 16))],
      r.inputs?.seed != null && ["Seed", h("span", { class: "mono" }, r.inputs.seed)],
      r.inputs?.final_prompt && ["Prompt", h("span", { class: "hint-text" }, r.inputs.final_prompt)],
    ]);
    return section("Receipt", h("div", { class: "stack" }, rows, r.disclosure ? h("p", { class: "hint" }, r.disclosure) : null), { open: false });
  }

  /** The code behind a take, on screen: a floating sheet with the snippet, so nobody has to leave the app to read it. */
  function codeSheet({ title, url, name }) {
    const pre = h("pre", { class: "code", tabindex: "0" }, "Loading\u2026");
    const copy = h("button", { type: "button", class: "btn secondary sm" }, "Copy");
    const raw = h("a", { class: "btn ghost sm", href: url, target: "_blank", rel: "noopener" }, name);
    copy.addEventListener("click", async () => notify(ctx, (await copyText(pre.textContent)) ? "Code copied." : "Could not copy the code.", "", "info"));
    openSheet({ title, body: pre, actions: [copy, raw], className: "sheet-code" });
    fetch(url).then((r) => (r.ok ? r.text() : Promise.reject(new Error(r.statusText))))
      .then((text) => { pre.textContent = text; })
      .catch(() => { pre.textContent = "Could not load the snippet. Open the raw file instead."; });
  }

  /** The share sheet: the caption, the places to send it and the video itself, all in one place. */
  function shareSheet(take, { isStatic, recorded }) {
    const { api, store } = ctx;
    const url = sharePageUrl(take.id, { isStatic, href: location.href });
    const caption = captionFor({ takes: [take], url, moves: store.get().moves });
    const media = api.media(take, fileOf(take, "video") ?? "take.mp4");
    const title = titleOf(take);

    const copyLink = h("button", { type: "button", class: "btn secondary" }, icon("link"), "Copy link");
    const copyCaption = h("button", { type: "button", class: "btn secondary" }, icon("check"), "Copy caption");
    copyLink.addEventListener("click", async () => notify(ctx, (await copyText(url)) ? "Link copied." : "Could not copy the link.",
      isStatic || recorded ? "Opens this take, with its receipt." : "Works on this computer only. Publish a Replay to share it.", "info"));
    copyCaption.addEventListener("click", async () => notify(ctx, (await copyText(caption)) ? "Caption copied." : "Could not copy the caption.",
      "Paste it with the video. Edit freely.", "info"));

    // the video as a file, fetched as the sheet opens: the Share click has to stay a gesture the browser accepts
    let pending = null;
    const videoFile = () => (pending ??= fetch(media)
      .then((res) => (res.ok ? res.blob() : null))
      .then((blob) => (blob ? new File([blob], `${take.id}.mp4`, { type: blob.type || "video/mp4" }) : null))
      .catch(() => null));
    const native = typeof navigator.share === "function" ? h("button", { type: "button", class: "btn primary" }, icon("send"), "Share…") : null;
    const files = typeof navigator.canShare === "function"; // only a browser that can share files fetches the video
    if (native) {
      if (files) videoFile();
      native.addEventListener("click", async () => {
        native.disabled = true;
        try {
          const clip = files ? await videoFile() : null;
          const data = clip && navigator.canShare?.({ files: [clip] }) ? { files: [clip], title, text: caption } : { url, title, text: caption };
          await navigator.share(data);
        } catch (error) {
          if (error?.name !== "AbortError") notify(ctx, "The share did not go out.", "Your browser blocked it. Copy the link instead.", "error");
        } finally {
          native.disabled = false;
        }
      });
    }

    const links = h("div", { class: "share-links" }, shareTargets({ url, text: caption }).map((target) =>
      h("a", { class: "btn ghost sm", href: target.href, target: "_blank", rel: "noopener noreferrer", "aria-label": `Share on ${target.label}` }, target.label)));
    const download = h("a", { class: "btn secondary", href: media, download: `${take.id}.mp4` }, icon("upload"), "Download video");
    // a Direct take can go out with its planned camera drawn in a corner, travelling in step
    const move = take.kind === "direct" ? store.get().moves?.moves.find((m) => m.id === take.recipe?.rig?.movement) : null;
    const withPath = move?.path?.length && canSaveWithPath()
      ? savePathButton(ctx, take, move, { onError: (why) => notify(ctx, "Could not save the video.", why, "error"), onSaved: (name) => notify(ctx, "Saved.", name, "info") }) : null;
    // one picture of the take as planned and made: its frames, the camera's path, the words and the receipt
    const sheet = move?.path?.length ? shotSheetButton(ctx, take, move, { link: url, onError: (why) => notify(ctx, "Could not draw the sheet.", why, "error") }) : null;

    openSheet({
      title: "Share this take",
      className: "sheet-share",
      body: h("div", { class: "share-body" },
        h("p", { class: "hint" }, "The caption travels with the take: paste it with the video."),
        h("pre", { class: "code", tabindex: "0" }, caption),
        links,
        h("div", { class: "action-row" }, copyLink, copyCaption, native, download, withPath, sheet)),
    });
  }

  function actions(take, view, recorded) {
    const isStatic = api.kind === "static";
    const live = !recorded && !isStatic;
    const btn = (label, name, onClick, opts = {}) => {
      const b = h("button", { type: "button", class: `btn ${opts.primary ? "primary" : "secondary"}${opts.small ? " sm" : ""}${opts.large ? " lg" : ""}`, disabled: opts.disabled }, icon(name, opts.small ? "sm" : undefined), label);
      b.addEventListener("click", onClick);
      return b;
    };
    const link = (label, name, href, download) => h("a", { class: "btn secondary sm", href, ...(download ? { download: "" } : { target: "_blank", rel: "noopener" }) }, icon(name, "sm"), label);
    const done = take.status === "succeeded" || recorded;
    const canRender = !isStatic && !store.get().status?.backend?.locked;
    const lead = []; // the one thing to do next
    const row = []; // what the take gives you, compact
    const tail = []; // exports and deletion
    if (done && take.edit?.after) {
      const animate = btn("Animate this still in Direct", "clapperboard", () => animateStill(ctx, take, take.edit.after, "The edited still"), { large: true, disabled: !canRender });
      if (!canRender) animate.append(h("span", { class: "btn-hint" }, "needs a backend"));
      lead.push(animate);
    }
    if (take.status === "awaiting_approval") lead.push(btn("Review the stills", "image", () => { controller.select(take.id); ui.go(take.kind === "reshoot" ? "reshoot" : "direct"); }, { primary: true }));
    // one orange action per screen: the shot card's primary is the screen's; here the lead is a large secondary
    if (["direct", "reshoot"].includes(take.kind)) lead.push(btn("Use these settings", "undo-2", () => loadTake(ctx, take), { large: take.status !== "awaiting_approval" }));
    if (done && ["direct", "reshoot"].includes(take.kind)) row.push(btn("Transition…", "arrow-left-right", () => openTransitionSheet(ctx, take), { small: true }));
    // an extension can be extended again
    if (done && ["direct", "extend"].includes(take.kind) && store.get().moves?.extend) row.push(btn("Extend…", "chevrons-right", () => openExtendSheet(ctx, take), { small: true }));
    if (done && upscalable(take) && store.get().moves?.upscale) row.push(btn("Upscale…", "maximize", () => openUpscaleSheet(ctx, take), { small: true }));
    // an edit's result, a board's first setup
    if (done && ["direct", "shots", "edit"].includes(take.kind)) row.push(btn("Edit with words…", "image", () => openEditSheet(ctx, take, { still: take.edit?.after ?? take.shots?.[0]?.file, receipt: view?.receipt }), { small: true }));
    if (done && take.kind === "direct" && take.recipe?.line) row.push(btn("Dub…", "volume-2", () => openDubSheet(ctx, take, { receipt: view?.receipt }), { small: true }));
    if (take.status === "succeeded" && !take.replay) {
      row.push(btn("Share…", "send", () => shareSheet(take, { isStatic, recorded }), { small: true }));
    }
    // side by side with another take, over what their receipts say differently
    if (done && fileOf(take, "video") && take.kind !== "export" && canCompare(store.get(), take)) row.push(btn("Compare…", "columns-2", () => openCompareSheet(ctx, take.id), { small: true }));
    if (view?.recipe_link) {
      row.push(btn("Copy recipe link", "file-json", async () => {
        const url = `${location.origin}${location.pathname}#recipe=${view.recipe_link}`;
        notify(ctx, (await copyText(url)) ? "Recipe link copied." : "Could not copy the link.", "Opens these settings in OpenField. No footage.", "info");
      }, { small: true }));
    }
    if (take.status === "succeeded") {
      const workflow = link("Download workflow", "package", api.workflowsUrl(take), true);
      workflow.title = "The workflows this take ran, as JSON for ComfyUI.";
      row.push(workflow);
      const snippet = link("SDK snippet", "file-json", api.snippetUrl(take));
      snippet.title = "Reproduce this render step with comfy-sdk";
      snippet.addEventListener("click", (e) => {
        if (e.ctrlKey || e.metaKey || e.shiftKey || e.button) return; // a modified click still opens the raw file
        e.preventDefault();
        codeSheet({ title: "Reproduce this step with comfy-sdk", url: snippet.href, name: "sdk-snippet.py" });
      });
      row.push(snippet); // the receipt file is linked from its own row in the verdict strip
    }
    if (take.kind === "direct" && take.status === "succeeded") {
      const vertical = btn("Export 9:16", "smartphone", async () => { const out = await controller.exportVertical(take.id, cropFocus(cropFocusByTake, take.id)); if (out) ui.go("takes"); }, { disabled: !live });
      if (!live) {
        vertical.append(h("span", { class: "btn-hint" }, "needs a backend"));
        tail.push(vertical);
      } else {
        const focus = segmented({
          label: "Crop focus",
          options: [{ value: 0.2, label: "Left" }, { value: 0.5, label: "Centre" }, { value: 0.8, label: "Right" }],
          value: cropFocus(cropFocusByTake, take.id),
          onChange: (v) => cropFocusByTake.set(take.id, v),
        });
        tail.push(h("div", { class: "field" }, focus.el, vertical));
      }
    }
    if (live) {
      const del = btn(armed === take.id ? "Click again to delete" : "Delete take", "trash-2", () => {
        if (armed !== take.id) { armed = take.id; shownKey = null; return render(); }
        armed = null;
        controller.remove(take.id);
      });
      del.classList.add("quiet-danger");
      tail.push(del);
    }
    return h("div", { class: "section" }, h("div", { class: "section-body dock-actions" }, ...lead, row.length ? h("div", { class: "action-row" }, row) : null, ...tail));
  }

  async function render() {
    const state = store.get();
    const kinds = KINDS[state.route] ?? KINDS.takes;
    const { take, recorded } = focusTake(state, kinds);
    const key = take ? `${take.id}|${take.status}|${armed}|${JSON.stringify(take.identity ?? {})}|${state.previews ? "small" : "full"}` : "none";
    if (key === shownKey) return;
    shownKey = key;
    if (!take) {
      el.replaceChildren(h("div", { class: "empty" }, icon("shield-check", "lg"), h("h2", null, "Nothing selected"), h("p", null, "Pick a take to see how it was made.")));
      return;
    }
    const view = take.status === "succeeded" ? await receiptOf(take) : null;
    if (shownKey !== key) return; // something newer arrived while the receipt loaded
    el.replaceChildren(...[
      h("div", { class: "take-head" }, h("h3", null, titleOf(take)), h("p", { class: "hint" }, take.replay ? "Replay of a recorded take" : recorded ? "Recorded take" : take.created_at ? `Made ${ago(take.created_at)}` : ""),
        ...(take.notes ?? []).map(plainNote).filter(Boolean).map((note) => h("p", { class: "hint take-note" }, note))), // what a reader should know (a re-shoot names its source)
      verdict(take, view),
      stagesStrip(take, view),
      actions(take, view, recorded),
      identitySection(take)?.el, auditSection(view?.receipt)?.el, receiptSection(take, view).el,
    ].filter(Boolean));
  }

  // the strip's pictures load only while the panel is on screen: a closed panel (and the Lobby's, which is never shown)
  // still sits beside the page, near enough for lazy loading to fetch the stills on a first visit
  const panelShown = () => ui.get().dockOpen && !["lobby", "chat"].includes(store.get().route);
  function wake() {
    if (!panelShown()) return;
    for (const img of el.querySelectorAll("img[data-src]")) { img.src = img.dataset.src; img.removeAttribute("data-src"); }
  }
  const paint = () => render().then(wake);
  store.subscribe((_, changed) => changed.some((k) => ["takes", "selected", "recorded", "route", "previews"].includes(k)) && paint());
  ui.subscribe((_, changed) => changed.includes("dockOpen") && wake());
  paint();
  return { el, render: () => { shownKey = null; return paint(); } };
}
