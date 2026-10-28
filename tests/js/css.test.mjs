import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// Plain reads of the stylesheets: the traps that only show in the cascade, and the rule that nothing glows.

const SHEETS = ["tokens", "components", "layout", "stations", "lobby"];
const read = (name) => readFileSync(new URL(`../../openfield/web/css/${name}.css`, import.meta.url), "utf8");
const web = (path) => readFileSync(new URL(`../../openfield/web/${path}`, import.meta.url), "utf8");

/** A sheet with its comments blanked (newlines kept, so line numbers hold): a rule named in a comment is not a rule. */
const bare = (text) => text.replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, " "));

/** Every style rule as { selector, body, line }. @media, @container, @supports and @starting-style are looked through;
    keyframes and font faces hold no rules of the page's own. */
function rules(text) {
  const src = bare(text);
  const out = [];
  const lineAt = (index) => src.slice(0, index).split("\n").length;
  const walk = (from, to) => {
    let i = from;
    while (i < to) {
      const open = src.indexOf("{", i);
      if (open < 0 || open >= to) break;
      let depth = 1;
      let j = open + 1;
      while (j < to && depth) { if (src[j] === "{") depth += 1; else if (src[j] === "}") depth -= 1; j += 1; }
      const head = src.slice(i, open).trim();
      if (head.startsWith("@")) { if (!/^@(keyframes|font-face)/.test(head)) walk(open + 1, j - 1); } else out.push({ selector: head, body: src.slice(open + 1, j - 1), line: lineAt(open) });
      i = j;
    }
  };
  walk(0, src.length);
  return out;
}

/** A selector list as its parts: commas inside :is() and friends do not split it. */
const parts = (selector) => selector.split(/,(?![^(]*\))/).map((s) => s.trim()).filter(Boolean);

/** The custom properties of tokens.css, so a shadow written as var(--x) is read as what it is. */
function tokens() {
  return Object.fromEntries([...bare(read("tokens")).matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
}
const resolve = (value, vars) => { let v = value; for (let i = 0; i < 5 && v.includes("var("); i += 1) v = v.replace(/var\((--[\w-]+)\)/g, (_, name) => vars[name] ?? `var(${name})`); return v; };

/** One box-shadow value as its layers: colour, offsets, blur and spread in px (commas inside rgb() do not split it). */
function shadowLayers(value) {
  const layers = [];
  let depth = 0;
  let at = 0;
  for (let i = 0; i < value.length; i += 1) {
    if (value[i] === "(") depth += 1;
    else if (value[i] === ")") depth -= 1;
    else if (value[i] === "," && !depth) { layers.push(value.slice(at, i)); at = i + 1; }
  }
  layers.push(value.slice(at));
  return layers.map((l) => l.trim()).filter((l) => l && l !== "none").map((raw) => {
    const colour = /(?:rgba?|hsla?)\([^)]*\)|#[0-9a-f]{3,8}\b/i.exec(raw)?.[0] ?? null;
    const lengths = [...raw.replace(colour ?? "", " ").matchAll(/(-?(?:\d+\.?\d*|\.\d+))(px|rem|em)?(?![\w.])/g)].map((m) => Number(m[1]) * (m[2] ? (m[2] === "px" ? 1 : 16) : 1));
    const [x = 0, y = 0, blur = 0, spread = 0] = lengths;
    return { raw, colour, x, y, blur, spread, unread: raw.includes("var(") };
  });
}

/** Black or near it (every channel 12 or under), as the printed shadows are: rgb(0 0 0 / .85), rgb(5 4 3 / .7). */
function isBlack(colour) {
  if (!colour) return false;
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})(?:[0-9a-f]{2})?$/i.exec(colour);
  const channels = hex
    ? [0, 1, 2].map((i) => parseInt(hex[1].length === 3 ? hex[1][i] + hex[1][i] : hex[1].slice(2 * i, 2 * i + 2), 16))
    : (/\(([^)]*)\)/.exec(colour)?.[1] ?? "").split(/[\s,/]+/).slice(0, 3).map(Number);
  return channels.length === 3 && channels.every((c) => c <= 12);
}

