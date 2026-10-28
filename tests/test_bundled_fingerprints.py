"""The recorded takes bundled for Replay must keep matching: a recipe key written at its default would change every
fingerprint, and Replay would stop finding the 64 real renders. The first test re-hashes each bundled take's stored recipe;
the second sends every bundled Direct take back through the request path (the body the form sends, DirectBody and
`start_direct`) and checks that the recipe it writes has the recorded fingerprint."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import openfield.pipeline as pipeline_module
from openfield.app import DirectBody
from openfield.engine.rig import CameraRig, compile_shot
from openfield.pipeline import DirectRequest, Pipeline, fingerprint

# OPENFIELD_BUNDLED_TAKES points the tests at another folder of recorded takes (a checkout that has the media)
BUNDLED = Path(os.environ.get("OPENFIELD_BUNDLED_TAKES") or Path(__file__).resolve().parents[1] / "openfield" / "web" / "showcase" / "takes")
EXTRAS = {"cast_name", "auto_approve", "reference_name"}  # kept in take.json beside the recipe, never hashed


def recipes():
    if not BUNDLED.is_dir():
        return []
    found = []
    for take_json in sorted(BUNDLED.glob("*/take.json")):
        data = json.loads(take_json.read_text(encoding="utf-8"))
        if data.get("status") == "succeeded" and data.get("recipe_hash"):
            found.append((take_json.parent.name, data))
    return found


@pytest.mark.skipif(not recipes(), reason="no bundled takes in this checkout")
@pytest.mark.parametrize("take_id,data", recipes(), ids=[t for t, _ in recipes()])
def test_every_bundled_take_still_fingerprints_to_its_recorded_hash(take_id, data):
    recipe = {k: v for k, v in data["recipe"].items() if k not in EXTRAS}
    assert fingerprint(recipe) == data["recipe_hash"], f"{take_id}: a recipe key changed; Replay would stop matching it"
    if recipe.get("kind") == "direct":  # a tier or a sourced hero is in the recipe only when it is not the default
        assert recipe.get("quality", "draft") != "standard", "standard is the default and is never written"
        if "source_sha256" in recipe:
            assert len(recipe["source_sha256"]) == 64


def direct_takes():
    return [(take_id, data) for take_id, data in recipes() if data.get("kind") == "direct"]


class _Written(Exception):
    """Raised in place of creating the take: the recipe start_direct wrote is all this test reads."""


@pytest.mark.skipif(not direct_takes(), reason="no bundled Direct takes in this checkout")
@pytest.mark.parametrize("take_id,data", direct_takes(), ids=[t for t, _ in direct_takes()])
async def test_every_bundled_direct_take_writes_its_recorded_fingerprint_again(take_id, data, tmp_path, monkeypatch):
    recipe = data["recipe"]
    plan = compile_shot(CameraRig(**recipe["rig"]), recipe["subject"], prompt_only=bool(recipe.get("prompt_only")))
    if bool(recipe.get("single_pass")) != any(s.mids for s in plan.segments):
        pytest.skip("rendered in segments before one-pass shots: today's request makes its one-pass twin")
    body = {"subject": recipe["subject"], "rig": recipe["rig"], "seed": recipe["seed"],
            "orientation": recipe.get("orientation", "landscape"), "auto_approve": bool(recipe.get("auto_approve")),
            "prompt_only": bool(recipe.get("prompt_only"))}
    body |= {k: recipe[k] for k in ("audio", "line", "delivery", "language", "action", "quality") if recipe.get(k) is not None}
    sent = DirectBody.model_validate(body)  # the server's own limits, as over HTTP
    source = None
    if recipe.get("source_sha256"):
        source = tmp_path / "source.png"
        source.write_bytes(b"a stand-in for the person's image")
    # stand-ins: a Cast reference is named by its own digest, the image hashes to the recorded one
    monkeypatch.setattr(pipeline_module, "file_sha256",
                        lambda p: recipe["source_sha256"] if source is not None and Path(p) == source else Path(p).name)
    written: dict = {}

    def new_take(kind, label, stored, fp, backend):
        written.update(fp)
        raise _Written

    pipeline = Pipeline.__new__(Pipeline)
    pipeline.backend = lambda: SimpleNamespace(kind="replay", label="Replay", locked=True)
    pipeline._new_take = new_take
    with pytest.raises(_Written):
        await pipeline.start_direct(DirectRequest(
            subject=sent.subject, rig=sent.rig, cast_refs=[Path(h) for h in recipe.get("cast_refs", [])],
            cast_name=recipe.get("cast_name"), audio=sent.audio, line=sent.line, delivery=sent.delivery,
            language=sent.language, action=sent.action, seed=sent.seed, orientation=sent.orientation,
            auto_approve=sent.auto_approve, prompt_only=sent.prompt_only, quality=sent.quality, source=source))
    changed = sorted(k for k in set(written) | set(recipe) - EXTRAS if written.get(k) != recipe.get(k))
    assert fingerprint(written) == data["recipe_hash"], f"{take_id}: start_direct writes {changed} differently now"
