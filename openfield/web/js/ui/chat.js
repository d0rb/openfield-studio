// The Chat room: talk to your own agent on this computer (OpenCode with an open-weights model, Claude Code or Codex,
// signed in on this machine), and it works the studio through the same MCP tools any agent can use: it plans, directs, approves and cuts, and every take it makes
// keeps its receipt. The room shows the conversation as it streams, each tool the agent used, the stills and strips it
// looked at, and links to the takes it made. The hosted copy cannot run an agent: the room says how to get one, and
// shows a take an open-weights agent made here.

import { applyEvent, blocks, newChat, pieces, statusLine, toolDetail, toolWords } from "../lib/chat.js";
import { cloneLine } from "../lib/install.js";
import { holdStill } from "../lib/motion.js";
import { fill, h, icon, setText } from "./dom.js";
import { notify } from "./actions.js";
import { selectField } from "./controls.js";
import { liveClip, previewOf } from "./wall.js";
import { printKeykode } from "./keykode.js";

const SUGGESTIONS = [
  "What can you do in this studio?",
  "Direct a slow dolly-in on a lighthouse keeper at dusk",
  "Plan a three-shot movie about a street musician, and show me the list first",
  "Look at my latest take and tell me if it holds",
];
const TOOL_ICON = { running: "clock", done: "check", error: "circle-alert" };
const BUSY = new Set(["busy", "starting", "stopping"]);
const MADE_HERE = "tk_20261025_135037_c07b"; // shot here on 2026-10-25 by OpenCode with DeepSeek V4.1 Flash (open weights)

