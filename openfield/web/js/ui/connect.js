// The Connect sheet: point the studio at a render target without leaving the app, and see plainly what it can run.
//
// A GPU box is comfy-api-proxy in front of ComfyUI (Vast.ai, RunPod, a local PC): its address, the token it was
// started with, and, if you give it, ComfyUI's own address for the model and node check. Comfy Cloud is an API key.
// Test never switches. Use switches new takes only. The address can be remembered; the key never leaves memory.

import { copyText, h, icon } from "./dom.js";
import { field, section, segmented, switchRow, textField } from "./controls.js";
import { openSheet } from "./sheet.js";
import { notify } from "./actions.js";
import { cloneLine } from "../lib/install.js";

export const PLACEHOLDERS = { base_url: "http://127.0.0.1:9189", comfy_url: "http://127.0.0.1:9188" };
export const GUIDE = [
  { title: "1. Rent a box", text: "Vast.ai or RunPod. Allow 150 GB of disk." },
  { title: "2. Set it up (one script)", code: "scp -P <PORT> scripts/pod_setup.sh scripts/fetch_template_models.py openfield/engine/manifest.json root@<BOX>:/workspace/" },
  { title: "   then on the box", code: "export HF_TOKEN=<read-only token>; bash /workspace/pod_setup.sh" },
  { title: "3. Tunnel it here", code: "ssh -N -L 9189:127.0.0.1:8189 -L 9188:127.0.0.1:8188 -p <PORT> root@<BOX>" },
  { title: "Your own ComfyUI", code: "pip install comfy-api-proxy && comfy-api-proxy run --comfyui http://127.0.0.1:8188 --port 8189 --comfyui-base-dir <ComfyUI>" },
  { title: "Comfy Cloud", text: "An API key from platform.comfy.org, on a paid plan." },
];
const TONES = { ready: "green", missing: "red", unknown_nodes: "red", unavailable: "amber" };

/** One readiness row: a workflow and what the box said about it. */
export function readinessText(w) {
  if (w.state === "ready") return "Ready";
  if (w.state === "missing") return `Missing: ${w.missing.map((m) => `${m.file} (models/${m.directory}, from ${m.repo})`).join(", ")}`;
  if (w.state === "unknown_nodes") return `This ComfyUI lacks ${w.unknown_nodes.join(", ")}`;
  return w.detail ?? w.state;
}

function resultCard(res, kind) {
  const ok = Boolean(res.health?.ok);
  const where = `${res.target?.label ?? "target"} at ${res.target?.host ?? "?"}`;
  const rows = [
    h("div", { class: "connect-line" }, h("span", { class: "status-dot", "data-tone": ok ? "green" : "red" }),
      h("b", null, ok ? `Reachable: ${where}` : `Not connected: ${where}`),
      h("span", { class: "hint" }, ok ? (res.health.authenticated ? "token accepted" : "") : (res.health?.detail ?? ""))),
  ];
  for (const w of res.warnings ?? []) rows.push(h("p", { class: "hint connect-warn" }, icon("triangle-alert", "sm"), h("span", null, w)));
  const pre = res.preflight;
  if (pre?.state === "checked") {
    const sys = pre.comfyui ?? {};
    const box = [sys.version ? `ComfyUI ${sys.version}` : null, sys.device, sys.vram_total_gb ? `${sys.vram_total_gb} GB` : null].filter(Boolean).join(" · ");
    if (box) rows.push(h("p", { class: "hint" }, box));
    rows.push(h("div", { class: "ready-table", role: "table", "aria-label": "Workflow readiness" },
      ...pre.workflows.map((w) => h("div", { class: "ready-row", role: "row", "data-state": w.state },
        h("span", { class: "status-dot", "data-tone": TONES[w.state] ?? "amber" }),
        h("span", { class: "ready-name", role: "cell" }, w.label), h("span", { class: "ready-state", role: "cell" }, readinessText(w))))));
    const hints = [...new Set(pre.workflows.flatMap((w) => w.missing.map((m) => m.hint)))];
    if (hints.length) rows.push(h("p", { class: "hint" }, "On the box: ", h("code", null, hints.join("  ·  ")), " (HF_TOKEN for gated files)."));
    rows.push(h("p", { class: "hint" }, pre.summary));
  } else if (pre) {
    rows.push(h("p", { class: "hint connect-warn" }, icon("triangle-alert", "sm"), h("span", null, `Model check: ${pre.summary}`)));
  } else if (kind === "pod") {
    rows.push(h("p", { class: "hint" }, "Model files not checked. Add the ComfyUI address to check them."));
  } else {
    rows.push(h("p", { class: "hint" }, "Comfy Cloud lists no model files. Missing ones show at render."));
  }
  return h("div", { class: "connect-result" }, ...rows);
}

