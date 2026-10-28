"""The real, exported ComfyUI templates in openfield/workflows: what the patcher does to each of them.

These were validated once against a live ComfyUI 0.41.0 (scripts/validate_on_comfy.py). Here they are held
in place: a changed slot map, a re-export or a regenerated manifest that drifts apart fails loudly.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

from openfield.engine.audit import audit_graph
from openfield.engine.contract import CONTRACTS, check_contract
from openfield.engine.workflows import WORKFLOW_DIR, WorkflowError, load_template, sample_values

ROOT = Path(__file__).resolve().parents[1]
NAMES = sorted(CONTRACTS)
PRUNED_CLASSES = {"TextGenerate", "TextGenerateLTX2Prompt", "ResolutionSelector", "ImageCompare", "BatchImagesNode"}
NOTHING_TO_PRUNE = {"esrgan_upscale"}  # a straight chain: no prompt enhancer, no resolution selector, nothing that feeds no output


def load_script(name: str):
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    folder = tmp_path_factory.mktemp("samples")
    image, video = folder / "a.png", folder / "a.mp4"
    Image.new("RGB", (32, 32)).save(image)
    video.write_bytes(b"")
    return image, video


@pytest.mark.parametrize("name", NAMES)
def test_every_real_template_satisfies_its_contract_and_the_audit(name):
    template = load_template(name, WORKFLOW_DIR)
    assert check_contract(name, template) == []
    assert template.problems() == []
    assert audit_graph(template.graph).passed


@pytest.mark.parametrize("name", NAMES)
def test_patching_removes_prompt_enhancers_and_helper_nodes(name, samples):
    template = load_template(name, WORKFLOW_DIR)
    patched = template.patch(sample_values(template, *samples))
    classes = {node["class_type"] for node in patched.graph.values()}
    assert not classes & PRUNED_CLASSES, classes & PRUNED_CLASSES
    assert (len(patched.graph) == len(template.graph)) if name in NOTHING_TO_PRUNE else (len(patched.graph) < len(template.graph))
    # every output we ask for survived, and nothing the audit forbids came back
    assert all(node in patched.graph for node in patched.outputs.values())
    assert audit_graph(patched.graph).passed
    # no input points at a node that was pruned away
    for node in patched.graph.values():
        for value in node["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                assert value[0] in patched.graph


def test_the_committed_manifest_matches_what_the_workflows_really_load(samples):
    gen = load_script("gen_manifest")
    manifest = json.loads((ROOT / "openfield" / "engine" / "manifest.json").read_text(encoding="utf-8"))
    used = gen.models_used_by_our_workflows({m["name"] for m in manifest["models"]})
    assert used, "the real workflows must be found"
    for model in manifest["models"]:
        assert model["required"] == (model["name"] in used), model["name"]
        assert model["optional"] == (not model["required"])
        assert model["used_by"] == sorted(used.get(model["name"], ()))
    # the three files the official templates list only for their prompt enhancers are not loaded by ours
    unused = {m["name"] for m in manifest["models"] if not m["required"]}
    assert unused == {"gemma4_e2b_it_int8_convrot.safetensors",
                      "qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors",
                      "qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors"}
    # LTX image-to-video is two-stage: its latent upscaler is required, whatever its file name suggests
    upscaler = next(m for m in manifest["models"] if "latent-spatial-upscaler" in m["name"])
    assert upscaler["required"] and upscaler["used_by"] == ["ltx25_i2v"]


def test_the_download_plan_asks_for_exactly_the_required_files():
    fetch = load_script("fetch_template_models")
    manifest = ROOT / "openfield" / "engine" / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    required = {m["name"] for m in data["models"] if m["required"]}
    plan = fetch.plan_from_manifest(manifest, list(fetch.GROUPS), include_optional=False)
    assert {row["name"] for row in plan} == required and len(plan) == 14
    everything = fetch.plan_from_manifest(manifest, list(fetch.GROUPS), include_optional=True)
    assert len(everything) == len(data["models"])
    wan_only = fetch.plan_from_manifest(manifest, ["wan"], include_optional=False)
    assert {row["repo"] for row in wan_only} == {"Comfy-Org/Wan-Animate-2"} and len(wan_only) == 5


def test_stub_files_are_created_for_every_required_model_only(tmp_path):
    validate = load_script("validate_on_comfy")
    created = validate.stub_models(tmp_path)
    files = sorted(p.relative_to(tmp_path / "models").as_posix() for p in (tmp_path / "models").rglob("*.safetensors"))
    assert created == len(files) == 14
    assert "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors" in files
    assert not any("_pe_" in f or "gemma4_e2b" in f for f in files)
    assert all((tmp_path / "models" / f).stat().st_size == 0 for f in files)


def test_ltx_image_to_video_snaps_to_the_two_stage_multiple(samples):
    template = load_template("ltx25_i2v", WORKFLOW_DIR)
    values = sample_values(template, *samples) | {"width": 1280, "height": 720}
    patched = template.patch(values)
    assert patched.snapped == {"height": 704}
    assert patched.graph["398:372"]["inputs"]["value"] == 1280  # the resolution selector's wiring was replaced
    assert patched.graph["398:360"]["inputs"]["value"] == 704


def test_wan_animate_takes_two_prompts_and_a_frame_that_matches_the_clip(samples):
    template = load_template("wan_animate2", WORKFLOW_DIR)
    values = sample_values(template, *samples) | {
        "prompt": "Character Description: a courier\nBackground description: a street",
        "motion_prompt": "A person walks toward the camera.", "width": 854, "height": 482}
    graph = template.patch(values).graph
    assert graph["672:582"]["inputs"]["text"].startswith("Character Description: a courier")
    assert graph["672:585"]["inputs"]["text"] == "A person walks toward the camera."
    assert graph["672:600"]["inputs"]["resize_type.width"] == 854
    assert graph["672:600"]["inputs"]["resize_type.height"] == 482
    assert "292" not in graph and "246" in graph, "only the raw video is saved, not the side-by-side comparison"
    # without a motion prompt the neutral default applies; without a size the template's portrait size stays
    plain = template.patch({k: v for k, v in values.items() if k not in {"motion_prompt", "width", "height"}}).graph
    assert plain["672:585"]["inputs"]["text"].startswith("A person moving naturally")
    assert (plain["672:600"]["inputs"]["resize_type.width"], plain["672:600"]["inputs"]["resize_type.height"]) == (482, 854)


def test_qwen_edit_with_and_without_size_and_references(samples, tmp_path):
    template = load_template("qwen21_edit", WORKFLOW_DIR)
    ref = tmp_path / "ref.png"
    Image.new("RGB", (16, 16)).save(ref)
    base = sample_values(template, *samples)
    plain = template.patch(base).graph
    assert plain["459:468"]["inputs"]["switch"] is False
    assert "images.image_2" not in plain["459:474"]["inputs"] and "475" not in plain
    sized = template.patch(base | {"custom_size": True, "width": 1344, "height": 768, "refs": [ref]}).graph
    assert sized["459:468"]["inputs"]["switch"] is True
    assert (sized["459:456"]["inputs"]["width"], sized["459:456"]["inputs"]["height"]) == (1344, 768)
    assert sized["459:474"]["inputs"]["images.image_2"] == ["475_refs_0", 0]


def test_text_to_image_replaces_the_resolution_selector_with_exact_sizes(samples):
    template = load_template("qwen21_t2i", WORKFLOW_DIR)
    graph = template.patch(sample_values(template, *samples) | {"width": 1344, "height": 768}).graph
    assert "13" not in graph
    assert (graph["459:456"]["inputs"]["width"], graph["459:456"]["inputs"]["height"]) == (1344, 768)
    assert graph["459:474"]["inputs"]["switch"] is False
    assert graph["459:474"]["inputs"]["on_false"] == "sample", "the prompt goes in the switch's literal"


def test_validation_only_ever_removes_its_own_prompt_from_the_box(monkeypatch):
    """The box may be rendering someone else's job: never clear the queue, never interrupt blindly."""
    validate = load_script("validate_on_comfy")
    calls: list[tuple[str, object]] = []
    queue = {"queue_running": [[1, "someone-elses", {}, {}, []]], "queue_pending": []}

    def fake_request(base, path, body=None, **_):
        calls.append((path, body))
        return 200, queue if path == "/queue" and body is None else {}

    monkeypatch.setattr(validate, "request", fake_request)
    validate.stop_ours("http://box", "ours")  # still queued: deleted, not interrupted
    assert ("/queue", {"delete": ["ours"]}) in calls and not any(p == "/interrupt" for p, _ in calls)
    assert not any(isinstance(b, dict) and b.get("clear") for _, b in calls)

    calls.clear()
    queue["queue_running"] = [[2, "ours", {}, {}, []]]  # already started: that one prompt is interrupted
    monkeypatch.setattr(validate.time, "sleep", lambda _: None)
    validate.stop_ours("http://box", "ours")
    assert ("/interrupt", {"prompt_id": "ours"}) in calls
    calls.clear()
    validate.stop_ours("http://box", None)
    assert calls == []


