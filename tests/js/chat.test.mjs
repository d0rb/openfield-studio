// The Chat room's logic: events become the conversation, a reconnect replays nothing twice, a turn that ends settles every
// message (and the room keeps each item's element), and the agent's text becomes paragraphs, lists, code and take links.
import test from "node:test";
import assert from "node:assert/strict";

import { applyEvent, blocks, newChat, pieces, statusLine, takesIn, toolDetail, toolWords } from "../../openfield/web/js/lib/chat.js";

const TAKE = "tk_20261025_120000_abcd";
const play = (events, chat = newChat()) => { for (const e of events) applyEvent(chat, e); return chat; };
const conversation = [
  { seq: 1, kind: "status", state: "starting" },
  { seq: 2, kind: "user", id: "u1", text: "shoot a lighthouse" },
  { seq: 3, kind: "ready", model: "claude-opus-5" },
  { seq: 4, kind: "status", state: "busy" },
  { seq: 5, kind: "delta", id: "m1.1", text: "I'll start " },
  { seq: 6, kind: "delta", id: "m1.1", text: "the shot." },
  { seq: 7, kind: "text", id: "m1.1", text: "I'll start the shot." },
  { seq: 8, kind: "tool", id: "t1", name: "direct_shot", input: { subject: "A lighthouse at dusk" } },
  { seq: 9, kind: "result", id: "t1", text: `Started ${TAKE}.`, images: ["data:image/jpeg;base64,QUJD"], takes: [TAKE] },
  { seq: 10, kind: "text", id: "m2.1", text: `Started ${TAKE}: the stills come first.` },
  { seq: 11, kind: "turn", ms: 900 },
  { seq: 12, kind: "status", state: "idle" },
];

test("a conversation becomes the person's line, the agent's words, and the tool it used with what came back", () => {
  const chat = play(conversation);
  assert.deepEqual(chat.items.map((i) => i.kind), ["user", "agent", "tool", "agent"]);
  assert.equal(chat.items[1].text, "I'll start the shot.");
  assert.equal(chat.items[1].live, false);
  assert.equal(chat.items[2].state, "done");
  assert.deepEqual(chat.items[2].result.takes, [TAKE]);
  assert.equal(chat.model, "claude-opus-5");
  assert.equal(chat.state, "idle");
  assert.equal(statusLine(chat), "");
});

test("the agent's words grow piece by piece and the whole text replaces them", () => {
  const chat = play(conversation.slice(0, 6));
  assert.equal(chat.items[1].text, "I'll start the shot.");
  assert.equal(chat.items[1].live, true);
  assert.equal(statusLine(chat), "Thinking…");
  applyEvent(chat, { seq: 7, kind: "text", id: "m1.1", text: "I'll start the shot!" });
  assert.equal(chat.items[1].text, "I'll start the shot!");
});

test("a reconnect replays events the room has seen: nothing is drawn twice", () => {
  const chat = play(conversation);
  for (const e of conversation) assert.equal(applyEvent(chat, e), null);
  assert.equal(chat.items.length, 4);
});

test("the status line names the tool that is running", () => {
  const chat = play(conversation.slice(0, 8));
  assert.equal(statusLine(chat), "Starting a shot…");
  assert.equal(statusLine(play([{ seq: 1, kind: "status", state: "starting" }])), "Starting the agent…");
});

test("a stopped turn and an agent error each leave one plain line", () => {
  const stopped = play([...conversation.slice(0, 6), { seq: 7, kind: "turn", stopped: true }]);
  assert.equal(stopped.items.at(-1).text, "Stopped.");
  assert.equal(stopped.items.find((i) => i.kind === "agent").live, false);
  const failed = play([{ seq: 1, kind: "turn", error: true, text: "rate limited" }]);
  assert.deepEqual(failed.items.at(-1), { kind: "notice", tone: "error", text: "rate limited" });
});

test("New chat clears the conversation", () => {
  const chat = play(conversation);
  assert.equal(applyEvent(chat, { seq: 13, kind: "reset" }), "all");
  assert.deepEqual(chat.items, []);
  assert.equal(chat.model, null);
});

test("a tool's answer that failed marks the tool, and an answer for no tool is ignored", () => {
  const chat = play([{ seq: 1, kind: "tool", id: "t", name: "approve_stills", input: { take_id: TAKE } }, { seq: 2, kind: "result", id: "t", error: true, text: "Not waiting for approval." }]);
  assert.equal(chat.items[0].state, "error");
  assert.equal(applyEvent(chat, { seq: 3, kind: "result", id: "nope", text: "?" }), null);
});

test("tools are named in the room's words, with what they were asked", () => {
  assert.equal(toolWords("direct_shot", false), "Starting a shot");
  assert.equal(toolWords("direct_shot", true), "Started a shot");
  assert.equal(toolWords("brand_new_tool", false), "Using brand_new_tool");
  assert.equal(toolDetail({ subject: "  A lighthouse\nat dusk " }), "A lighthouse at dusk");
  assert.equal(toolDetail({ take_id: TAKE }), TAKE);
  assert.equal(toolDetail({ subject: "x".repeat(200) }).length, 96);
  assert.equal(toolDetail({}), "");
});

