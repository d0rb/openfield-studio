from __future__ import annotations

import pytest

from openfield.engine import preflight
from openfield.engine.workflows import load_template

from .fake_comfy_api import fake_object_info

STATS = {"system": {"comfyui_version": "0.41.0"},
         "devices": [{"name": "cuda:0 NVIDIA GeForce RTX 5090 : cudaMallocAsync",
                      "vram_total": 34_000_000_000, "vram_free": 30_500_000_000}]}


def test_every_workflow_is_ready_when_the_box_lists_every_file():
    result = preflight.assess(fake_object_info(), STATS)
    assert result["ok"] is True and result["summary"] == "6 of 6 workflows ready"
    assert all(row["state"] == "ready" and row["missing"] == [] for row in result["workflows"])
    assert result["comfyui"] == {"version": "0.41.0", "device": "NVIDIA GeForce RTX 5090",
                                 "vram_total_gb": 34.0, "vram_free_gb": 30.5}


def test_a_missing_file_names_the_workflows_it_breaks_and_where_to_get_it():
    result = preflight.assess(fake_object_info(missing={"wan_animate_2_int8_convrot.safetensors"}), None)
    rows = {row["name"]: row for row in result["workflows"]}
    assert result["ok"] is False and result["missing_files"] == ["wan_animate_2_int8_convrot.safetensors"]
    assert rows["wan_animate2"]["state"] == "missing" and len(rows["wan_animate2"]["missing"]) == 1
    gap = rows["wan_animate2"]["missing"][0]
    assert gap["directory"] == "diffusion_models" and gap["repo"] == "Comfy-Org/Wan-Animate-2"
    assert gap["url"].startswith("https://huggingface.co/") and "FETCH_ONLY=wan" in gap["hint"]
    assert all(rows[n]["state"] == "ready" for n in ("qwen21_t2i", "qwen21_edit", "ltx25_i2v", "ltx25_flf2v"))
    assert result["comfyui"] == {"version": None, "device": None, "vram_total_gb": None, "vram_free_gb": None}


def test_the_upscaler_file_is_asked_for_from_its_own_group():
    result = preflight.assess(fake_object_info(missing={"RealESRGAN_x4plus.safetensors"}), None)
    rows = {row["name"]: row for row in result["workflows"]}
    assert result["missing_files"] == ["RealESRGAN_x4plus.safetensors"]
    assert rows["esrgan_upscale"]["state"] == "missing" and rows["esrgan_upscale"]["label"] == "Real-ESRGAN, video upscale"
    gap = rows["esrgan_upscale"]["missing"][0]
    assert gap["directory"] == "upscale_models" and gap["repo"] == "Comfy-Org/Real-ESRGAN_repackaged"
    assert gap["hint"] == "FETCH_ONLY=esrgan bash /workspace/pod_setup.sh fetch"
    assert all(rows[n]["state"] == "ready" for n in rows if n != "esrgan_upscale")


def test_an_older_comfyui_reports_the_node_classes_it_lacks():
    info = fake_object_info()
    del info["LTXVAddGuide"]
    result = preflight.assess(info, STATS)
    rows = {row["name"]: row for row in result["workflows"]}
    assert rows["ltx25_flf2v"]["state"] == "unknown_nodes" and rows["ltx25_flf2v"]["unknown_nodes"] == ["LTXVAddGuide"]
    assert rows["qwen21_t2i"]["state"] == "ready"
    lines = preflight.report_lines(result)
    assert lines[0] == ("ok", "ComfyUI", "ComfyUI 0.41.0, NVIDIA GeForce RTX 5090, 34.0 GB")
    assert ("fail", "LTX 2.5, first and last frame to video", "this ComfyUI lacks: LTXVAddGuide") in lines


def test_model_inputs_find_the_files_a_patched_graph_loads():
    found = preflight.model_inputs(preflight.sample_graph(load_template("ltx25_flf2v")))
    files = {file for _node, _class, _input, file in found}
    assert "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors" in files
    assert "gemma4_e2b_it_int8_convrot.safetensors" not in files, "the pruned prompt enhancer is not demanded"


def test_urls_are_checked_before_anything_is_fetched():
    assert preflight.check_url(" http://127.0.0.1:9188/ ") == "http://127.0.0.1:9188"
    for bad in ("", "box:8188", "ftp://box", "http://u:p@box:8188", "http://box:8188/?a=1"):
        with pytest.raises(ValueError):
            preflight.check_url(bad)


async def test_probe_reports_a_box_that_is_not_there_without_raising(fake_api):
    result = await preflight.probe_comfy(fake_api.base_url)
    assert result["ok"] is True and result["state"] == "checked"
    down = await preflight.probe_comfy("http://127.0.0.1:9", timeout=2.0)
    assert down["ok"] is False and down["state"] == "unreachable" and "Could not reach" in down["summary"]
