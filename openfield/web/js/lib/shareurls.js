// The links a take travels with: the social intents a person can open, and the page a share points at.
// Pure, so it runs in Node as well as in the browser: nothing here touches the DOM.

import { takeLink } from "./route.js";

/** The href as a URL, or null when it cannot be read (a relative link with no page to resolve it against). */
const asUrl = (href) => {
  if (!href) return null;
  try {
    return new URL(href, globalThis.location?.href);
  } catch {
    return null;
  }
};

/**
 * The places a take can be sent to, in the order the sheet lists them.
 * Every value is encoded: a caption with a space, an ampersand or a hashtag in it must not break the link.
 *
 * @param {object} options
 * @param {string} options.url the page the take is on
 * @param {string} options.text the caption that travels with it
 * @returns {Array<{ id: string, label: string, href: string }>} the targets, ready to draw
 */
export function shareTargets({ url = "", text = "" } = {}) {
  const u = encodeURIComponent(url);
  const t = encodeURIComponent(text);
  return [
    { id: "x", label: "X", href: `https://x.com/intent/post?text=${t}&url=${u}` },
    { id: "reddit", label: "Reddit", href: `https://www.reddit.com/submit?url=${u}&title=${t}` },
    { id: "linkedin", label: "LinkedIn", href: `https://www.linkedin.com/sharing/share-offsite/?url=${u}` },
    { id: "whatsapp", label: "WhatsApp", href: `https://wa.me/?text=${encodeURIComponent(`${text} ${url}`)}` },
    { id: "telegram", label: "Telegram", href: `https://t.me/share/url?url=${u}&text=${t}` },
  ];
}

/**
 * The page a share points at: the take's own link on the live app, its own page on the hosted copy
 * (the export writes one page per take, at `t/<id>.html` beside index.html).
 *
 * @param {string} takeId the take that is shared
 * @param {object} options
 * @param {boolean} [options.isStatic] the hosted copy, where every take has a page of its own
 * @param {string} [options.href] the page the app is on, which the link is resolved against
 * @returns {string} the link to share
 */
export function sharePageUrl(takeId, { isStatic = false, href = "" } = {}) {
  const url = asUrl(href);
  if (!isStatic) return takeLink(takeId, url ? { origin: url.origin, pathname: url.pathname } : {});
  if (!url) return `t/${takeId}.html`; // no page to resolve against: the link stays relative to this one
  const path = url.pathname.replace(/[^/]*$/, `t/${takeId}.html`); // the last segment of the path is the page itself
  return `${url.origin}${path}`;
}

/**
 * The page a camera move is shared at: the move's own page on the hosted copy (the export writes one per move that has a
 * recorded take, at `m/<id>.html`), else the Lobby with the move open (`#/lobby/<id>`).
 *
 * @param {string} moveId the move that is shared
 * @param {object} options
 * @param {boolean} [options.isStatic] the hosted copy, where every move with a take has a page of its own
 * @param {string} [options.href] the page the app is on, which the link is resolved against
 * @returns {string} the link to share
 */
export function movePageUrl(moveId, { isStatic = false, href = "" } = {}) {
  const url = asUrl(href);
  if (!url) return isStatic ? `m/${moveId}.html` : `#/lobby/${moveId}`;
  const page = url.pathname.replace(/[^/]*$/, isStatic ? `m/${moveId}.html` : "");
  return isStatic ? `${url.origin}${page}` : `${url.origin}${url.pathname}#/lobby/${moveId}`;
}
