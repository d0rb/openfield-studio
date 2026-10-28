// The Chat room's logic, free of the page so it can be tested: the studio's chat events become the conversation the
// room draws (the person's lines, the agent's words as they arrive, each studio tool it used and what came back), and a
// line of the agent's text becomes pieces, with take ids as links and `code` as code.

const TAKE = /tk_\d{8}_\d{6}_[0-9a-f]{4}/g;

/** Each studio tool in the room's words: [while it runs, once it is back]. */
const TOOL_WORDS = {
  studio_status: ["Checking the studio", "Checked the studio"],
  read_guide: ["Reading the prompting guide", "Read the prompting guide"],
  list_options: ["Looking at the moves and looks", "Looked at the moves and looks"],
  list_cast: ["Looking at the cast", "Looked at the cast"],
  create_character: ["Inventing a character", "Invented a character"],
  add_character: ["Adding to the cast", "Added to the cast"],
  plan_shot: ["Planning the shot", "Planned the shot"],
  direct_shot: ["Starting a shot", "Started a shot"],
  wait_for_take: ["Waiting for the take", "Looked at the take"],
  approve_stills: ["Approving the stills", "Approved the stills"],
  edit_take: ["Editing a still", "Started the edit"],
  shots_board: ["Shooting nine setups", "Started the nine setups"],
  transition: ["Bridging two takes", "Started the transition"],
  extend_take: ["Extending the take", "Started the extension"],
  dub_take: ["Dubbing the take", "Started the dub"],
  upscale_take: ["Upscaling the take", "Started the upscale"],
  reshoot_video: ["Re-shooting a clip", "Started the re-shoot"],
  make_movie: ["Cutting the movie", "Cut the movie"],
  export_vertical: ["Exporting 9:16", "Exported 9:16"],
  list_takes: ["Looking at the takes", "Looked at the takes"],
  replay_take: ["Playing back a recording", "Started the playback"],
  get_receipt: ["Reading a receipt", "Read the receipt"],
  save_take: ["Saving a file", "Saved a file"],
  cancel_take: ["Cancelling a take", "Cancelled the take"],
};

export const toolWords = (name, done) => (TOOL_WORDS[name] ?? [`Using ${name}`, `Used ${name}`])[done ? 1 : 0];

/** One short line about what the tool was asked: the shot's subject, the edit's words, the take it works on. */
export function toolDetail(input = {}) {
  const pick = input.subject ?? input.idea ?? input.instruction ?? input.words ?? input.line ?? input.prompt ?? input.description
    ?? input.take_id ?? input.section ?? "";
  const text = String(pick).replace(/\s+/g, " ").trim();
  return text.length > 96 ? `${text.slice(0, 95)}…` : text;
}

/** A fresh conversation. */
export const newChat = () => ({ items: [], state: "idle", model: null, seq: 0 });

/**
 * Apply one event from the studio's chat stream (in order). Returns the item it touched (to redraw), "all" when the
 * whole conversation changed (a new chat, or a turn that ended) or null. An event for an id already held changes that
 * item in place and keeps what it does not carry. Replaying the same events always builds the same conversation.
 */
/** Nothing is still arriving: live messages settle, and a call that never answered says so. True when anything changed. */
function settleAll(chat) {
  let changed = false;
  for (const it of chat.items) {
    if (it.kind === "agent" && it.live) { it.live = false; changed = true; }
    if (it.kind === "tool" && it.state === "running") {
      it.state = "error";
      it.result = { text: "No answer came back: the turn ended first.", images: [], takes: [] };
      changed = true;
    }
  }
  return changed;
}

