// The Take tab of the dock: what a person can do with a take, and how it was made and whether to trust it:
// identity check, open-weights audit, receipt.

import { ago } from "../lib/format.js";
import { formatScore, perStage, ringState } from "../lib/identity.js";
import { focusTake, stepName, titleOf } from "../lib/stages.js";
import { copyText, h, icon, svg } from "./dom.js";
import { pill, section } from "./controls.js";
import { loadTake, notify } from "./actions.js";

const TONE = { pass: "green", drift: "amber" };
const KINDS = { direct: ["direct"], reshoot: ["reshoot"], takes: ["direct", "reshoot", "export"] };

/** The Identity Ring: the score as an arc, the pass line (0.363) as a tick across it. */
export function identityRing(report) {
  const state = ringState(report);
  const R = 26;
  const C = 2 * Math.PI * R;
  const root = svg("svg", { viewBox: "0 0 64 64", class: `ring ring-${state.status}`, role: "img", "aria-label": `${state.label}${state.score != null ? `, score ${formatScore(state.score)}` : ""}` });
  root.append(svg("circle", { cx: 32, cy: 32, r: R, class: "ring-track" }));
  if (state.fraction > 0) root.append(svg("circle", { cx: 32, cy: 32, r: R, class: "ring-arc", "stroke-dasharray": `${(state.fraction * C).toFixed(2)} ${C.toFixed(2)}`, transform: "rotate(-90 32 32)" }));
  if (state.tick != null) {
    const a = state.tick * 2 * Math.PI - Math.PI / 2;
    const at = (r) => [32 + r * Math.cos(a), 32 + r * Math.sin(a)];
    const [x1, y1] = at(R - 5.5);
    const [x2, y2] = at(R + 5.5);
    root.append(svg("line", { x1, y1, x2, y2, class: "ring-tick" }));
  }
  root.append(svg("text", { x: 32, y: 36, class: "ring-num", "text-anchor": "middle" }, state.score == null ? (state.status === "na" ? "n/a" : "–") : formatScore(state.score)));
  return root;
}

const kv = (rows) => h("dl", { class: "kv" }, rows.filter(Boolean).flatMap(([k, v]) => [h("dt", null, k), h("dd", null, v)]));
const short = (s, n = 14) => (s && s.length > n ? `${s.slice(0, n)}…` : s);

/** "LTX-2.x Community License (4), Qwen Research License (3)" */
function licenceSummary(models) {
  const counts = new Map();
  for (const m of models) counts.set(m.license ?? "licence unknown", (counts.get(m.license ?? "licence unknown") ?? 0) + 1);
  return [...counts].map(([name, n]) => `${name} (${n})`).join(", ");
}

