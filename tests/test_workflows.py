import copy
import json
from pathlib import Path

import pytest
from PIL import Image

from openfield.engine import models
from openfield.engine.audit import audit_graph
from openfield.engine.workflows import (
    Slot,
    Template,
    WorkflowError,
    load_template,
    prune_unreachable,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def template() -> Template:
    return load_template("mini_ltx_flf2v", FIXTURES)


@pytest.fixture
def frames(tmp_path):
    first, last = tmp_path / "a.png", tmp_path / "b.png"
    Image.new("RGB", (64, 36), "red").save(first)
    Image.new("RGB", (64, 36), "blue").save(last)
    return first, last


def values(frames, **extra):
    first, last = frames
    return {"prompt": "A lighthouse at dusk.", "first_frame": first, "last_frame": last, **extra}


def test_fixture_template_has_no_problems(template):
    assert template.problems() == []


def test_patch_sets_literals_binds_assets_and_forces_fixed_values(template, frames):
    patched = template.patch(values(frames, duration=6, seed=42))
    graph = patched.graph
    assert graph["251:252"]["inputs"]["value"] == "A lighthouse at dusk."
    assert graph["251:198"]["inputs"]["value"] == 6
    assert graph["251:196"]["inputs"]["noise_seed"] == 42
    assert graph["251:250"]["inputs"]["value"] is False  # prompt enhancer forced off
    assert {(a.node, a.input) for a in patched.assets} == {("31", "image"), ("39", "image")}
    assert patched.outputs == {"video": "68"}
    assert template.graph["251:252"]["inputs"]["value"] == ""  # the template itself is untouched


def test_sizes_snap_to_the_model_multiple_and_say_so(template, frames):
    patched = template.patch(values(frames, width=1000, height=700))
    assert patched.graph["251:215"]["inputs"]["value"] == 992
    assert patched.graph["251:216"]["inputs"]["value"] == 704
    assert patched.snapped == {"width": 992, "height": 704}


def test_unreachable_nodes_are_pruned(template, frames):
    patched = template.patch(values(frames))
    assert "999" not in patched.graph  # PreviewAny hangs off nothing that is an output
    assert len(patched.graph) < len(template.graph)
    assert prune_unreachable(template.graph, {"video": "68"}).keys() == patched.graph.keys()


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"duration": 99}, "between"),
        ({"duration": "five"}, "number"),
        ({"duration": True}, "number"),
        ({"seed": -1}, "between"),
        ({"prompt": "   "}, "non-empty"),
        ({"nonsense": 1}, "unknown slot"),
    ],
)
def test_bad_values_are_rejected(template, frames, override, message):
    with pytest.raises(WorkflowError, match=message):
        template.patch(values(frames, **override))


def test_missing_required_slot_and_bad_files(template, frames, tmp_path):
    with pytest.raises(WorkflowError, match="missing required slot 'prompt'"):
        template.patch({"first_frame": frames[0], "last_frame": frames[1]})
    with pytest.raises(WorkflowError, match="file not found"):
        template.patch(values(frames, first_frame=tmp_path / "nope.png"))
    wrong = tmp_path / "clip.mp4"
    wrong.write_bytes(b"x")
    with pytest.raises(WorkflowError, match="not one of"):
        template.patch(values(frames, first_frame=wrong))


def test_typos_cannot_create_ghost_nodes(template, frames):
    broken = copy.deepcopy(template)
    broken.slots["prompt"] = Slot("prompt", "251:252", "vlaue", "text")  # typo in the input name
    assert any("no input 'vlaue'" in p for p in broken.problems())
    with pytest.raises(WorkflowError, match="no input 'vlaue'"):
        broken.patch(values(frames))
    missing = copy.deepcopy(template)
    missing.slots["seed"] = Slot("seed", "251:19", "noise_seed", "seed", default=1)
    assert any("not in the graph" in p for p in missing.problems())
    with pytest.raises(WorkflowError, match="not in the graph"):
        missing.patch(values(frames))


def test_a_slot_that_feeds_no_output_is_a_template_bug(template, frames):
    template.graph["900"] = {"class_type": "PrimitiveInt", "inputs": {"value": 3}}  # wired to nothing
    template.slots["duration"] = Slot("duration", "900", "value", "int", default=4)
    with pytest.raises(WorkflowError, match="does not feed any output"):
        template.patch(values(frames))
    # the same guard protects uploads
    template.slots["duration"] = Slot("duration", "251:198", "value", "int", default=4)
    template.slots["first_frame"] = Slot("first_frame", "900", "value", "image")
    with pytest.raises(WorkflowError, match="does not feed any output"):
        template.patch(values(frames))