export function applyEvent(chat, event) {
  if (!event || typeof event !== "object") return null;
  if (event.seq <= chat.seq && event.kind !== "reset") return null; // seen already (a reconnect replays)
  chat.seq = Math.max(chat.seq, event.seq ?? 0);
  const find = (kind, id) => chat.items.find((it) => it.kind === kind && it.id === id);
  switch (event.kind) {
    case "reset":
      chat.items = [];
      chat.state = "idle";
      chat.model = null;
      return "all";
    case "user": {
      let item = event.id == null ? null : find("user", event.id);
      if (item) item.text = event.text;
      else chat.items.push((item = { kind: "user", id: event.id, text: event.text }));
      return item;
    }
    case "delta": {
      let item = find("agent", event.id);
      if (!item) chat.items.push((item = { kind: "agent", id: event.id, text: "", live: true }));
      item.text += event.text;
      item.live = true; // a message id a later turn uses again is live again
      return item;
    }
    case "text": {
      let item = find("agent", event.id);
      if (!item) chat.items.push((item = { kind: "agent", id: event.id, text: "" }));
      item.text = event.text;
      item.live = false;
      return item;
    }
    case "tool": {
      let item = event.id == null ? null : find("tool", event.id);
      if (item) { // the same call again: its words refresh, what came back stays
        item.name = event.name ?? item.name;
        item.input = event.input ?? item.input;
      } else chat.items.push((item = { kind: "tool", id: event.id, name: event.name, input: event.input ?? {}, state: "running", result: null }));
      return item;
    }
    case "result": {
      const item = find("tool", event.id);
      if (!item) return null;
      item.state = event.error ? "error" : "done";
      item.result = { text: event.text ?? "", images: event.images ?? [], takes: event.takes ?? [] };
      return item;
    }
    case "status":
      chat.state = event.state;
      // idle means nothing is still arriving, even when no turn event came (an agent that died mid-sentence, an overdue Stop)
      return event.state === "idle" && settleAll(chat) ? "all" : null;
    case "ready":
      chat.model = event.model ?? chat.model;
      return null;
    case "turn": {
      settleAll(chat); // however it ended, nothing is still arriving, and a call still running never will
      if (event.error || event.stopped) {
        chat.items.push({ kind: "notice", tone: event.error ? "error" : "info",
          text: event.stopped ? "Stopped." : event.text || "The agent could not finish that." });
      }
      return "all"; // the live messages settle, and a notice may be new
    }
    case "notice":
    case "error": {
      const item = { kind: "notice", tone: event.kind === "error" ? "error" : "info", text: event.text ?? "" };
      chat.items.push(item);
      return item;
    }
    default:
      return null;
  }
}

/** What the room says it is doing now. */
export function statusLine(chat) {
  if (chat.state === "starting") return "Starting the agent…";
  if (chat.state === "stopping") return "Stopping…";
  if (chat.state !== "busy") return "";
  const running = [...chat.items].reverse().find((it) => it.kind === "tool" && it.state === "running");
  return running ? `${toolWords(running.name, false)}…` : "Thinking…";
}

/** A line of the agent's text as pieces: plain text, `code`, **bold**, and take ids (each a link in the room). */
export function pieces(line) {
  const out = [];
  const pattern = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(tk_\d{8}_\d{6}_[0-9a-f]{4})/g;
  let at = 0;
  for (const m of line.matchAll(pattern)) {
    if (m.index > at) out.push({ text: line.slice(at, m.index) });
    if (m[1]) out.push({ code: m[1].slice(1, -1) });
    else if (m[2]) out.push({ bold: m[2].slice(2, -2) });
    else out.push({ take: m[3] });
    at = m.index + m[0].length;
  }
  if (at < line.length) out.push({ text: line.slice(at) });
  return out;
}

/** The agent's text as blocks: paragraphs (lines kept) and lists ("- " or "1. " lines), the shapes chat text takes. */
export function blocks(text) {
  const out = [];
  for (const chunk of String(text ?? "").replace(/\r/g, "").split(/\n{2,}/)) {
    const lines = chunk.split("\n").filter((l) => l.trim());
    if (!lines.length) continue;
    const listy = lines.every((l) => /^\s*(?:[-*•]|\d+[.)])\s+/.test(l));
    if (listy) out.push({ list: lines.map((l) => l.replace(/^\s*(?:[-*•]|\d+[.)])\s+/, "")), ordered: /^\s*\d/.test(lines[0]) });
    else out.push({ lines: lines.map((l) => l.replace(/^#{1,6}\s+/, "")) });
  }
  return out;
}

/** Every take id a text names, once each. */
export const takesIn = (text) => [...new Set(String(text ?? "").match(TAKE) ?? [])];