export function createDetails(ctx) {
  const { api, store, controller, ui } = ctx;
  const el = h("div", { class: "dock-pane", "data-pane": "take", hidden: true });
  const receipts = new Map();
  let shownKey = null;
  let armed = null; // a take whose delete button was pressed once

  async function receiptOf(take) {
    if (!receipts.has(take.id)) receipts.set(take.id, api.receipt(take).catch(() => null));
    return receipts.get(take.id);
  }

  function identitySection(take) {
    const reports = Object.values(take.identity ?? {});
    const stages = perStage(take.identity);
    const worst = reports.find((r) => r.status === "drift") ?? reports[0];
    const total = ringState(worst);
    const body = !stages.length
      ? h("p", { class: "hint" }, "No face check ran for this take. Shots with no real face show n/a.")
      : h("div", { class: "identity" },
        h("div", { class: "identity-top" }, identityRing(worst),
          h("div", null, h("strong", null, total.label), h("p", { class: "hint" }, `Passes at ${total.threshold ?? 0.363} or higher. Compared with the character's photos on this computer; nothing is uploaded.`))),
        h("ul", { class: "stages" }, stages.map((s) => h("li", null, h("span", null, stepName(s.stage)), h("span", { class: "num" }, formatScore(s.score)),
          pill(s.status === "pass" ? "Same" : s.status === "drift" ? (s.retried ? "Drifted, retried" : "Drifted") : s.status === "na" ? "n/a" : "Unavailable", TONE[s.status])))));
    return section("Identity", body, { open: stages.length > 0 });
  }

  function auditSection(take, receipt) {
    const audit = receipt?.audit ?? take.audit;
    const models = receipt?.models ?? [];
    const pass = audit?.result === "pass";
    const head = audit
      ? h("div", { class: "audit-head" }, pill(pass ? "Open weights only" : "Audit failed", pass ? "green" : "red", { dot: true, size: "lg" }),
        h("p", { class: "hint" }, pass ? "Every model in this take's workflows is an open-weights file, and no partner or paid API node ran." : `Not allowed: ${(audit.disallowed ?? []).join(", ") || "see the receipt"}.`))
      : h("p", { class: "hint" }, take.replay ? "The audit was recorded with the original take." : "The audit runs when a take finishes.");
    const list = h("ul", { class: "models", hidden: true }, models.map((m) => h("li", null, h("span", { class: "model-file mono", title: m.file }, m.file), h("span", { class: "hint" }, m.role), pill(m.license ?? "licence unknown"))));
    const toggle = h("button", { type: "button", class: "link-btn", "aria-expanded": "false" }, `Show the ${models.length} model files`);
    toggle.addEventListener("click", () => {
      const open = list.hidden;
      list.hidden = !open;
      toggle.setAttribute("aria-expanded", String(open));
      toggle.textContent = open ? "Hide the model files" : `Show the ${models.length} model files`;
    });
    const attribution = [...new Set(models.map((m) => m.attribution).filter(Boolean))];
    return section("Open weights", h("div", { class: "stack" }, head,
      models.length ? h("p", { class: "hint" }, licenceSummary(models)) : null,
      models.length ? h("div", null, toggle) : null, models.length ? list : null,
      ...attribution.map((a) => h("p", { class: "hint" }, a))));
  }

  function receiptSection(take, view) {
    if (!view) return section("Receipt", h("p", { class: "hint" }, take.status === "succeeded" ? "This take has no receipt on this computer." : take.replay ? "The receipt was sealed with the original take." : "The receipt is sealed when the take finishes."), { open: false });
    const r = view.receipt;
    const seal = view.verified === true ? pill("Checksum matches", "green", { dot: true }) : pill("Checksum does not match", "amber", { dot: true });
    const rows = kv([
      ["Take", h("span", { class: "mono" }, r.take?.id)],
      ["Made", r.take?.created_at ? new Date(r.take.created_at).toLocaleString() : null],
      ["Rendered on", r.backend?.label || r.backend?.kind],
      r.backend?.job_id && ["Job", h("span", { class: "mono", title: r.backend.job_id }, short(r.backend.job_id, 24))],
      r.workflow?.sha256 && ["Workflow", h("span", { class: "mono", title: r.workflow.sha256 }, short(r.workflow.sha256, 16))],
      r.inputs?.seed != null && ["Seed", h("span", { class: "mono" }, r.inputs.seed)],
      r.inputs?.final_prompt && ["Prompt", h("span", { class: "hint-text" }, r.inputs.final_prompt)],
    ]);
    return section("Receipt", h("div", { class: "stack" }, seal,
      h("p", { class: "hint" }, "A checksum shows the receipt was not edited after it was written. It is not a signature."), rows,
      r.disclosure ? h("p", { class: "hint" }, r.disclosure) : null), { open: false });
  }

  function actions(take, view, recorded) {
    const isStatic = api.kind === "static";
    const live = !recorded && !isStatic;
    const btn = (label, name, onClick, opts = {}) => {
      const b = h("button", { type: "button", class: `btn ${opts.primary ? "primary" : "secondary"}`, disabled: opts.disabled }, icon(name), label);
      b.addEventListener("click", onClick);
      return b;
    };
    const link = (label, name, href, download) => h("a", { class: "btn secondary", href, ...(download ? { download: "" } : { target: "_blank", rel: "noopener" }) }, icon(name), label);
    const list = [];
    if (take.status === "awaiting_approval") list.push(btn("Review the stills", "image", () => { controller.select(take.id); ui.go(take.kind === "reshoot" ? "reshoot" : "direct"); }, { primary: true }));
    if (["direct", "reshoot"].includes(take.kind)) list.push(btn("Use these settings", "undo-2", () => loadTake(ctx, take), { primary: take.status !== "awaiting_approval" }));
    if (view?.recipe_link) {
      list.push(btn("Copy remix link", "link", async () => {
        const url = `${location.origin}${location.pathname}#recipe=${view.recipe_link}`;
        notify(ctx, (await copyText(url)) ? "Remix link copied." : "Could not copy the link.", "Anyone with OpenField can open it to load these settings.");
      }));
    }
    if (take.status === "succeeded") {
      const workflow = link("Download workflow", "package", api.workflowsUrl(take), true);
      workflow.title = "The exact graphs this take ran, as API-format JSON to load in ComfyUI";
      workflow.append(h("span", { class: "btn-hint" }, "for ComfyUI"));
      list.push(workflow);
      list.push(link("SDK snippet", "file-json", api.snippetUrl(take)));
      if (take.outputs?.some((o) => o.role === "receipt")) list.push(link("Receipt (JSON)", "shield-check", api.media(take, "receipt.json")));
    }
    if (take.kind === "direct" && take.status === "succeeded") {
      const vertical = btn("Export 9:16", "smartphone", async () => { const out = await controller.exportVertical(take.id); if (out) ui.go("takes"); }, { disabled: !live });
      if (!live) vertical.append(h("span", { class: "btn-hint" }, "needs a backend"));
      list.push(vertical);
    }
    if (live) {
      const del = btn(armed === take.id ? "Click again to delete" : "Delete take", "trash-2", () => {
        if (armed !== take.id) { armed = take.id; shownKey = null; return render(); }
        armed = null;
        controller.remove(take.id);
      });
      del.classList.add("quiet-danger");
      list.push(del);
    }
    return h("div", { class: "section" }, h("div", { class: "section-body dock-actions" }, list));
  }

  async function render() {
    const state = store.get();
    const kinds = KINDS[state.route] ?? KINDS.takes;
    const { take, recorded } = focusTake(state, kinds);
    const key = take ? `${take.id}|${take.status}|${armed}|${JSON.stringify(take.identity ?? {})}` : "none";
    if (key === shownKey) return;
    shownKey = key;
    if (!take) {
      el.replaceChildren(h("div", { class: "empty" }, icon("shield-check", "lg"), h("h2", null, "Nothing selected"), h("p", null, "Pick a take to see how it was made: identity check, open-weights audit and receipt.")));
      return;
    }
    const view = take.status === "succeeded" ? await receiptOf(take) : null;
    if (shownKey !== key) return; // something newer arrived while the receipt loaded
    el.replaceChildren(
      h("div", { class: "take-head" }, h("h3", null, titleOf(take)), h("p", { class: "hint" }, take.replay ? "Replay of a recorded take" : recorded ? "Recorded take" : take.created_at ? `Made ${ago(take.created_at)}` : "")),
      actions(take, view, recorded),
      identitySection(take).el, auditSection(take, view?.receipt).el, receiptSection(take, view).el);
  }

  store.subscribe((_, changed) => changed.some((k) => ["takes", "selected", "recorded", "route"].includes(k)) && render());
  render();
  return { el, render: () => { shownKey = null; return render(); } };
}