// What the files do today, and so what the guard allows: the rail's warm light is two small blurs (8px and 16px); every
// other shadow on a card is a black drop shadow pulled in by a negative spread, so a long blur never shows round the card.
// A halo is a blur past 24px that is not that: a glow of any colour, or a black blur spread out round the object.
const BLUR_LIMIT = 24;
const FAMILIES = /\.(?:rail-item|btn|card|[\w-]+-card)(?![\w-])/; // the rail's items, buttons, and cards (.card, .show-card, .lobby-card, ...)

/** The halos in some sheets, as lines of text: any backdrop-filter, and a shadow on a rail item, button or card that glows. */
function haloProblems(sheets, vars) {
  const found = [];
  for (const { name, text } of sheets) {
    for (const { selector, body, line } of rules(text)) {
      if (/backdrop-filter\s*:/.test(body)) found.push(`${name}.css:${line} ${selector}: backdrop-filter (no glass)`); // the -webkit- twin ends the same way
      if (!parts(selector).some((p) => FAMILIES.test(p))) continue;
      for (const m of body.matchAll(/box-shadow\s*:\s*([^;]+);/g)) {
        for (const layer of shadowLayers(resolve(m[1].trim(), vars))) {
          if (layer.unread) found.push(`${name}.css:${line} ${selector}: cannot read the shadow "${layer.raw}" (define its token in tokens.css)`);
          else if (layer.blur > BLUR_LIMIT && !(isBlack(layer.colour) && layer.spread < 0)) found.push(`${name}.css:${line} ${selector}: a ${layer.blur}px blur that is not a printed drop shadow ("${layer.raw}")`);
        }
      }
    }
  }
  return found;
}

/** Where a rule carries `view-transition-name: stage` without every one of its selectors naming .room-swap. */
function permanentStageNames(sheets) {
  const found = [];
  for (const { name, text } of sheets) {
    for (const { selector, body, line } of rules(text)) {
      if (!/view-transition-name\s*:\s*stage(?![\w-])/.test(body)) continue;
      if (!parts(selector).every((p) => p.includes(".room-swap"))) found.push(`${name}.css:${line} ${selector}`);
    }
  }
  return found;
}

const sheets = () => SHEETS.map((name) => ({ name, text: read(name) }));
const ruleOf = (name, selector) => rules(read(name)).find((r) => parts(r.selector).includes(selector));

test("no line of lobby.css starts with .move-grid: it would reach the Move Pad in Direct, which has a .move-grid of its own", () => {
  const loose = bare(read("lobby")).split("\n").map((line, i) => [i + 1, line.trim()]).filter(([, line]) => line.startsWith(".move-grid"));
  assert.deepEqual(loose, [], "lobby.css loads after stations.css: write .lobby .move-grid");
  const columns = rules(read("lobby")).filter((r) => parts(r.selector).includes(".lobby .move-grid") && /grid-template-columns/.test(r.body));
  assert.ok(columns.length >= 1, "the Lobby's gallery still has its columns, under .lobby");
  assert.match(ruleOf("stations", ".move-grid").body, /gap:\s*6px/, "the Move Pad keeps its 6px gap");
});

test("the stage carries a view-transition name only under .room-swap, so a rail-mark slide never takes the stage with it", () => {
  assert.deepEqual(permanentStageNames(sheets()), [], "view-transition-name: stage belongs to a rule whose selectors all name .room-swap");
  // the check sees what it should
  const css = (text) => [{ name: "sample", text }];
  assert.equal(permanentStageNames(css(".room-swap .stage { view-transition-name: stage; }")).length, 0);
  assert.equal(permanentStageNames(css(":root.room-swap .stage { view-transition-name: stage; }")).length, 0);
  assert.equal(permanentStageNames(css("@supports (view-transition-name: stage) { .room-swap .stage { view-transition-name: stage; } }")).length, 0);
  assert.equal(permanentStageNames(css(".stage { view-transition-name: stage; }")).length, 1);
  assert.equal(permanentStageNames(css(".stage, .room-swap .stage { view-transition-name: stage; }")).length, 1);
  assert.equal(permanentStageNames(css("/* .stage { view-transition-name: stage; } */ .stage { view-transition-name: none; }")).length, 0);
});

