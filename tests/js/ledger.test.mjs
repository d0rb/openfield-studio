import { test } from "node:test";
import assert from "node:assert/strict";
import { ledgerLine } from "../../openfield/web/js/lib/billing.js";

test("the recorded takes' GPU time reads as hours and money, or minutes when it is short", () => {
  assert.equal(ledgerLine({ takes: 134, seconds: 19440 }), "5.4 GPU hours, about $3.83");
  assert.equal(ledgerLine({ takes: 1, seconds: 150 }), "3 GPU minutes, about 3.0¢");
  assert.equal(ledgerLine({ takes: 1, seconds: 20 }), "1 GPU minute, about 0.4¢");
  assert.equal(ledgerLine(null), null);
  assert.equal(ledgerLine({ takes: 0, seconds: 0 }), null);
});
