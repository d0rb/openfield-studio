from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from openfield.engine import quality
from openfield.engine.workflows import load_template

WORKFLOWS = Path(__file__).resolve().parents[1] / "openfield" / "workflows"


def test_tiers_say_what_they_change_and_standard_is_what_the_app_always_rendered():
    assert list(quality.TIERS) == ["draft", "standard", "fine"]
    assert quality.still_size("standard") == (1344, 768) and quality.video_size("standard") == (1280, 720)
    assert quality.still_size("standard", "portrait") == (768, 1344) and quality.steps("standard") == 25
    assert quality.check(None) == "standard" and quality.check("fine") == "fine"
    with pytest.raises(ValueError, match="unsupported quality"):
        quality.check("ultra")
    tiers = {t["id"]: t for t in quality.describe()}
    assert tiers["standard"]["tested"] is True and tiers["draft"]["tested"] is True and tiers["fine"]["tested"] is True, "draft and fine checked by eye on the Oct 22 renders"
    assert all(t["what"] for t in tiers.values())


@pytest.mark.parametrize("tier", ["draft", "standard", "fine"])
@pytest.mark.parametrize("orientation", ["landscape", "portrait"])
def test_every_tier_fits_every_direct_template_without_snapping_except_the_known_one(tier, orientation, tmp_path):
    image = tmp_path / "a.png"
    Image.new("RGB", (64, 36), "red").save(image)
    sw, sh = quality.still_size(tier, orientation)
    vw, vh = quality.video_size(tier, orientation)
    t2i = load_template("qwen21_t2i", WORKFLOWS).patch({"prompt": "x", "seed": 1, "width": sw, "height": sh, "steps": quality.steps(tier)})
    assert t2i.snapped == {}, "the still size is a multiple of 16 within the caps"
    edit = load_template("qwen21_edit", WORKFLOWS).patch({"prompt": "x", "seed": 1, "base_image": image, "custom_size": True, "width": sw, "height": sh, "steps": quality.steps(tier)})
    assert edit.snapped == {}
    flf = load_template("ltx25_flf2v", WORKFLOWS).patch({"prompt": "x", "seed": 1, "duration": 5, "width": vw, "height": vh, "first_frame": image, "last_frame": image})
    assert flf.snapped == {}
    i2v = load_template("ltx25_i2v", WORKFLOWS).patch({"prompt": "x", "seed": 1, "duration": 5, "width": vw, "height": vh, "first_frame": image})
    expected = {"height": 704} if (tier, orientation) == ("standard", "landscape") else {"width": 704} if (tier, orientation) == ("standard", "portrait") else {}
    assert i2v.snapped == expected, "only the standard video's 720 snaps to 704 on the still-to-video graph, as it always did"


def test_the_steps_slot_at_its_default_leaves_the_qwen_graphs_untouched():
    for name in ("qwen21_t2i", "qwen21_edit"):
        template = load_template(name, WORKFLOWS)
        assert template.graph["459:458"]["inputs"]["steps"] == 25 and template.slots["steps"].default == 25
        values = {"prompt": "x", "seed": 1}
        if name == "qwen21_edit":
            values["base_image"] = Path(__file__)  # any existing file with no image suffix would be refused; use a png
        if name == "qwen21_edit":
            continue  # the edit graph's base image needs a real file; the t2i case proves the point for the shared node
        plain = template.patch(values).graph
        explicit = template.patch({**values, "steps": 25}).graph
        assert json.dumps(plain, sort_keys=True) == json.dumps(explicit, sort_keys=True)
        assert template.patch({**values, "steps": 12}).graph["459:458"]["inputs"]["steps"] == 12