# -- the video upscaler: the official Real-ESRGAN graph plus one resize ------------------------------------------------
def test_the_upscale_graph_is_the_official_chain_plus_one_image_scale():
    graph = json.loads((WORKFLOW_DIR / "esrgan_upscale.api.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "openfield" / "engine" / "manifest.json").read_text(encoding="utf-8"))
    official = manifest["templates"]["utility-gan_upscaler"]
    assert official["group"] == "esrgan" and official["models"] == ["RealESRGAN_x4plus.safetensors"]
    assert official["added_node_types"] == ["ImageScale"] and "ImageScale" not in official["node_types"]
    assert "ImageScale" in manifest["allowed_node_types"], "the added class is allowed, and said to be added"
    classes = sorted(node["class_type"] for node in graph.values())
    assert classes == sorted([*official["node_types"], "ImageScale"]), "exactly the classes of the template and the one resize"

    def node(cls):
        (found,) = [(key, n) for key, n in graph.items() if n["class_type"] == cls]
        return found

    load, get, loader, model, scale, create, save = (node(c) for c in (
        "LoadVideo", "GetVideoComponents", "UpscaleModelLoader", "ImageUpscaleWithModel", "ImageScale", "CreateVideo",
        "SaveVideo"))
    assert get[1]["inputs"]["video"] == [load[0], 0]
    assert model[1]["inputs"]["image"] == [get[0], 0] and model[1]["inputs"]["upscale_model"] == [loader[0], 0]
    assert scale[1]["inputs"]["image"] == [model[0], 0], "the resize reads the output of the model"
    assert create[1]["inputs"]["images"] == [scale[0], 0], "and the video is made from the resized frames"
    assert create[1]["inputs"]["fps"] == [get[0], 2] and create[1]["inputs"]["audio"] == [get[0], 1], "frame rate and sound pass through"
    assert save[1]["inputs"]["video"] == [create[0], 0]
    assert loader[1]["inputs"]["model_name"] == "RealESRGAN_x4plus.safetensors"
    assert scale[1]["inputs"]["crop"] == "disabled" and scale[1]["inputs"]["upscale_method"] == "area"


def test_re_exporting_the_official_template_adds_the_same_image_scale():
    export = load_script("export_templates")
    assert export.OFFICIAL["esrgan_upscale"] == "utility-gan_upscaler" and "esrgan_upscale" in export.AFTER_EXPORT
    committed = json.loads((WORKFLOW_DIR / "esrgan_upscale.api.json").read_text(encoding="utf-8"))
    plain = {k: v for k, v in committed.items() if v["class_type"] != "ImageScale"}  # what the frontend exports
    (create,) = [k for k, v in plain.items() if v["class_type"] == "CreateVideo"]
    (model,) = [k for k, v in plain.items() if v["class_type"] == "ImageUpscaleWithModel"]
    plain[create] = {**plain[create], "inputs": {**plain[create]["inputs"], "images": [model, 0]}}
    assert export.add_image_scale(plain) == committed
    assert "ImageScale" not in {v["class_type"] for v in plain.values()}, "the input is not changed"
    plain[create]["inputs"]["images"] = ["999", 0]
    with pytest.raises(ValueError, match="template changed"):
        export.add_image_scale(plain)


def test_the_upscale_slots_land_the_graph_on_the_requested_even_size(samples):
    template = load_template("esrgan_upscale", WORKFLOW_DIR)
    values = sample_values(template, *samples) | {"width": 3840, "height": 2112}
    patched = template.patch(values)
    assert sorted(patched.graph, key=int) == ["1", "2", "9", "10", "11", "12", "13"] and patched.outputs == {"video": "12"}
    assert patched.graph["13"]["inputs"] == {"upscale_method": "area", "width": 3840, "height": 2112, "crop": "disabled", "image": ["2", 0]}
    assert [(a.node, a.input, a.slot) for a in patched.assets] == [("9", "file", "video")] and patched.snapped == {}
    bicubic = template.patch(values | {"upscale_method": "bicubic"})
    assert bicubic.graph["13"]["inputs"]["upscale_method"] == "bicubic" and bicubic.sha256() != patched.sha256()
    odd = template.patch(values | {"width": 3841, "height": 2113})  # yuv420p needs even sides: snapped, and recorded
    assert (odd.graph["13"]["inputs"]["width"], odd.graph["13"]["inputs"]["height"]) == (3840, 2112)
    assert odd.snapped == {"width": 3840, "height": 2112}
    for bad in ({"width": 100}, {"height": 9000}, {"upscale_method": "lanczos"}):
        with pytest.raises(WorkflowError, match="between|must be one of"):
            template.patch(values | bad)
    for missing in ("width", "height", "video"):
        with pytest.raises(WorkflowError, match=f"missing required slot .{missing}."):
            template.patch({k: v for k, v in values.items() if k != missing})


def test_the_upscaler_is_a_registered_open_weights_file_with_its_licence_source_and_size():
    from openfield.engine import models

    info = models.model_info("RealESRGAN_x4plus.safetensors")
    assert info.open_weights and info.role == "upscaler:real-esrgan" and info.license_id == "bsd-3-clause"
    assert info.license_name == "BSD 3-Clause License" and info.attribution is None
    assert info.source == "https://huggingface.co/Comfy-Org/Real-ESRGAN_repackaged/resolve/main/RealESRGAN_x4plus.safetensors"
    manifest = json.loads((ROOT / "openfield" / "engine" / "manifest.json").read_text(encoding="utf-8"))
    (entry,) = [m for m in manifest["models"] if m["name"] == "RealESRGAN_x4plus.safetensors"]
    assert entry["directory"] == "upscale_models" and entry["required"] is True and entry["used_by"] == ["esrgan_upscale"]
    assert entry["bytes"] == 66_857_836 and entry["sha256"] == "37f9a931c215f040aa6d50f711f2cb115f713c46df1d0d6469a8bd7bfe9a60bb"
    # Hugging Face renamed the repository: both names carry the licence, so a template that follows the rename still audits
    assert models.REPO_LICENSE["Comfy-Org/Real-ESRGAN_repackaged"] == models.REPO_LICENSE["Comfy-Org/Real-ESRGAN"] == "bsd-3-clause"
    assert audit_graph(load_template("esrgan_upscale", WORKFLOW_DIR).graph).passed


def test_the_esrgan_group_downloads_the_one_upscaler_into_the_folder_comfyui_reads(tmp_path):
    fetch = load_script("fetch_template_models")
    manifest = ROOT / "openfield" / "engine" / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert fetch.GROUPS["esrgan"] == ["utility-gan_upscaler"] and "esrgan" in fetch.GROUP_OF.values()
    plan = fetch.plan_from_manifest(manifest, ["esrgan"], include_optional=False)
    assert [(row["name"], row["directory"], row["optional"]) for row in plan] == [("RealESRGAN_x4plus.safetensors", "upscale_models", False)]
    assert plan[0]["bytes"] == 66_857_836 and len(plan[0]["sha256"]) == 64
    assert fetch.KNOWN_FILES["RealESRGAN_x4plus.safetensors"] == {"bytes": plan[0]["bytes"], "sha256": plan[0]["sha256"]}
    # hf_hub_download writes the repository path under local_dir: for every file that must end up in models/DIRECTORY/NAME
    for model in data["models"]:
        assert fetch.download_root(tmp_path, model) / model["path"] == fetch.destination(tmp_path, model), model["name"]
    assert fetch.download_root(tmp_path, plan[0]) == tmp_path / "models" / "upscale_models", "the repository keeps this file at its root"
    wan = next(m for m in data["models"] if m["name"] == "wan_animate_2_int8_convrot.safetensors")
    assert fetch.download_root(tmp_path, wan) == tmp_path / "models", "the other repositories keep the directory in the path"
    wan_only = fetch.plan_from_manifest(manifest, ["wan"], include_optional=False)
    assert "RealESRGAN_x4plus.safetensors" not in {row["name"] for row in wan_only}
