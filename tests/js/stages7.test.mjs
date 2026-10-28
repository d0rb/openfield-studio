import { test } from "node:test";
import assert from "node:assert/strict";
import { stageList, stepName } from "../../openfield/web/js/lib/stages.js";
import { FILM_KINDS, ledgerTakes } from "../../openfield/web/js/lib/takes.js";

const ids = (take) => stageList(take, null).map((s) => s.id);

test("a running transition, board, edit or face-only re-shoot shows its own steps, not only Finish", () => {
  assert.deepEqual(ids({ kind: "transition", recipe: {} }), ["prepare", "bridge", "finish"]);
  assert.deepEqual(ids({ kind: "edit", recipe: {} }), ["source", "edit", "finish"]);
  assert.deepEqual(ids({ kind: "reshoot", recipe: { face_only: true } }), ["prepare", "face", "motion", "finish"]);
  assert.deepEqual(ids({ kind: "reshoot", recipe: {} }), ["prepare", "motion", "finish"]);
  const board = ids({ kind: "shots", recipe: { board: Array(9).fill("a") } });
  assert.equal(board.length, 11);
  assert.equal(board[1], "shot_1");
  assert.equal(stepName("shot_4"), "Setup 4");
  assert.equal(stepName("bridge"), "Bridge");
  assert.equal(stepName("face_retry"), "Face swap, re-rolled");
});

test("the Takes station lists this install's own bridges, boards and edits", () => {
  for (const kind of ["transition", "shots", "edit"]) assert.ok(FILM_KINDS.has(kind), kind);
  const takes = [{ id: "a", kind: "transition", created_at: "2026-10-23T01:00:00Z" }, { id: "b", kind: "portrait", created_at: "2026-10-23T02:00:00Z" }];
  assert.deepEqual(ledgerTakes(takes).map((t) => t.id), ["a"]);
});

test("tiles and cards load a take's small pictures, and fall back to the full files", async () => {
  const { thumbOf, stillThumb } = await import("../../openfield/web/js/lib/stages.js");
  const api = { asset: (p) => `/${p}`, media: (t, f) => `/media/${t.id}/${f}` };
  const take = { id: "tk_a", outputs: [{ role: "poster", file: "poster.png" }] };
  const state = { previews: { takes: { tk_a: { poster: "showcase/previews/tk_a.jpg", stills: { "runs/01_hero/image.png": "showcase/previews/tk_a-s1.jpg" } } } } };
  assert.equal(thumbOf(state, take, api), "/showcase/previews/tk_a.jpg");
  assert.equal(thumbOf(state, { ...take, id: "tk_r", replay_of: "tk_a" }, api), "/showcase/previews/tk_a.jpg", "a replay shows its recording's picture");
  assert.equal(thumbOf({}, take, api), "/media/tk_a/poster.png", "no preview: the full poster");
  assert.equal(thumbOf({}, { id: "tk_b", outputs: [] }, api), "", "nothing to show");
  assert.equal(stillThumb(state, take, "runs/01_hero/image.png", api), "/showcase/previews/tk_a-s1.jpg");
  assert.equal(stillThumb(state, take, "runs/02_end/image.png", api), "/media/tk_a/runs/02_end/image.png", "no copy: the still itself");
});