function guideBlock(ctx) {
  const items = GUIDE.map((step) => {
    const copy = step.code ? h("button", { type: "button", class: "btn ghost sm", "aria-label": `Copy: ${step.title.trim()}` }, "Copy") : null;
    copy?.addEventListener("click", async () => notify(ctx, (await copyText(step.code)) ? "Copied." : "Could not copy.", "", "info"));
    return h("div", { class: "guide-step" }, h("b", null, step.title), step.text ? h("p", { class: "hint" }, step.text) : null,
      step.code ? h("div", { class: "guide-code" }, h("code", null, step.code), copy) : null);
  });
  return section("Get a GPU box", h("div", { class: "stack" }, ...items, h("p", { class: "hint" }, "The long version, with RunPod and the tunnel, is in docs/CONNECT.md.")), { open: false });
}

export function openConnectSheet(ctx) {
  const { api, store, controller } = ctx;
  const status = store.get().status;
  const b = status?.backend ?? {};
  if (api.kind === "static") {
    const code = h("code", null, cloneLine(null)); // the placeholder address first; the site's own follows
    const body = h("div", { class: "stack connect-body" },
      h("p", null, "Recorded takes only. Install OpenField and connect a backend to render."),
      h("div", { class: "guide-code" }, code),
      guideBlock(ctx).el);
    const sheet = openSheet({ title: "Connect a backend", body, className: "sheet-connect" });
    Promise.resolve(api.site?.()).then((site) => { if (site?.repo_url) code.textContent = cloneLine(site.repo_url); });
    return sheet;
  }

  const target = b.target ?? null;
  const state = {
    kind: target?.kind === "cloud" ? "cloud" : "pod",
    base_url: target?.kind === "pod" ? target.url ?? "" : "",
    api_key: "", comfy_url: target?.comfy_url ?? "", remember: true,
  };
  const body = () => (state.kind === "cloud"
    ? { base_url: "", api_key: state.api_key, comfy_url: "" }
    : { base_url: state.base_url, api_key: state.api_key, comfy_url: state.comfy_url });
  let passed = null; // the JSON of the body that last tested ok

  const result = h("div", { class: "connect-results" });
  const testBtn = h("button", { type: "button", class: "btn secondary" }, icon("refresh-cw"), "Test");
  const useBtn = h("button", { type: "button", class: "btn primary", disabled: true }, icon("cloud"), "Use this backend");
  const dirty = () => { useBtn.disabled = passed !== JSON.stringify(body()); };

  const baseUrl = textField({ id: "connect-url", value: state.base_url, placeholder: PLACEHOLDERS.base_url, onInput: (v) => { state.base_url = v.trim(); dirty(); } });
  const token = textField({ id: "connect-token", type: "password", placeholder: "only if the proxy was started with a token", onInput: (v) => { state.api_key = v.trim(); dirty(); } });
  const comfyUrl = textField({ id: "connect-comfy", value: state.comfy_url, placeholder: PLACEHOLDERS.comfy_url, onInput: (v) => { state.comfy_url = v.trim(); dirty(); } });
  const key = textField({ id: "connect-key", type: "password", placeholder: "comfyui-…", onInput: (v) => { state.api_key = v.trim(); dirty(); } });
  const pod = h("div", { class: "stack", hidden: state.kind !== "pod" },
    field("Proxy address", baseUrl.el, { id: "connect-url", hint: "comfy-api-proxy on the box, through your SSH tunnel: usually http://127.0.0.1:9189." }).el,
    field("Token (optional)", token.el, { id: "connect-token", hint: "Kept in memory until the app closes. Never written to disk." }).el,
    field("ComfyUI address (optional)", comfyUrl.el, { id: "connect-comfy", hint: "Optional. Lets Test check every model file and node." }).el);
  const cloud = h("div", { class: "stack", hidden: state.kind !== "cloud" },
    field("API key", key.el, { id: "connect-key", hint: "From platform.comfy.org, on a paid plan. Never written to disk." }).el);
  const kind = segmented({
    label: "Target", value: state.kind,
    options: [{ value: "pod", label: "GPU box" }, { value: "cloud", label: "Comfy Cloud" }],
    onChange: (v) => { state.kind = v; state.api_key = ""; token.set(""); key.set(""); pod.hidden = v !== "pod"; cloud.hidden = v !== "cloud"; dirty(); },
  });
  const remember = switchRow({ title: "Remember the address", hint: "Never the key or token.", value: true, onChange: (v) => { state.remember = v; } });

  testBtn.addEventListener("click", async () => {
    testBtn.disabled = true;
    result.replaceChildren(h("p", { class: "hint" }, "Testing…"));
    const res = await controller.testBackend(body());
    testBtn.disabled = false;
    if (!res) { result.replaceChildren(); return; } // the controller already posted why
    passed = res.health?.ok ? JSON.stringify(body()) : null;
    result.replaceChildren(resultCard(res, state.kind));
    dirty();
  });
  useBtn.addEventListener("click", async () => {
    useBtn.disabled = true;
    const next = await controller.connectBackend({ ...body(), remember: state.remember });
    if (!next) { dirty(); return; }
    const t = next.backend?.target;
    notify(ctx, `Connected: ${t?.label ?? "backend"} at ${t?.host ?? "?"}. New takes render there.`, "", "info");
    sheet.close();
  });

  const foot = h("div", { class: "connect-foot" });
  const paintFoot = () => {
    const now = store.get().status?.backend ?? {};
    const kids = [];
    if (now.configured && now.target) {
      kids.push(h("span", { class: "hint" }, icon(now.locked ? "film" : "cloud", "sm"),
        ` ${now.locked ? "Replay is on · " : ""}${now.target.label} at ${now.target.host}${now.source === "saved" ? " (remembered)" : now.source === "env" ? " (from the environment)" : ""}`));
      if (now.source === "saved" || now.source === "session") {
        const forget = h("button", { type: "button", class: "btn ghost sm" }, "Forget");
        forget.addEventListener("click", async () => { if (await controller.forgetBackend()) notify(ctx, "Forgotten. Replay plays the recorded takes.", "", "info"); });
        kids.push(forget);
      }
    } else {
      kids.push(h("span", { class: "hint" }, "No backend yet: Replay plays the recorded takes."));
    }
    foot.replaceChildren(...kids);
  };
  paintFoot();
  const unsubscribe = store.subscribe((_, changed) => changed.includes("status") && paintFoot());

  const form = h("div", { class: "stack connect-body" },
    field("Target", kind.el, { id: "connect-kind" }).el, pod, cloud,
    h("div", { class: "connect-actions" }, testBtn, useBtn, h("span", { class: "grow" }), remember.el),
    result, foot, guideBlock(ctx).el);
  // onClose runs on every way out (Escape, the scrim, the X, Back, close()), so the footer's subscription never outlives the sheet
  const sheet = openSheet({ title: "Connect a backend", body: form, className: "sheet-connect", onClose: () => unsubscribe?.() });
  (state.kind === "pod" ? baseUrl.el : key.el).focus();
  return sheet;
}
