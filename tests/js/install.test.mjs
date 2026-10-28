import test from "node:test";
import assert from "node:assert/strict";

import { COST, cloneLine, folderName, installSteps } from "../../openfield/web/js/lib/install.js";

const REPO = "https://github.com/owner/openfield-studio";

test("the folder a clone lands in is the repository's last segment", () => {
  assert.equal(folderName(REPO), "openfield-studio");
  assert.equal(folderName("https://github.com/owner/studio"), "studio");
  assert.equal(folderName("https://github.com/owner/studio/"), "studio");
});

test("without a repository the folder is the plain default", () => {
  assert.equal(folderName(null), "openfield-studio");
  assert.equal(folderName(""), "openfield-studio");
  assert.equal(folderName(undefined), "openfield-studio");
});

test("the three ways in each carry a title, a text and the commands to run", () => {
  const steps = installSteps(REPO);
  assert.equal(steps.length, 3);
  assert.deepEqual(steps.map((s) => s.title), [
    "Your own GPU (24-32 GB)",
    "Rent a GPU box",
    "Direct it from your own agent",
  ]);
  for (const step of steps) {
    assert.ok(step.text, step.title);
    assert.ok(step.code, step.title);
  }
});

test("your own GPU: clone, then install and serve in the folder the clone made", () => {
  const [own] = installSteps(REPO);
  assert.equal(own.code, `git clone ${REPO}\ncd openfield-studio && pip install -e . && openfield serve`);
});

test("a rented GPU: the same clone, then the one script that sets the box up", () => {
  const [, rented] = installSteps(REPO);
  assert.ok(rented.code.startsWith(`git clone ${REPO}\n`), rented.code);
  assert.ok(rented.code.includes("bash scripts/pod_setup.sh"), rented.code);
  assert.match(rented.text, /docs\/CONNECT\.md/);
});

test("your own agent: the studio serves, then the Chat room talks to it", () => {
  const [, , agent] = installSteps(REPO);
  assert.ok(agent.code.startsWith("openfield serve"), agent.code);
  assert.match(agent.code, /Chat room/);
  assert.match(agent.text, /Chat room/);
});

test("the one line installs the studio and starts it", () => {
  assert.equal(cloneLine(REPO), `git clone ${REPO} && cd openfield-studio && pip install -e . && openfield serve`);
  assert.equal(cloneLine("https://github.com/owner/studio"),
    "git clone https://github.com/owner/studio && cd studio && pip install -e . && openfield serve");
});

test("without a repository the line still says what to run", () => {
  const line = cloneLine(null);
  assert.match(line, /^git clone https:\/\/github\.com\//);
  assert.match(line, /&& cd openfield-studio && pip install -e \. && openfield serve$/);
});

test("the cost of a shot is stated, measured", () => {
  assert.equal(COST, "2 to 3 cents per 5-second shot.");
});
