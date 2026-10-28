"""The pod-side and template scripts that can be checked without a GPU or a browser."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
WORKFLOWS = Path(__file__).resolve().parents[1] / "openfield" / "workflows"


def load(name: str):
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_validate_workflows_passes_the_mini_templates_and_fails_missing_ones(tmp_path, capsys):
    validate = load("validate_workflows")
    assert validate.main(["--dir", str(WORKFLOWS)]) == 0
    assert "6/6 templates usable" in capsys.readouterr().out
    assert validate.main(["--dir", str(tmp_path)]) == 1
    assert "[FAIL] ltx25_flf2v" in capsys.readouterr().out


def test_slot_ranges_are_checked_against_the_nodes_real_limits():
    from openfield.engine.workflows import load_template

    validate = load("validate_workflows")
    template = load_template("ltx25_flf2v", WORKFLOWS)
    # the node reports what ComfyUI itself would accept for this input
    roomy = {"PrimitiveInt": {"input": {"required": {"value": ["INT", {"min": 0, "max": 8192, "step": 1}]}}},
             "RandomNoise": {"input": {"required": {"noise_seed": ["INT", {"min": 0, "max": 2**64 - 1}]}}}}
    assert validate.check_ranges("ltx25_flf2v", template, roomy) == []

    tight = {"PrimitiveInt": {"input": {"required": {"value": ["INT", {"min": 640, "max": 1000, "step": 64}]}}},
             "RandomNoise": roomy["RandomNoise"]}
    problems = validate.check_ranges("ltx25_flf2v", template, tight)
    assert any("'width'" in p and "below the node's minimum 640" in p for p in problems)
    assert any("'width'" in p and "above the node's maximum 1000" in p for p in problems)
    assert any("'duration'" in p and "below the node's minimum 640" in p for p in problems)
    assert any("'width'" in p and "multiple_of 16 is not a multiple of the node's step 64" in p for p in problems)

    unknown = validate.check_ranges("ltx25_flf2v", template, {})
    assert unknown and all("unknown to ComfyUI" in p for p in unknown)
    # combos, text and nested inputs are skipped rather than guessed at
    text_only = {"PrimitiveInt": {"input": {"required": {"value": [["a", "b"]]}}}, "RandomNoise": roomy["RandomNoise"]}
    assert validate.check_ranges("ltx25_flf2v", template, text_only) == []


def test_export_script_suggests_slot_candidates_from_titles_and_classes():
    export = load("export_templates")
    graph = json.loads((WORKFLOWS / "ltx25_flf2v.api.json").read_text())
    found = export.candidates(graph)
    # titles come from the real template: the prompt primitive outranks the text encoder holding the negative prompt
    assert found["prompt"][0] == {"node": "251:252", "input": "value", "why": "PrimitiveStringMultiline 'Prompt'"}
    assert {"node": "31", "input": "image", "why": "LoadImage 'Load First Frame'"} in found["first_frame"]
    assert {"node": "39", "input": "image", "why": "LoadImage 'Load Last Frame'"} in found["last_frame"]
    assert found["duration"][0]["node"] == "251:198"
    assert found["output"][0]["node"] == "68" and found["seed"][0]["input"] == "noise_seed"

    qwen = export.candidates(json.loads((WORKFLOWS / "qwen21_t2i.api.json").read_text()))
    # the switch's literal is the prompt; the enhancer's system prompt is never suggested
    assert qwen["prompt"][0] == {"node": "459:474", "input": "on_false", "why": "ComfySwitchNode 'If/Else Switch'"}


def test_showcase_mid_strength_requires_single_pass(capsys):
    from openfield.cli import main

    with pytest.raises(SystemExit):
        main(["showcase", "--mid-strength", "0.5", "--dry-run"])
    assert "--mid-strength requires --single-pass" in capsys.readouterr().err
