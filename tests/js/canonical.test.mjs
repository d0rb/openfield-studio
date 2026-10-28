import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, existsSync } from "node:fs";

import { canonical, checkSeal, parseKeepingNumbers } from "../../openfield/web/js/lib/canonical.js";

// the three sealed receipts kept as fixtures always run; the bundled takes join them on a checkout that has them
const FIXTURES = new URL("./fixtures/", import.meta.url);
const TAKES = new URL("../../openfield/web/showcase/takes/", import.meta.url);
const receipts = [
  ...readdirSync(FIXTURES).filter((f) => /^receipt-.*\.json$/.test(f)).map((f) => new URL(f, FIXTURES)),
  ...(existsSync(TAKES) ? readdirSync(TAKES).filter((d) => existsSync(new URL(`${d}/receipt.json`, TAKES))).map((d) => new URL(`${d}/receipt.json`, TAKES)) : []),
];

test("every sealed receipt checks out in the browser's way, exactly as openfield verify says", async () => {
  assert.ok(receipts.length >= 3, "the fixture receipts are there");
  for (const file of receipts) {
    const result = await checkSeal(readFileSync(file, "utf8"));
    assert.equal(result.ok, true, `${file.pathname.split("/").slice(-2).join("/")}: ${result.reason}`);
  }
});

test("an edited receipt does not check out", async () => {
  const text = readFileSync(receipts[0], "utf8");
  const tree = JSON.parse(text);
  tree.app = { ...tree.app, edited: true };
  const result = await checkSeal(JSON.stringify(tree, null, 2));
  assert.equal(result.ok, false);
  assert.match(result.reason, /differs/);
});

test("canonical JSON keeps each number as written, sorts keys and escapes like Python", () => {
  const tree = parseKeepingNumbers(String.raw`{"b": 5.0, "a": [1e-05, true, null], "s": "café \"q\"\n\u0001"}`);
  assert.equal(canonical(tree), String.raw`{"a":[1e-05,true,null],"b":5.0,"s":"café \"q\"\n\u0001"}`);
});

test("text that is not a sealed receipt is refused, never thrown", async () => {
  assert.equal((await checkSeal("not json")).ok, false);
  assert.equal((await checkSeal("[1, 2]")).ok, false);
  assert.equal((await checkSeal('{"integrity": {"alg": "md5", "digest": "x"}}')).ok, false);
  // a page served in the receipt's place is not a receipt, which is not the same as a receipt that fails its seal
  const page = await checkSeal("<!doctype html><title>Not found</title>");
  assert.equal(page.reason, "not a receipt");
  assert.match(page.detail, /unexpected character/);
  assert.equal((await checkSeal("[1, 2]")).reason, "not a receipt");
  assert.equal((await checkSeal(undefined)).reason, "not a receipt");
  assert.equal((await checkSeal('{"integrity": {"alg": "md5", "digest": "x"}}')).reason, "no sha256 seal");
});

test("a browser that cannot hash here (plain http on a LAN) says so, never a fail", async () => {
  const sealed = `{"take": {"id": "tk_1"}, "integrity": {"alg": "sha256", "digest": "${"0".repeat(64)}"}}`;
  const native = Object.getOwnPropertyDescriptor(globalThis, "crypto");
  const stubs = [
    [{ getRandomValues: () => {} }, "unavailable"], // what an insecure page has: crypto, without crypto.subtle
    [undefined, "unavailable"],
    [{ subtle: { digest: async () => { throw new Error("The operation is not supported."); } } }, "hashing failed"], // WebCrypto is here and the digest itself fails: told apart
  ];
  try {
    for (const [stub, reason] of stubs) {
      Object.defineProperty(globalThis, "crypto", { value: stub, configurable: true, writable: true });
      const result = await checkSeal(sealed);
      assert.equal(result.ok, false);
      assert.equal(result.reason, reason, JSON.stringify(stub));
    }
  } finally {
    Object.defineProperty(globalThis, "crypto", native);
  }
  assert.equal((await checkSeal(sealed)).reason, "the digest differs", "with WebCrypto back, the same text is checked");
});
