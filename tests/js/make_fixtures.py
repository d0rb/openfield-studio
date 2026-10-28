"""Snapshots of server output that the JavaScript tests read, so they test against real data.

    python tests/js/make_fixtures.py        # rewrite tests/js/fixtures/*.json

tests/test_rig.py fails when the files on disk differ from what the server produces now.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from openfield.engine import receipt as receipts
from openfield.engine import rig
from openfield.pipeline import DirectRequest, Pipeline, fingerprint

OUT = Path(__file__).parent / "fixtures"


def sample_recipe() -> dict[str, object]:
    return {
        "schema": "openfield.recipe/1", "kind": "direct", "template": "ltx25_i2v", "seed": 7,
        "inputs": {"subject": "A lighthouse at dusk", "rig": {"movement": "orbit_90", "lens": "anamorphic"},
                   "mode": "prompt_only", "seed": 7, "orientation": "portrait", "audio": "waves",
                   "cast": {"name": "Mara", "refs": ["0" * 64]}},
        "models": [],
    }


def plan_table() -> dict[str, object]:
    """Every move at several lengths, full and quick, plain and with a transformation (one that keeps the face and one
    that changes it), segmented and in one pass: what the browser's plan estimate must reproduce. The key is
    move|seconds|quick|effect|pass."""
    table: dict[str, object] = {}
    for move_id in rig.MOVES:
        for seconds in (2, 5, 10):
            for quick in (False, True):
                for effect in ("none", "ignite", "gold"):
                    for single in (False, True):
                        try:
                            plan = rig.compile_shot(rig.CameraRig(movement=move_id, duration_seconds=seconds, effect=effect),
                                                    "A lighthouse at dusk", prompt_only=quick,
                                                    single_pass=single).to_dict()
                        except ValueError:  # an effect on a move played backwards is refused: no row
                            continue
                        key = f"{move_id}|{seconds}|{'quick' if quick else 'full'}|{effect}|{'one' if single else 'segments'}"
                        table[key] = {
                            "mode": plan["mode"], "roles": [a["role"] for a in plan["anchors"]],
                            "segments": [s["seconds"] for s in plan["segments"]], "total": plan["total_seconds"],
                        }
    return table


def remix_requests() -> dict[str, DirectRequest]:
    """Direct takes of every shape a receipt or a recipe link must rebuild: one-still moves, a keyframed move in full, quick
    and in one pass, a spoken line with and without a language, an action, effects, an angle and the tiers."""
    def take(**kw: object) -> DirectRequest:
        return DirectRequest(**({"subject": "Oskar at the net, a close-up", "rig": {"movement": "static"}, "seed": 11,
                                 "auto_approve": True} | kw))

    return {
        "static": take(cast_name="Oskar"),
        "static_quick": take(prompt_only=True, audio="a drum loop"),  # quick on a one-still move: only the fingerprint changes
        "orbit_90": take(rig={"movement": "orbit_90", "lens": "anamorphic"}, audio="waves", orientation="portrait"),
        "dolly_in": take(rig={"movement": "dolly_in"}),
        "dolly_in_quick": take(rig={"movement": "dolly_in"}, prompt_only=True),
        "orbit_180_one_pass": take(rig={"movement": "orbit_180"}),
        "spoken_line": take(line='  "We leave at   first light."  ', delivery="whisper", language="English"),
        "spoken_line_no_language": take(line="Come home.", delivery="calm", cast_name="Mara"),
        "action": take(rig={"movement": "dolly_in"}, action="  He draws the katana\nand raises the blade "),
        "talking_acted_draft": take(line="Ready?", action="She lifts the lantern", quality="draft",
                                    rig={"movement": "static", "effect": "rain", "grade": "teal_orange", "score": "strings"}),
        "transformation": take(rig={"movement": "static", "effect": "ignite"}),
        "experimental": take(rig={"movement": "whip_pan"}),
        "angle_fine": take(rig={"movement": "dolly_in", "angle": "back_left/low/wide"}, quality="fine"),
    }


class _Written(Exception):
    pass


def recorded(req: DirectRequest) -> dict[str, object]:
    """The take as Replay lists it: the recipe `start_direct` writes for the request, with what take.json keeps beside it."""
    found: dict[str, object] = {}

    def new_take(kind, label, recipe, fp, backend):
        found.update(kind=kind, recipe=recipe, recipe_hash=fingerprint(fp))
        raise _Written

    pipeline = Pipeline.__new__(Pipeline)
    pipeline.backend = lambda: SimpleNamespace(kind="replay", label="Replay", locked=True)
    pipeline._new_take = new_take
    try:
        asyncio.run(pipeline.start_direct(req))
    except _Written:
        pass
    return found


def receipt_inputs(req: DirectRequest) -> dict[str, object]:
    """A Direct receipt's inputs as `Pipeline._run_direct` writes them, for the keys a remix reads (tests/test_pipeline.py
    checks real receipts against this)."""
    camera = rig.CameraRig(**req.rig)
    plan = rig.compile_shot(camera, req.subject, req.audio, prompt_only=req.prompt_only, line=req.line,
                            delivery=req.delivery, language=req.language, action=req.action)
    inputs: dict[str, object] = {
        "subject": req.subject.strip(), "rig": asdict(camera), "move": plan.move_id, "mode": plan.mode,
        "final_prompt": plan.prompt, "seed": req.seed, "orientation": req.orientation, "audio": req.audio,
        "quality": req.quality}
    if plan.transformation:
        inputs["transformation"] = plan.transformation
    if plan.dialogue:
        inputs["dialogue"] = plan.dialogue
    if plan.action:
        inputs["action"] = plan.action
    inputs["cast"] = {"name": req.cast_name, "refs": []}
    return inputs


def remix_receipts() -> list[dict[str, object]]:
    """What POST /api/receipts/import answers for each take (a recipe link holds the same recipe), beside the recording."""
    cases = []
    for name, req in remix_requests().items():
        take = recorded(req)
        inputs = receipt_inputs(req) | {"recipe_hash": take["recipe_hash"]}  # _seal_and_finish adds it to every receipt
        cases.append({"name": name, "recorded": take, "imported": {"verified": True, "recipe": receipts.recipe_from_receipt(
            {"take": {"kind": "direct"}, "inputs": inputs})}})
    return cases


def build() -> dict[str, object]:
    shot = rig.compile_shot
    cam = rig.CameraRig
    return {
        "plan_table.json": plan_table(),
        "remix_receipts.json": remix_receipts(),
        "catalog.json": rig.catalog(),
        "recipe_link.json": {"recipe": sample_recipe(), "link": receipts.recipe_link(sample_recipe())},
        "plans.json": {
            "dolly_in": shot(cam(movement="dolly_in"), "A lighthouse at dusk").to_dict(),
            "static": shot(cam(movement="static"), "A lighthouse at dusk").to_dict(),
            "orbit_360": shot(cam(movement="orbit_360", duration_seconds=5), "A bottle").to_dict(),
            "dolly_in_quick": shot(cam(movement="dolly_in"), "A lighthouse at dusk", prompt_only=True).to_dict(),
            "static_ignite": shot(cam(movement="static", effect="ignite"), "A lighthouse at dusk").to_dict(),
            "orbit_180_one_pass": shot(cam(movement="orbit_180"), "A bottle", single_pass=True).to_dict(),
        },
    }


def render(data: object) -> str:
    return json.dumps(data, indent=1, sort_keys=True) + "\n"


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, data in build().items():
        (OUT / name).write_text(render(data), encoding="utf-8", newline="\n")  # LF on every OS, like the rest of the repo
        print("wrote", OUT / name)
