"""Snapshots of server output that the JavaScript tests read, so they test against real data.

    python tests/js/make_fixtures.py        # rewrite tests/js/fixtures/*.json

tests/test_rig.py fails when the files on disk differ from what the server produces now.
"""
from __future__ import annotations

import json
from pathlib import Path

from openfield.engine import receipt as receipts
from openfield.engine import rig

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
    """Every move at several lengths, full and quick: what the browser's plan estimate must reproduce."""
    table: dict[str, object] = {}
    for move_id in rig.MOVES:
        for seconds in (2, 3, 5, 7, 10):
            for quick in (False, True):
                plan = rig.compile_shot(rig.CameraRig(movement=move_id, duration_seconds=seconds), "A lighthouse at dusk",
                                        prompt_only=quick).to_dict()
                table[f"{move_id}|{seconds}|{'quick' if quick else 'full'}"] = {
                    "mode": plan["mode"], "roles": [a["role"] for a in plan["anchors"]],
                    "segments": [s["seconds"] for s in plan["segments"]], "total": plan["total_seconds"],
                }
    return table


def build() -> dict[str, object]:
    shot = rig.compile_shot
    cam = rig.CameraRig
    return {
        "plan_table.json": plan_table(),
        "catalog.json": rig.catalog(),
        "recipe_link.json": {"recipe": sample_recipe(), "link": receipts.recipe_link(sample_recipe())},
        "plans.json": {
            "dolly_in": shot(cam(movement="dolly_in"), "A lighthouse at dusk").to_dict(),
            "static": shot(cam(movement="static"), "A lighthouse at dusk").to_dict(),
            "orbit_360": shot(cam(movement="orbit_360", duration_seconds=5), "A bottle").to_dict(),
            "dolly_in_quick": shot(cam(movement="dolly_in"), "A lighthouse at dusk", prompt_only=True).to_dict(),
        },
    }


def render(data: object) -> str:
    return json.dumps(data, indent=1, sort_keys=True) + "\n"


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, data in build().items():
        (OUT / name).write_text(render(data), encoding="utf-8", newline="\n")  # LF on every OS, like the rest of the repo
        print("wrote", OUT / name)
