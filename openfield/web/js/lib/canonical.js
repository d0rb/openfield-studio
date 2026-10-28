// Check a receipt's seal in the browser, the same way `openfield verify` does on the command line: the receipt without
// its `integrity` field, written as canonical JSON (keys sorted, no spaces, unicode as itself, each number exactly as
// the file wrote it), hashed with SHA-256, must equal the digest the receipt carries.

const WS = /[ \t\n\r]/;

/** Parse JSON text into a tree that keeps every number's own spelling (5.0 stays "5.0", as Python wrote it). */
export function parseKeepingNumbers(text) {
  let i = 0;
  const fail = (what) => { throw new SyntaxError(`${what} at ${i}`); };
  const skip = () => { while (i < text.length && WS.test(text[i])) i++; };
  const value = () => {
    skip();
    const c = text[i];
    if (c === "{") {
      i++;
      const out = new Map();
      skip();
      if (text[i] === "}") { i++; return { object: out }; }
      for (;;) {
        skip();
        if (text[i] !== '"') fail("expected a key");
        const key = string();
        skip();
        if (text[i++] !== ":") fail("expected a colon");
        out.set(key, value());
        skip();
        if (text[i] === ",") { i++; continue; }
        if (text[i++] === "}") return { object: out };
        fail("expected , or }");
      }
    }
    if (c === "[") {
      i++;
      const out = [];
      skip();
      if (text[i] === "]") { i++; return { array: out }; }
      for (;;) {
        out.push(value());
        skip();
        if (text[i] === ",") { i++; continue; }
        if (text[i++] === "]") return { array: out };
        fail("expected , or ]");
      }
    }
    if (c === '"') return { string: string() };
    for (const word of ["true", "false", "null"]) {
      if (text.startsWith(word, i)) { i += word.length; return { literal: word }; }
    }
    const m = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(text.slice(i, i + 64));
    if (!m) fail("unexpected character");
    i += m[0].length;
    return { number: m[0] };
  };
  const string = () => {
    const start = i;
    i++;
    while (i < text.length && text[i] !== '"') i += text[i] === "\\" ? 2 : 1;
    if (text[i] !== '"') fail("unterminated string");
    i++;
    return JSON.parse(text.slice(start, i)); // the escapes decoded exactly as JSON defines them
  };
  const tree = value();
  skip();
  if (i !== text.length) fail("trailing text");
  return tree;
}

// Python's json.dumps(ensure_ascii=False): only the quote, the backslash and control characters are escaped
const SHORT = { '"': '\\"', "\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t", "\b": "\\b", "\f": "\\f" };
const quote = (s) => `"${s.replace(/["\\\u0000-\u001f]/g, (c) => SHORT[c] ?? `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`)}"`;

/** The tree written as canonical JSON: sorted keys, "," and ":" with no spaces. */
export function canonical(node) {
  if ("object" in node) {
    const keys = [...node.object.keys()].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${keys.map((k) => `${quote(k)}:${canonical(node.object.get(k))}`).join(",")}}`;
  }
  if ("array" in node) return `[${node.array.map(canonical).join(",")}]`;
  if ("string" in node) return quote(node.string);
  if ("number" in node) return node.number;
  return node.literal;
}

/** SHA-256 of a text's UTF-8 bytes, as lowercase hex (WebCrypto: the browser and Node both have it). */
export async function sha256Hex(text) {
  const bytes = new TextEncoder().encode(text);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Check a receipt's text: { ok, expected, actual, reason }, ok only when the seal matches; never throws. Reasons:
 * "unavailable" (WebCrypto needs https or localhost), "hashing failed" (WebCrypto is here and the digest threw; see
 * `detail`), "not a receipt" (see `detail`), "no sha256 seal", "the digest differs". */
export async function checkSeal(text) {
  const no = (reason, more) => ({ ok: false, expected: null, actual: null, reason, ...more });
  if (typeof globalThis.crypto?.subtle?.digest !== "function") return no("unavailable");
  let tree;
  try {
    tree = parseKeepingNumbers(text);
  } catch (error) {
    return no("not a receipt", { detail: error.message });
  }
  if (!("object" in tree)) return no("not a receipt", { detail: "not a JSON object" });
  const integrity = tree.object.get("integrity");
  const field = (key) => (integrity && "object" in integrity ? integrity.object.get(key)?.string ?? null : null);
  const expected = field("digest");
  if (!expected || field("alg") !== "sha256") return no("no sha256 seal", { expected });
  tree.object.delete("integrity");
  try {
    const actual = await sha256Hex(canonical(tree));
    return { ok: actual === expected, expected, actual, reason: actual === expected ? null : "the digest differs" };
  } catch (error) {
    return no("hashing failed", { expected, detail: error?.message }); // WebCrypto is here, and the digest itself threw
  }
}