test("a line becomes text, code, bold and take links", () => {
  assert.deepEqual(pieces(`Open \`list_takes\` then **check** ${TAKE}.`), [
    { text: "Open " }, { code: "list_takes" }, { text: " then " }, { bold: "check" }, { text: " " }, { take: TAKE }, { text: "." },
  ]);
  assert.deepEqual(pieces("plain"), [{ text: "plain" }]);
  assert.deepEqual(takesIn(`${TAKE} and ${TAKE} and tk_20261025_120001_beef`), [TAKE, "tk_20261025_120001_beef"]);
});

test("the agent's text becomes paragraphs and lists", () => {
  assert.deepEqual(blocks("## Plan\nTwo lines\nhere\n\n- one\n- two\n\n1. first\n2. second"), [
    { lines: ["Plan", "Two lines", "here"] },
    { list: ["one", "two"], ordered: false },
    { list: ["first", "second"], ordered: true },
  ]);
  assert.deepEqual(blocks(""), []);
});

// -- streaming: what the room redraws and keeps ------------------------------------------------------------------------
const sameObjects = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);

test("after a turn event no item is live, however the turn ended", () => {
  const arriving = [
    ...conversation.slice(0, 6),
    { seq: 7, kind: "delta", id: "m1.2", text: "A second message, " },
  ];
  for (const end of [{ kind: "turn", ms: 900 }, { kind: "turn", error: true, text: "rate limited" }, { kind: "turn", stopped: true }]) {
    const chat = play(arriving);
    assert.deepEqual(chat.items.filter((i) => i.kind === "agent").map((i) => i.live), [true, true], "both are still arriving");
    const before = [...chat.items];
    assert.equal(applyEvent(chat, { seq: 8, ...end }), "all", "the room is told to settle the whole conversation");
    assert.equal(chat.items.filter((i) => i.live).length, 0, `${JSON.stringify(end)} left a message live`);
    assert.ok(sameObjects(chat.items.slice(0, before.length), before), "every item is the same object: the room keeps its element");
    assert.equal(chat.items.length, before.length + (end.error || end.stopped ? 1 : 0), "an error or a stop adds its one plain line");
  }
});

test("a delta appends text to the right item", () => {
  const chat = play([
    { seq: 1, kind: "delta", id: "a.1", text: "one " },
    { seq: 2, kind: "delta", id: "b.1", text: "two " },
    { seq: 3, kind: "tool", id: "a.1", name: "list_takes", input: {} }, // the same id as the first message, but a tool
    { seq: 4, kind: "delta", id: "a.1", text: "more" },
  ]);
  const [first, second, tool] = chat.items;
  assert.equal(chat.items.length, 3);
  assert.deepEqual([first.text, second.text], ["one more", "two "]);
  assert.equal(tool.kind, "tool");
  assert.equal("text" in tool, false, "the tool did not take the words");
  assert.equal(applyEvent(chat, { seq: 5, kind: "delta", id: "b.1", text: "words" }), second, "the item it grew is the one it returns");
  assert.equal(second.text, "two words");
  assert.equal(first.text, "one more");
  assert.deepEqual([first.live, second.live], [true, true]);
});

test("an all payload merges by id and keeps what the room alone knows", () => {
  const chat = play(conversation);
  const held = [...chat.items];
  held[1].mine = "kept"; // what the room knows about an item that the studio never says
  held[2].opened = true;
  // the whole conversation again, as the studio keeps it (its pieces already folded into the whole text), under new numbers
  const again = conversation.filter((e) => e.kind !== "delta").map((e, i) => ({ ...e, seq: 100 + i }));
  for (const event of again) applyEvent(chat, event);
  assert.equal(chat.items.length, 4, "no item is drawn twice");
  assert.ok(sameObjects(chat.items, held), "each item is merged into the one the room holds");
  assert.deepEqual([held[1].mine, held[2].opened], ["kept", true]);
  assert.equal(held[0].text, "shoot a lighthouse");
  assert.equal(held[1].text, "I'll start the shot.");
  assert.equal(held[1].live, false);
  assert.equal(held[2].name, "direct_shot", "what came back does not carry the tool's name");
  assert.deepEqual(held[2].input, { subject: "A lighthouse at dusk" });
  assert.equal(held[2].state, "done", "the same call again does not make it run again");
  assert.deepEqual(held[2].result.takes, [TAKE]);
  assert.equal(chat.seq, 100 + again.length - 1);
});

test("an event with no id is never folded into another item", () => {
  const chat = play([
    { seq: 1, kind: "tool", name: "list_cast", input: {} },
    { seq: 2, kind: "tool", name: "list_takes", input: {} },
    { seq: 3, kind: "user", text: "one" },
    { seq: 4, kind: "user", text: "two" },
  ]);
  assert.deepEqual(chat.items.map((i) => i.name ?? i.text), ["list_cast", "list_takes", "one", "two"]);
});