export function createChatStation(ctx) {
  const { api, store, controller, ui } = ctx;
  const chat = newChat();
  const nodes = new Map(); // a conversation item -> its element
  const drawn = new WeakMap(); // an agent's words -> what they show now, so a change draws only what differs
  let info = null;
  let source = null;
  let repoUrl = null; // the repository the hosted copy was built from, when it says
  let proof = null; // the hosted card's take, made once so repainting never restarts its loop
  let recent = true; // the event being drawn just happened (not one replayed from before this page opened)
  let glide = false; // something recent was drawn since the last frame
  let pinned = true; // following the end of the conversation, until the person scrolls up
  let lastTop = 0;
  let end = 0; // the log's height when it last scrolled to its end
  let frame = 0;

  const lane = h("p", { class: "hint chat-lane" });
  const reset = h("button", { type: "button", class: "btn ghost sm" }, icon("refresh-cw", "sm"), "New chat");
  // which agent, and which of its models: another agent is another conversation, another model keeps this one
  const choose = async (body) => {
    try { info = await api.chat.settings(body); } catch (error) { notify(ctx, "Could not switch.", error.message, "error"); }
    paintPickers();
    paint();
  };
  const agentPick = selectField({ id: "chat-agent", options: [], value: "", onChange: (v) => choose({ lane: v }) });
  const modelPick = selectField({ id: "chat-model", options: [], value: "", onChange: (v) => choose({ model: v }) });
  agentPick.select.setAttribute("aria-label", "Agent (another agent starts a new chat)");
  modelPick.select.setAttribute("aria-label", "Model");
  const pickers = h("div", { class: "chat-pickers" }, agentPick.el, modelPick.el);
  function paintPickers() {
    const lanes = (info?.lanes ?? []).filter((l) => l.installed);
    agentPick.setOptions(lanes.map((l) => ({ value: l.id, label: l.open_weights ? `${l.label} · open weights` : l.label })), info?.lane?.id);
    const models = (info?.lanes ?? []).find((l) => l.id === info?.lane?.id)?.models ?? [];
    modelPick.setOptions(models, info?.choice ?? "");
    agentPick.el.hidden = lanes.length < 2;
    modelPick.el.hidden = models.length < 2;
  }
  const log = h("div", { class: "chat-log", role: "log", "aria-label": "Conversation", "aria-live": "polite" });
  const input = h("textarea", { class: "textarea chat-input", rows: "2", maxlength: "8000", "aria-label": "Message to the agent",
    placeholder: "Ask the studio: direct a shot, cut a movie, check a take…" });
  // The room before anyone has spoken: a call sheet, printed on the studio's card stock, beside the one take this room
  // actually made. The sheet asserts what can be asked, so it is printed; the take is footage, so it is emulsion; the
  // room behind both is lacquer. Nothing here is decoration -- the loop is a real take and its receipt opens.
  const suggest = h("ol", { class: "callsheet-lines" }, SUGGESTIONS.map((text) => {
    const b = h("button", { type: "button", class: "link-btn callsheet-line" }, text);
    b.addEventListener("click", () => { input.value = text; input.focus(); paint(); });
    return h("li", null, b);
  }));
  const callsheet = h("div", { class: "callsheet on-stock" },
    h("p", { class: "callsheet-head" }, "Call sheet"),
    h("p", { class: "callsheet-lede" }, "Ask in plain words. It plans, shows you, then renders."),
    suggest);
  const introMade = h("div", { class: "chat-made" });
  const intro = h("div", { class: "chat-intro" }, callsheet, introMade);
  const send = h("button", { type: "submit", class: "btn primary" }, icon("send"), h("span", null, "Send"));
  const stop = h("button", { type: "button", class: "btn secondary", hidden: true }, icon("square"), "Stop");
  const status = h("p", { class: "hint chat-status", "aria-live": "polite" });
  const compose = h("form", { class: "chat-compose" }, input, h("div", { class: "chat-actions" }, status, stop, send));
  const scroller = h("div", { class: "chat-scroll" }, intro, log);
  const off = h("div", { class: "empty chat-off", hidden: true });
  const el = h("section", { class: "chat-station", "aria-label": "Chat" },
    h("div", { class: "station-head" }, h("h1", null, "Chat"),
      h("p", { class: "hint" }, "Your agent, with the studio's tools.")),
    h("div", { class: "chat-bar" }, lane, pickers, reset), off, scroller, compose);

  const busy = () => BUSY.has(chat.state);
  const atEnd = () => scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 48;

  // -- the agent's words: paragraphs, lists, code, bold, and take ids as links ----------------------------------------
  const takeLink = (id) => {
    const a = h("a", { class: "take-link num", href: `#/takes/${id}` }, id);
    a.addEventListener("click", async (e) => {
      e.preventDefault();
      if (!store.get().takes.some((t) => t.id === id)) await controller.refreshTakes?.(); // made a moment ago
      ui.openTake(id);
    });
    return a;
  };
  const inline = (line) => pieces(line).map((p) => (p.take ? takeLink(p.take) : p.code ? h("code", null, p.code) : p.bold ? h("b", null, p.bold) : p.text));
  const blockNode = (b) => (b.list
    ? h(b.ordered ? "ol" : "ul", null, b.list.map((l) => h("li", null, inline(l))))
    : h("p", null, b.lines.flatMap((l, i) => (i ? [h("br"), ...inline(l)] : inline(l)))));
  // a block that did not change keeps its element: only the end of a message that is still arriving is drawn again
  function setWords(box, text) {
    const was = drawn.get(box);
    if (was?.text === text) return;
    const now = blocks(text);
    const keys = now.map((b) => JSON.stringify(b));
    keys.forEach((key, i) => {
      if (key === was?.keys[i]) return;
      if (box.children[i]) box.children[i].replaceWith(blockNode(now[i]));
      else box.append(blockNode(now[i]));
    });
    while (box.children.length > keys.length) box.lastChild.remove();
    drawn.set(box, { text, keys });
  }

  function setTool(node, item) {
    // drawn again only when something it shows changed: the state, the words, or what came back (a lane may report a
    // result more than once, and the words of a running call can refresh)
    const sig = `${item.state}|${item.name}|${JSON.stringify(item.input ?? {})}|${item.result?.text?.length ?? -1}|${item.result?.takes?.length ?? 0}|${item.result?.images?.length ?? 0}`;
    if (node.dataset.sig === sig) return;
    node.dataset.sig = sig;
    node.dataset.state = item.state;
    const result = item.result;
    const detail = toolDetail(item.input);
    const said = result?.text?.trim();
    node.replaceChildren(icon(TOOL_ICON[item.state] ?? "clock", "sm"),
      h("div", { class: "chat-tool-body" },
        h("b", null, toolWords(item.name, item.state !== "running")),
        detail ? h("span", { class: "chat-tool-detail" }, detail) : null,
        result?.takes?.length ? h("span", { class: "chat-tool-takes" }, result.takes.map(takeLink)) : null,
        result?.images?.length ? h("span", { class: "chat-tool-pictures" }, result.images.map((src) => h("img", { src, alt: "What the tool showed the agent", loading: "lazy", draggable: "false" }))) : null,
        said ? h("details", { class: "chat-tool-said" }, h("summary", null, item.state === "error" ? "What went wrong" : "What came back"), h("pre", null, said)) : null));
  }

  // an item's element is made once and kept; after that only what changed is drawn again
  function draw(item) {
    let node = nodes.get(item);
    if (!node) {
      node = item.kind === "tool" ? h("div", { class: "chat-tool" })
        : item.kind === "notice" ? h("p", { class: "chat-notice", "data-tone": item.tone }, item.text)
          : h("div", { class: `chat-msg ${item.kind}` }, h("div", { class: "chat-text" }));
      nodes.set(item, node);
      log.append(node);
      // what just happened settles in over 180 ms (the room's one curve); under reduced motion or Save-Data it just appears
      if (recent && !holdStill()) node.animate?.([{ opacity: 0, transform: "translateY(4px)" }, { opacity: 1, transform: "none" }], { duration: 180, easing: "cubic-bezier(0.16,1,0.3,1)" });
    }
    if (item.kind === "tool") setTool(node, item);
    else if (item.kind !== "notice") {
      node.classList.toggle("live", Boolean(item.live));
      setWords(node.firstChild, item.text);
    }
  }
  // the whole conversation again: elements stay with their items (an open "What came back" stays open); gone items leave
  function redraw() {
    const have = new Set(chat.items);
    for (const [item, node] of nodes) if (!have.has(item)) { node.remove(); nodes.delete(item); }
    for (const item of chat.items) draw(item);
  }

  // -- following the end of the conversation, until the person scrolls up -------------------------------------------------
  scroller.addEventListener("scroll", () => {
    pinned = atEnd() || (pinned && scroller.scrollTop >= lastTop);
    lastTop = scroller.scrollTop;
  }, { passive: true });
  // once a frame, and only when the end moved (a piece of text that adds no line scrolls nothing); what just happened glides there
  function follow() {
    frame ||= requestAnimationFrame(() => {
      frame = 0;
      const to = scroller.scrollHeight;
      if (pinned && scroller.clientHeight && to !== end) {
        end = to;
        scroller.scrollTo({ top: to, behavior: glide && !holdStill() ? "smooth" : "auto" });
      }
      glide = false;
    });
  }
  // back in the room (a view transition shows it a frame late), a resized window or a growing composer: a reader at the end goes back to it
  if (globalThis.ResizeObserver) new ResizeObserver(() => { if (pinned && !atEnd()) { end = 0; follow(); } }).observe(scroller);

  function onEvent(event) {
    const now = Date.now() / 1000;
    recent = now - (event.at ?? now) < 2;
    const touched = applyEvent(chat, event);
    if (event.kind === "reset") { pinned = true; lastTop = end = 0; }
    if (touched === "all") redraw();
    else if (touched) draw(touched);
    if (event.kind === "result" && event.takes?.length) controller.refreshTakes?.(); // the rooms show the new take
    if (event.kind === "turn") api.chat.info().then((next) => { info = next; paintPickers(); paint(); }).catch(() => {}); // renders left
    paint();
    if (touched) {
      glide ||= recent;
      follow();
    }
  }

  function connect() {
    if (source || !info?.enabled) return;
    const url = api.chat?.eventsUrl?.(chat.seq);
    if (!url || !globalThis.EventSource) return;
    source = new EventSource(url); // the browser reconnects by itself, from the last event it saw
    source.onmessage = (message) => {
      let event;
      try { event = JSON.parse(message.data); } catch { return; }
      onEvent(event);
    };
  }

  function paint() {
    const ready = Boolean(info?.enabled);
    off.hidden = ready || !info;
    scroller.hidden = compose.hidden = !ready;
    reset.hidden = pickers.hidden = !ready;
    intro.hidden = chat.items.length > 0;
    // nothing said yet: the sheet and its take sit in the middle of the room rather than hanging from its top rule
    scroller.classList.toggle("at-rest", !intro.hidden);
    stop.hidden = !busy() || chat.state === "stopping";
    send.disabled = !ready || busy() || !input.value.trim();
    reset.disabled = busy() || chat.items.length === 0;
    agentPick.select.disabled = modelPick.select.disabled = busy();
    setText(status, statusLine(chat));
    if (ready) {
      const left = info.renders_left ?? info.renders;
      const renders = info.renders === 0 ? "plans and reviews only, no renders" : `${left} of ${info.renders} renders left in this chat`;
      const who = `${info.lane?.label ?? "Your agent"}${info.lane?.open_weights ? " (open weights)" : ""}`;
      setText(lane, `${who} on this computer · ${chat.model ?? info.model ?? "its own default model"} · ${renders}`);
    }
  }

  // the copy of the room's own take that fills a 560px frame on this screen, or nothing when it is not on file: both
  // the call sheet's loop and the hosted card are cut from it
  function madeClip() {
    const s = store.get();
    return (s.recorded.some((r) => r.id === MADE_HERE) && previewOf(s, { id: MADE_HERE }, api, { width: 560 })) || null;
  }
  // the hosted card shows a take an open-weights agent made here, on a loop, with the way to its receipt: the copy that fills a
  // 560px frame on this screen (its case is up to 480px wide; a phone keeps the small loop)
  function madeHere() {
    const clip = madeClip();
    if (!clip) return null;
    const open = h("button", { type: "button", class: "btn secondary" }, "Open the take");
    open.addEventListener("click", () => {
      history.pushState(null, "", `#/takes/${MADE_HERE}`);
      ui.openTake(MADE_HERE);
    });
    return [h("div", { class: "empty-art" }, liveClip(clip)), h("p", null, "Made here, in the Chat room."), open];
  }
  // the call sheet's other half: the take this room made, looping beside it, with the way to its receipt. Built once
  // (a repaint must never restart the loop) and only when the take's preview is on file, so an export without it
  // simply shows the sheet alone rather than an empty frame.
  let made = null;
  function paintMade() {
    if (made) return;
    const clip = madeClip();
    if (!clip) return;
    const open = h("button", { type: "button", class: "link-btn" }, "Open its receipt");
    open.addEventListener("click", () => {
      history.pushState(null, "", `#/takes/${MADE_HERE}`);
      ui.openTake(MADE_HERE);
    });
    const frame = h("div", { class: "chat-made-frame" }, liveClip(clip));
    printKeykode(frame, { id: MADE_HERE });
    made = h("figure", { class: "chat-made-fig" }, frame,
      h("figcaption", null, h("span", null, "An agent directed this take in this room."), open));
    introMade.replaceChildren(made);
  }

  function paintOff() {
    if (!info || info.enabled) return;
    proof ??= madeHere();
    fill(off, icon("message-square", "lg"), h("h2", null, info.code === "hosted" ? "Chat runs on your computer" : "The Chat room is off here"),
      proof, h("p", null, info.message ?? ""),
      info.code === "hosted" ? h("code", { class: "chat-install" }, ...stepSpans(cloneLine(repoUrl))) : null);
  }
  // on a phone the command wraps between its && steps and inside the long clone address, never inside a flag like -e
  function stepSpans(line) {
    return line.split(" && ").flatMap((step, i) => (i ? [" && ", h("span", { class: "chat-install-step" }, step)] : [step]));
  }

  async function load() {
    try {
      info = await api.chat.info();
    } catch (error) {
      info = { enabled: false, code: "unreachable", message: `The studio did not answer: ${error.message}` };
    }
    paintOff();
    paintPickers();
    paint();
    connect();
  }

  // the install line names the repository the hosted copy was built from, when the site says which one
  Promise.resolve(api.site?.()).then((site) => { repoUrl = site?.repo_url ?? null; paintOff(); }).catch(() => {});

  compose.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || busy() || !info?.enabled) return;
    send.disabled = true;
    try {
      await api.chat.send(text);
      input.value = "";
    } catch (error) {
      notify(ctx, "The agent did not take that message.", error.message, "error");
    }
    paint();
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      compose.requestSubmit();
    }
  });
  input.addEventListener("input", paint);
  stop.addEventListener("click", () => api.chat.stop().catch((error) => notify(ctx, "Could not stop the agent.", error.message, "error")));
  reset.addEventListener("click", () => api.chat.reset().catch((error) => notify(ctx, "Could not start a new chat.", error.message, "error")));

  // the room asks for its agent the first time it is opened, and then keeps following the conversation
  let opened = false;
  const open = () => {
    if (opened || store.get().route !== "chat") return;
    opened = true;
    load();
  };
  store.subscribe((_, changed) => {
    if (changed.includes("route")) open();
    if (changed.includes("previews") || changed.includes("recorded")) { paintOff(); paintMade(); } // the room's own take is ready
  });
  open();
  paintMade();
  paint();
  return { el };
}
