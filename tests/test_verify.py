"""Tests for `openfield verify`: one command that prints every proof a judge would check."""
from __future__ import annotations

import json

from openfield.cli import main
from openfield.engine import quality
from openfield.engine import receipt as receipts
from openfield.engine.rig import (
    ANGLES_TESTED,
    AZIMUTHS,
    DISTANCES,
    EFFECT_IDS,
    ELEVATIONS,
    FROM_IMAGE_TESTED,
    MOVES,
    SINGLE_PASS,
    VALIDATED,
    VALIDATED_EFFECTS,
)
from openfield.engine.workflows import WORKFLOW_DIR
from openfield.verify import (
    check_models,
    check_proof_counts,
    check_receipts,
    check_replay,
    check_workflows,
)


def test_workflows_pass_on_real_templates():
    result = check_workflows(WORKFLOW_DIR)
    assert result.status == "ok"
    assert len(result.items) == 6
    assert all(i["passed"] for i in result.items)
    assert {i["template"] for i in result.items} == {
        "qwen21_t2i", "qwen21_edit", "ltx25_i2v", "ltx25_flf2v", "wan_animate2", "esrgan_upscale",
    }
    assert all(i["nodes_checked"] > 0 for i in result.items)


def test_receipts_count_one_good_and_one_tampered(tmp_path):
    takes = tmp_path / "takes"
    good = takes / "good_take"
    bad = takes / "bad_take"
    for folder in (good, bad):
        folder.mkdir(parents=True)

    sealed = receipts.seal(receipts.new_receipt(take_id="good_take", kind="direct"))
    (good / "receipt.json").write_text(json.dumps(sealed), encoding="utf-8")
    (good / "take.json").write_text(json.dumps({"id": "good_take"}), encoding="utf-8")

    forged = receipts.seal(receipts.new_receipt(take_id="bad_take", kind="direct"))
    forged["inputs"]["seed"] = 9999
    (bad / "receipt.json").write_text(json.dumps(forged), encoding="utf-8")
    (bad / "take.json").write_text(json.dumps({"id": "bad_take"}), encoding="utf-8")

    result = check_receipts(takes)
    assert result.status == "fail"
    assert "2 take(s), 1 seal(s) verified" in result.detail
    assert "first failure: bad_take" in result.detail
    items = {i["id"]: i for i in result.items}
    assert items["good_take"]["verified"] is True
    assert items["bad_take"]["verified"] is False


def test_receipts_skip_when_folder_is_missing_or_empty(tmp_path):
    missing = tmp_path / "no_takes"
    result = check_receipts(missing)
    assert result.status == "skip"
    assert "no bundled takes" in result.detail

    empty = tmp_path / "empty_takes"
    empty.mkdir()
    result = check_receipts(empty)
    assert result.status == "skip"
    assert "no bundled takes" in result.detail


def test_proof_counts_match_code_constants():
    result = check_proof_counts()
    assert result.status == "ok"
    item = result.items[0]
    assert item["moves_tested"] == len(VALIDATED)
    assert item["moves_total"] == len(MOVES)
    assert item["angles_tested"] == len(ANGLES_TESTED)
    assert item["angles_total"] == len(AZIMUTHS) * len(ELEVATIONS) * len(DISTANCES)
    assert item["effects_tested"] == len(VALIDATED_EFFECTS)
    assert item["effects_total"] == len([e for e in EFFECT_IDS if e != "none"])
    assert item["quality_tiers_tested"] == len(quality.VALIDATED_QUALITY)
    assert item["quality_tiers_total"] == len(quality.TIERS)
    assert item["from_image_tested"] == FROM_IMAGE_TESTED
    assert item["single_pass"] == SINGLE_PASS


def test_models_are_all_marked_open_weights():
    result = check_models()
    assert result.status == "ok"
    assert len(result.items) > 0
    assert all(i["open_weights"] for i in result.items)


def test_replay_refuses_an_unrecorded_recipe():
    result = check_replay(WORKFLOW_DIR)
    assert result.status == "ok"
    assert "refused" in result.detail
    assert result.items[0]["code"] == "replay_unavailable"


def test_verify_cli_passes_on_clean_tree(capsys):
    code = main(["verify"])
    captured = capsys.readouterr()
    assert code == 0
    assert "VERIFIED:" in captured.out
    assert captured.out.count("[ ok ]") + captured.out.count("[ -- ]") == 5


def test_verify_cli_json_output(capsys):
    code = main(["verify", "--json"])
    captured = capsys.readouterr()
    assert code == 0
    data = json.loads(captured.out)
    assert data["summary"]["failed"] == 0
    assert len(data["results"]) == 5
