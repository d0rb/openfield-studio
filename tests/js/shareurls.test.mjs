import test from "node:test";
import assert from "node:assert/strict";

import { sharePageUrl, shareTargets } from "../../openfield/web/js/lib/shareurls.js";

const LINK = "https://openfield.example/#/takes/tk_1";
const CAPTION = "Mara on the pier: Orbit 90";

test("every target names itself and carries the caption and the take's page", () => {
  const targets = shareTargets({ url: LINK, text: CAPTION });
  assert.deepEqual(targets.map((t) => t.id), ["x", "reddit", "linkedin", "whatsapp", "telegram"]);
  assert.deepEqual(targets.map((t) => t.label), ["X", "Reddit", "LinkedIn", "WhatsApp", "Telegram"]);
  const u = "https%3A%2F%2Fopenfield.example%2F%23%2Ftakes%2Ftk_1";
  const t = "Mara%20on%20the%20pier%3A%20Orbit%2090";
  assert.equal(targets[0].href, `https://x.com/intent/post?text=${t}&url=${u}`);
  assert.equal(targets[1].href, `https://www.reddit.com/submit?url=${u}&title=${t}`);
  assert.equal(targets[2].href, `https://www.linkedin.com/sharing/share-offsite/?url=${u}`);
  assert.equal(targets[3].href, `https://wa.me/?text=${t}%20${u}`);
  assert.equal(targets[4].href, `https://t.me/share/url?url=${u}&text=${t}`);
});

test("a caption with an ampersand, a hashtag, spaces and an emoji does not break the link", () => {
  const text = "Mara & the pier 🎬 #hashtag";
  const url = "https://openfield.example/t/tk 1?a=1&b=2#top";
  const [x, reddit, , whatsapp, telegram] = shareTargets({ url, text });
  const t = "Mara%20%26%20the%20pier%20%F0%9F%8E%AC%20%23hashtag";
  const u = "https%3A%2F%2Fopenfield.example%2Ft%2Ftk%201%3Fa%3D1%26b%3D2%23top";
  assert.equal(x.href, `https://x.com/intent/post?text=${t}&url=${u}`);
  assert.equal(reddit.href, `https://www.reddit.com/submit?url=${u}&title=${t}`);
  assert.equal(whatsapp.href, `https://wa.me/?text=${t}%20${u}`);
  assert.equal(telegram.href, `https://t.me/share/url?url=${u}&text=${t}`);
  for (const target of [x, reddit, whatsapp, telegram]) assert.ok(!/[#\s]/.test(target.href), target.href);
});

test("the hosted copy points at the take's own page, beside index.html", () => {
  assert.equal(sharePageUrl("tk_1", { isStatic: true, href: "https://u.github.io/repo/#/lobby" }), "https://u.github.io/repo/t/tk_1.html");
  assert.equal(sharePageUrl("tk_1", { isStatic: true, href: "https://u.github.io/repo/index.html?x#y" }), "https://u.github.io/repo/t/tk_1.html");
});

test("the live app points at the take's own link", () => {
  assert.equal(sharePageUrl("tk_1", { href: "http://localhost:8000/#/lobby" }), "http://localhost:8000/#/takes/tk_1");
  assert.equal(sharePageUrl("tk_1", { href: "http://localhost:8000/studio/index.html" }), "http://localhost:8000/studio/index.html#/takes/tk_1");
});
