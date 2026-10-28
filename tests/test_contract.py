import copy
from pathlib import Path

import pytest

from openfield.engine.contract import CONTRACTS, check_contract
from openfield.engine.workflows import Slot, WorkflowError, load_template

WORKFLOWS = Path(__file__).resolve().parents[1] / "openfield" / "workflows"


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_every_mini_template_satisfies_its_contract_and_has_no_problems(name):
    template = load_template(name, WORKFLOWS)
    assert check_contract(name, template) == []
    assert template.problems() == []


def test_contract_reports_missing_and_mistyped_slots():
    template = load_template("ltx25_flf2v", WORKFLOWS)
    del template.slots["seed"]
    template.slots["duration"] = Slot("duration", "251:198", "value", "text")
    template.outputs.clear()
    issues = check_contract("ltx25_flf2v", template)
    assert "missing slot 'seed' (seed)" in issues
    assert any("slot 'duration' is 'text'" in i for i in issues)
    assert "missing output 'video'" in issues
    assert check_contract("nonsense", template) == ["no contract is defined for template 'nonsense'"]


def test_ltx25_flf2v_contract_treats_mids_as_optional():
    template = load_template("ltx25_flf2v", WORKFLOWS)
    assert check_contract("ltx25_flf2v", template) == []

    missing_optional = copy.deepcopy(template)
    del missing_optional.slots["mids"]
    assert check_contract("ltx25_flf2v", missing_optional) == []

    missing_required = copy.deepcopy(template)
    del missing_required.slots["seed"]
    issues = check_contract("ltx25_flf2v", missing_required)
    assert "missing slot 'seed' (seed)" in issues


def test_optional_reference_list_strips_placeholder_inputs_when_absent(tmp_path):
    template = load_template("qwen21_edit", WORKFLOWS)
    from PIL import Image

    base = tmp_path / "hero.png"
    Image.new("RGB", (16, 16)).save(base)
    patched = template.patch({"prompt": "Move the camera.", "base_image": base, "seed": 1})
    inputs = patched.graph["459:474"]["inputs"]
    assert "images.image_1" in inputs and "images.image_2" not in inputs
    assert "475" not in patched.graph  # the template's pre-wired reference loader is pruned
    ref = tmp_path / "ref.png"
    Image.new("RGB", (16, 16)).save(ref)
    with_ref = template.patch({"prompt": "x", "base_image": base, "refs": [ref], "seed": 1})
    assert with_ref.graph["459:474"]["inputs"]["images.image_2"] == ["475_refs_0", 0]
    assert template.patch({"prompt": "x", "base_image": base, "refs": [ref] * 9, "seed": 1})  # ten images in all
    with pytest.raises(WorkflowError):
        template.patch({"prompt": "x", "base_image": base, "refs": [ref] * 10, "seed": 1})