test("a sheet's exit is in the stylesheet: the scrim and its sheet fade, a carried sheet does not rise, a menu leaves upward", () => {
  const scrim = ruleOf("stations", ".sheet-scrim.leaving");
  assert.ok(scrim, ".sheet-scrim.leaving is in stations.css");
  assert.match(scrim.body, /opacity:\s*0\b/);
  const sheet = ruleOf("stations", ".sheet-scrim.leaving .sheet");
  assert.ok(sheet, ".sheet-scrim.leaving .sheet is in stations.css");
  assert.match(sheet.body, /opacity:\s*0\b/);
  assert.match(sheet.body, /translate:\s*0 8px/, "the sheet drops the 8px it rose");
  const carried = ruleOf("stations", ".sheet-scrim.carried .sheet");
  assert.ok(carried, "a carried page is told not to rise");
  assert.match(carried.body, /translate:\s*(none|0)\b/);
  const menu = ruleOf("stations", ".menu.leaving") ?? ruleOf("components", ".menu.leaving");
  assert.ok(menu, ".menu.leaving is in the stylesheet (shell.js lets the backend menu leave)");
  assert.match(menu.body, /opacity:\s*0\b/);
  assert.match(menu.body, /pointer-events:\s*none/, "a menu on its way out answers nothing");
});

test("the name the move page flies under is the one the script sets and the stylesheet styles", () => {
  const script = web("js/ui/movesheet.js");
  assert.match(script, /view-transition-name/, "movesheet.js sets a view-transition-name");
  assert.match(script, /["']move-frame["']/, "and it is move-frame, on the card's frame and on the page's");
  assert.match(web("js/ui/sheet.js"), /\bcarried\b/, "openSheet takes carried");
  const lobby = bare(read("lobby"));
  assert.ok(lobby.includes("::view-transition-group(move-frame)"), "lobby.css times the flight");
  assert.ok(lobby.includes("::view-transition-old(move-frame)") && lobby.includes("::view-transition-new(move-frame)"), "and crops both pictures to the frame");
});

test("nothing glows: no backdrop-filter anywhere, and no halo round a rail item, a button or a card", () => {
  const problems = haloProblems(sheets(), tokens());
  assert.deepEqual(problems, [], "light is a screen-blended render, not a CSS glow (DESIGN.md)");
});

test("the halo guard sees a glow, a glass pane and an unreadable shadow, and lets the printed shadows and the rail's light through", () => {
  const vars = { "--float": "0 12px 28px rgb(0 0 0 / 0.55), 0 2px 6px rgb(0 0 0 / 0.4)" };
  const found = (text) => haloProblems([{ name: "sample", text }], vars).length;
  assert.equal(found(".btn:hover { box-shadow: 0 0 40px rgb(255 122 26 / 0.5); }"), 1, "an orange glow");
  assert.equal(found(".show-card:hover { box-shadow: 0 0 30px 4px #fff; }"), 1, "a white one");
  assert.equal(found(".card { box-shadow: 0 0 60px rgb(0 0 0 / 0.8); }"), 1, "a black blur spread round the card");
  assert.equal(found(".card { box-shadow: var(--float); }"), 1, "the float shadow, which is a panel's, not a card's");
  assert.equal(found(".rail-item { box-shadow: 0 0 20px var(--nowhere); }"), 1, "a token nobody defined");
  assert.equal(found(".btn { backdrop-filter: blur(8px); }"), 1, "glass");
  assert.equal(found(".panel { -webkit-backdrop-filter: blur(8px); }"), 1, "glass anywhere");
  assert.equal(found(".lobby-card:hover { box-shadow: 0 30px 44px -16px rgb(0 0 0 / 0.85), 0 8px 14px -6px rgb(0 0 0 / 0.6); }"), 0, "a printed drop shadow");
  assert.equal(found(".rail-item:hover::before { box-shadow: 0 14px 8px 6px rgb(255 122 26 / 0.16), 0 17px 16px 10px rgb(255 122 26 / 0.16); }"), 0, "the rail's warm light is small blurs");
  assert.equal(found(".btn.primary:focus-visible { box-shadow: inset 0 0 0 2px #141311; }"), 0, "an inset edge");
  assert.equal(found(".sheet { box-shadow: var(--float); }"), 0, "a floating panel is not on the list");
});
