// A small browser driver: Chrome or Edge, headless, over the DevTools protocol. Used by the UI smoke test
// (tests/ui/smoke.mjs) and the demo recorder (scripts/ui/record.mjs).
// No packages: Node's built-in WebSocket and fetch are enough.

import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const CANDIDATES = [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/google-chrome-stable",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
  "/usr/bin/microsoft-edge",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
];

/** The browser to use: OPENFIELD_BROWSER, else the first known Chrome or Edge on this machine. */
export const findBrowser = () => (process.env.OPENFIELD_BROWSER ? [process.env.OPENFIELD_BROWSER] : CANDIDATES).find((p) => existsSync(p)) ?? null;

const freePort = () => new Promise((resolve, reject) => {
  const server = createServer();
  server.once("error", reject);
  server.listen(0, "127.0.0.1", () => { const { port } = server.address(); server.close(() => resolve(port)); });
});

export async function launch({ port, width = 1440, height = 900, mobile = false, scale = 1 } = {}) {
  const exe = findBrowser();
  if (!exe) throw new Error("no Chrome or Edge found (set OPENFIELD_BROWSER)");
  const profile = mkdtempSync(join(tmpdir(), "openfield-ui-"));
  const debugPort = port ?? (await freePort()); // asked of the OS: a random number can land in a range Windows reserves
  const args = [
    "--headless=new", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${profile}`, "--no-first-run", "--no-default-browser-check",
    "--disable-extensions", "--disable-background-networking", "--disk-cache-size=1", "--media-cache-size=1", "--force-color-profile=srgb",
    "--autoplay-policy=no-user-gesture-required", `--window-size=${width},${height}`, "about:blank",
  ];
  if (process.env.CI || process.getuid?.() === 0) args.push("--no-sandbox", "--disable-gpu");
  const proc = spawn(exe, args, { stdio: "ignore", detached: process.platform !== "win32" });
  const stop = () => {
    try {
      if (process.platform === "win32") spawnSync("taskkill", ["/PID", String(proc.pid), "/T", "/F"], { stdio: "ignore" });
      else process.kill(-proc.pid, "SIGKILL");
    } catch { /* already gone */ }
  };
  process.on("exit", stop);

  let info = null;
  for (let i = 0; i < 80 && !info; i += 1) {
    try { info = await (await fetch(`http://127.0.0.1:${debugPort}/json/version`)).json(); } catch { await sleep(250); }
  }
  if (!info) { stop(); throw new Error("the browser did not start"); }
  const page = (await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json()).find((t) => t.type === "page");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });

  let nextId = 0;
  const waiting = new Map();
  const listeners = new Map();
  const log = { errors: [], console: [], failed: [], bad: [] };
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && waiting.has(msg.id)) {
      const { resolve, reject } = waiting.get(msg.id);
      waiting.delete(msg.id);
      return msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
    }
    if (msg.method === "Runtime.exceptionThrown") log.errors.push(msg.params.exceptionDetails.exception?.description ?? msg.params.exceptionDetails.text);
    if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") log.console.push(msg.params.args.map((a) => a.value ?? a.description ?? "").join(" "));
    if (msg.method === "Network.loadingFailed" && !msg.params.canceled) log.failed.push(msg.params.errorText);
    if (msg.method === "Network.responseReceived" && msg.params.response.status >= 400) log.bad.push(`${msg.params.response.status} ${msg.params.response.url}`);
    for (const fn of listeners.get(msg.method) ?? []) fn(msg.params);
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++nextId;
    waiting.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
  const once = (method) => new Promise((resolve) => {
    const set = listeners.get(method) ?? listeners.set(method, new Set()).get(method);
    const fn = (params) => { set.delete(fn); resolve(params); };
    set.add(fn);
  });
  for (const domain of ["Page", "Runtime", "Network"]) await send(`${domain}.enable`);
  const viewport = (w, h, isMobile = false, dpr = 1) => send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: dpr, mobile: isMobile });
  await viewport(width, height, mobile, scale);

  const api = {
    log, viewport, sleep, send,
    /** Subscribe to a DevTools event; returns the function that unsubscribes. */
    on(method, fn) {
      const set = listeners.get(method) ?? listeners.set(method, new Set()).get(method);
      set.add(fn);
      return () => set.delete(fn);
    },
    /** Run a script in every page this browser loads, before the page's own scripts. */
    async addInitScript(source) {
      await send("Page.addScriptToEvaluateOnNewDocument", { source });
    },
    async screenshot(file, { writeFileSync } = {}) {
      const { data } = await send("Page.captureScreenshot", { format: "png" });
      if (writeFileSync) writeFileSync(file, Buffer.from(data, "base64"));
      return data;
    },
    async goto(url) {
      await send("Page.navigate", { url: "about:blank" });
      const loaded = once("Page.loadEventFired");
      await send("Page.navigate", { url });
      await loaded;
    },
    async eval(expression) {
      const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
      if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? r.exceptionDetails.text);
      return r.result.value;
    },
    async waitFor(expression, { timeout = 20000, label = expression } = {}) {
      const start = Date.now();
      let last = null;
      while (Date.now() - start < timeout) {
        try { if (await api.eval(expression)) return true; } catch (error) { last = error; }
        await sleep(100);
      }
      throw new Error(`timed out after ${timeout} ms waiting for: ${label}${last ? ` (last error: ${last.message})` : ""}`);
    },
    async click(selector) {
      const box = await api.eval(`(() => { const e = document.querySelector(${JSON.stringify(selector)}); if (!e) return null; e.scrollIntoView({ block: "nearest" }); const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()`);
      if (!box) throw new Error(`no element: ${selector}`);
      await send("Input.dispatchMouseEvent", { type: "mouseMoved", ...box });
      await send("Input.dispatchMouseEvent", { type: "mousePressed", ...box, button: "left", clickCount: 1 });
      await send("Input.dispatchMouseEvent", { type: "mouseReleased", ...box, button: "left", clickCount: 1 });
    },
    async type(selector, text) {
      await api.click(selector);
      await send("Input.insertText", { text });
    },
    async key(key, { ctrl = false } = {}) {
      const codes = { Enter: 13, Escape: 27, ArrowLeft: 37, ArrowRight: 39, ArrowUp: 38, ArrowDown: 40, Tab: 9 };
      const base = { key, code: key, modifiers: ctrl ? 2 : 0, windowsVirtualKeyCode: codes[key] ?? key.toUpperCase().charCodeAt(0) };
      await send("Input.dispatchKeyEvent", { type: "keyDown", ...base, text: key.length === 1 ? key : key === "Enter" ? "\r" : undefined });
      await send("Input.dispatchKeyEvent", { type: "keyUp", ...base });
    },
    async emulate(features) {
      await send("Emulation.setEmulatedMedia", { features });
    },
    async close() {
      try { await send("Browser.close"); } catch { /* closing */ }
      try { ws.close(); } catch { /* closed */ }
      stop();
      for (let i = 0; i < 10; i += 1) {
        await sleep(300);
        try { rmSync(profile, { recursive: true, force: true }); if (!existsSync(profile)) break; } catch { /* still locked */ }
      }
    },
  };
  return api;
}