def test_a_wired_input_is_not_a_literal(template, frames):
    template.slots["prompt"] = Slot("prompt", "251:222", "text", "text")  # linked to another node
    with pytest.raises(WorkflowError, match="wired to another node"):
        template.patch(values(frames))


def test_problems_catch_ui_format_dangling_links_and_bad_outputs(template):
    assert Template("x", "e", {"nodes": [], "links": []}, {}, {}).problems() == [
        "graph is a UI-format workflow; export API format"
    ]
    broken = copy.deepcopy(template)
    broken.graph["251:222"]["inputs"]["clip"] = ["404", 0]
    broken.outputs["video"] = "31"
    problems = broken.problems()
    assert any("missing node '404'" in p for p in problems)
    assert any("not an output node" in p for p in problems)


def test_workflow_hash_is_stable_and_sensitive(template, frames, tmp_path):
    a = template.patch(values(frames)).sha256()
    assert a == template.patch(values(frames)).sha256()
    assert a != template.patch(values(frames, seed=1)).sha256()
    other = tmp_path / "other.png"
    Image.new("RGB", (64, 36), "green").save(other)
    assert a != template.patch(values(frames, first_frame=other)).sha256()


def test_image_list_clones_a_loader_per_reference(tmp_path):
    graph = {
        "L": {"class_type": "LoadImage", "inputs": {"image": "ref.png", "upload": "image"}},
        "E": {
            "class_type": "TextEncodeQwenImage21",
            "inputs": {"prompt": "", "image_1": ["L", 0], "image_2": ["L", 0], "image_3": ["L", 0]},
        },
        "S": {"class_type": "SaveImageAdvanced", "inputs": {"images": ["E", 0], "prefix": "q"}},
    }
    slot = Slot("refs", "E", "", "image_list", pattern="image_{i}", start=2, limit=2, loader="L")
    tpl = Template("qwen", "qwen", graph, {"refs": slot}, {"image": "S"})
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    Image.new("RGB", (8, 8)).save(a)
    Image.new("RGB", (8, 8)).save(b)
    patched = tpl.patch({"refs": [a]})
    inputs = patched.graph["E"]["inputs"]
    assert inputs["image_2"] == ["L_refs_0", 0] and "image_3" not in inputs
    assert [x.path for x in patched.assets] == [a]
    with pytest.raises(WorkflowError, match="at most 2"):
        tpl.patch({"refs": [a, b, a]})
    with pytest.raises(WorkflowError, match="at least one"):
        tpl.patch({"refs": []})


def test_audit_passes_known_open_weights_and_reports_attribution(template):
    result = audit_graph(template.graph)
    assert result.passed and result.policy == "open-weights-only"
    assert {m["role"] for m in result.models} >= {"video:ltx-2.5", "text_encoder", "vae"}
    qwen = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_2.1_int8_convrot.safetensors"}},
        "2": {"class_type": "SaveImageAdvanced", "inputs": {"images": ["1", 0]}},
    }
    audited = audit_graph(qwen)
    assert audited.passed and any("Built with Qwen" in n for n in audited.notes)
    assert models.attributions(["qwen_image_2.1_int8_convrot.safetensors"]) == ["Built with Qwen"]


def test_audit_rejects_partner_nodes_and_unknown_weights(template):
    tainted = copy.deepcopy(template.graph)
    tainted["500"] = {"class_type": "KlingTextToVideoNode", "inputs": {"prompt": "x"}}
    tainted["501"] = {"class_type": "UNETLoader", "inputs": {"unet_name": "mystery-model.safetensors"}}
    result = audit_graph(tainted)
    assert not result.passed
    assert result.disallowed_nodes == ("KlingTextToVideoNode",)
    assert result.unknown_models == ("mystery-model.safetensors",)
    assert any("partner/API node" in n for n in result.notes)
    assert not audit_graph({}).passed


def test_every_template_node_in_the_manifest_is_allowed():
    manifest = json.loads(models.MANIFEST_PATH.read_text(encoding="utf-8"))
    allowed = set(manifest["allowed_node_types"])
    for name, info in manifest["templates"].items():
        assert set(info["node_types"]) <= allowed, name
    assert "KlingTextToVideoNode" not in allowed
