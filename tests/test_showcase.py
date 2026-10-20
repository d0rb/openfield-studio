from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from openfield.backends.sdk import SdkBackend
from openfield.cast import CastStore
from openfield.cli import main as cli_main
from openfield.ledger import Ledger
from openfield.pipeline import Pipeline
from openfield.showcase import (
    SpecError,
    already_recorded,
    benchmarks_markdown,
    load_spec,
    plan_text,
    record,
    slim_copy,
    write_report,
)

from .test_pipeline import make_clip

WORKFLOWS = Path(__file__).resolve().parents[1] / "openfield" / "workflows"
DESCRIPTION = "a woman in her thirties with short dark hair and a navy wool coat"


def good_spec(clip_name: str = "clip.mp4") -> dict:
    return {
        "casts": [{"name": "Mara", "description": DESCRIPTION, "count": 2, "pick": 2, "seed": 11}],
        "takes": [
            {"name": "mara-dolly", "kind": "direct", "cast": "Mara", "subject": "Mara walks along a pier at dusk",
             "rig": {"movement": "dolly_in"}, "seed": 4, "audio": "waves and gulls"},
            {"name": "mara-quick", "kind": "direct", "cast": "Mara", "subject": "Mara walks along a pier at dusk",
             "rig": {"movement": "dolly_in"}, "seed": 4, "prompt_only": True},
            {"name": "reshoot-mara", "kind": "reshoot", "source": clip_name, "cast": "Mara",
             "prompt": "a woman with short dark hair", "background": "a rooftop at night", "seed": 9},
        ],
    }


@pytest.fixture
def world(tmp_path, fake_api):
    make_clip(tmp_path / "clip.mp4")
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(good_spec()), encoding="utf-8")
    ledger = Ledger(tmp_path / "work" / "takes")
    casts = CastStore(tmp_path / "work" / "cast")
    backend = SdkBackend(base_url=fake_api.base_url)
    pipeline = Pipeline(ledger, lambda: backend, WORKFLOWS, timeout=60.0)
    return SimpleNamespace(root=tmp_path, spec_path=spec_path, ledger=ledger, casts=casts, pipeline=pipeline,
                           out=tmp_path / "out", log=[])


async def run(world, **kwargs):
    spec = load_spec(world.spec_path)
    return await record(spec, world.pipeline, world.ledger, world.casts, world.out,
                        log=world.log.append, **kwargs)


# -- the spec ------------------------------------------------------------------------------------

def test_a_good_spec_loads(world):
    spec = load_spec(world.spec_path)
    assert [c.name for c in spec.casts] == ["Mara"] and [t.name for t in spec.takes] == [
        "mara-dolly", "mara-quick", "reshoot-mara"]
    assert spec.takes[0].sha != spec.takes[1].sha and len(spec.takes[0].sha) == 16


def test_every_problem_in_a_bad_spec_is_reported_at_once(tmp_path):
    bad = {
        "casts": [{"name": "Mara", "description": "ab", "count": 2, "pick": 3},
                  {"name": "Mara", "description": "a calm sailor", "count": 9},
                  {"name": "Nude", "description": "a nude figure study"}],
        "takes": [
            {"name": "Bad Name", "kind": "direct", "subject": "A lighthouse", "rig": {"movement": "teleport"}},
            {"name": "ok-one", "kind": "direct", "subject": "two people having sex", "rig": {}},
            {"name": "no-cast", "kind": "direct", "cast": "Ghost", "subject": "A calm sea", "rig": {}},
            {"name": "ok-one", "kind": "reshoot", "source": "missing.mp4", "prompt": "x"},
            {"name": "weird", "kind": "remix"},
        ],
    }
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(SpecError) as info:
        load_spec(path)
    text = "\n".join(info.value.problems)
    for fragment in ("count must be 1 to 4", "pick must be between", "duplicate cast name", "safe-for-work",
                     "name must be lowercase", "cast 'Ghost' is not defined", "duplicate take name",
                     "source clip not found", "give a cast or a reference image", "kind must be"):
        assert fragment in text, fragment
    assert len(info.value.problems) >= 10
    with pytest.raises(SpecError, match="cannot read"):
        load_spec(tmp_path / "nowhere.json")
    path.write_text(json.dumps({"takes": []}), encoding="utf-8")
    with pytest.raises(SpecError, match="no takes"):
        load_spec(path)


def test_the_plan_counts_renders_and_only_the_casts_that_are_needed(world):
    spec = load_spec(world.spec_path)
    text = "\n".join(plan_text(spec))
    assert "cast  Mara" in text and "2 portrait render(s)" in text
    assert "mara-dolly" in text and "dolly_in (keyframed), 5s" in text and "mara-quick" in text
    # 2 portraits + dolly (hero, anchor, one segment = 3) + quick (hero, one segment = 2) + reshoot 1
    assert "total 8 ComfyUI render(s)" in text
    only = "\n".join(plan_text(spec, {"reshoot-mara"}))
    assert "total 3 ComfyUI render(s)" in only
    assert "cast  Mara" in only, "the re-shoot uses Mara's portrait as its reference"


def test_a_full_orbit_reuses_its_hero_still_so_that_anchor_is_not_counted_as_a_render(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({"takes": [{
        "name": "bottle-orbit", "kind": "direct", "subject": "A glass bottle on a table",
        "rig": {"movement": "orbit_360", "duration_seconds": 8}}]}), encoding="utf-8")
    text = "\n".join(plan_text(load_spec(spec_path)))
    # hero + three edited anchors (the fifth anchor is the hero again) + four first-and-last-frame shots
    assert "8 render(s)" in text and "total 8 ComfyUI render(s)" in text


# -- recording -----------------------------------------------------------------------------------

async def test_recording_generates_the_cast_once_renders_every_take_and_keeps_slim_folders(world):
    outcomes = await run(world)
    assert [o.status for o in outcomes] == ["succeeded"] * 3
    portraits = world.ledger.list(kind="portrait")
    assert len(portraits) == 1, "one cast, generated once, shared by three takes"
    cast = world.casts.list()[0]
    assert cast["name"] == "Mara" and cast["consent"] == "fictional" and cast["origin"]["seed"] == 12

    assert sorted(p.name for p in world.out.iterdir()) == sorted(o.take_id for o in outcomes)
    for outcome in outcomes:
        folder = world.out / outcome.take_id
        take = json.loads((folder / "take.json").read_text())
        assert take["showcase_name"] == outcome.name and take["status"] == "succeeded"
        assert (folder / "take.mp4").is_file() and (folder / "receipt.json").is_file()
        assert list(folder.glob("runs/*/workflow.api.json")), "the graphs travel with the take"
        assert not list(folder.glob("runs/*/*.mp4")), "intermediate per-step video is dropped"
        assert not list(folder.rglob("*.tmp"))
        assert outcome.seconds and outcome.runs and outcome.media_bytes > 0
    reshoot = json.loads((world.out / outcomes[2].take_id / "take.json").read_text())
    assert reshoot["recipe"]["background"] == "a rooftop at night"
    assert (world.out / outcomes[2].take_id / "inputs" / "source.mp4").is_file()
    assert [r["template"] for r in outcomes[1].runs] == ["qwen21_edit", "ltx25_i2v"]


async def test_recording_is_resumable_and_follows_spec_changes(world):
    first = await run(world)
    again = await run(world)
    assert [o.status for o in again] == ["skipped"] * 3
    assert [o.take_id for o in again] == [o.take_id for o in first]
    assert len(world.ledger.list(kind="direct")) == 2, "nothing was re-rendered"

    forced = await run(world, only={"mara-quick"}, force=True)
    assert forced[0].status == "succeeded" and forced[0].take_id != first[1].take_id

    changed = good_spec()
    changed["takes"][0]["seed"] = 99
    world.spec_path.write_text(json.dumps(changed), encoding="utf-8")
    spec = load_spec(world.spec_path)
    assert already_recorded(world.out, spec.takes[0]) is None, "a changed entry is not 'already recorded'"
    assert already_recorded(world.out, spec.takes[2]) == first[2].take_id


async def test_one_failing_take_does_not_stop_the_rest_and_is_reported(world):
    spec = good_spec()
    spec["takes"][2]["source"] = "not-a-video.mp4"  # exists, but ffmpeg cannot read it
    (world.root / "not-a-video.mp4").write_text("this is not a video")
    world.spec_path.write_text(json.dumps(spec), encoding="utf-8")
    outcomes = await run(world)
    assert [o.status for o in outcomes] == ["succeeded", "succeeded", "failed"]
    assert outcomes[2].error and outcomes[2].take_id
    assert not (world.out / outcomes[2].take_id).exists(), "a failed take is not copied into the showcase"

    report = write_report(outcomes, world.root / "report.json", backend_label="GPU box")
    assert report["summary"] == {"succeeded": 2, "failed": 1, "skipped": 0}
    assert json.loads((world.root / "report.json").read_text())["takes"][2]["status"] == "failed"
    table = benchmarks_markdown(report)
    assert "mara-dolly" in table and "qwen21_t2i" not in table.split("Not recorded")[0].split("mara-quick")[0]
    assert "Not recorded: reshoot-mara" in table and "Measured on **GPU box**" in table


async def test_a_cast_that_cannot_be_made_fails_its_takes_without_crashing(world, fake_api):
    fake_api.fail_with = {"code": "node_execution_error", "message": "CUDA out of memory",
                          "node_id": "459:458", "class_type": "KSampler"}
    outcomes = await run(world)
    assert [o.status for o in outcomes] == ["failed"] * 3
    assert all("could not be made" in (o.error or "") for o in outcomes)
    assert any("failed" in line for line in world.log)
    assert world.casts.list() == []


async def test_unknown_names_in_only_are_refused_before_anything_renders(world):
    with pytest.raises(SpecError, match="no such take: nope"):
        await run(world, only={"nope"})
    assert world.ledger.list() == []


# -- slimming ------------------------------------------------------------------------------------

def test_slim_copy_keeps_what_replay_needs_and_drops_step_video(tmp_path):
    src = tmp_path / "src"
    for rel, size in {
        "take.json": 10, "receipt.json": 10, "take.mp4": 400, "poster.png": 5, "events.jsonl": 5,
        "inputs/source.mp4": 100, "candidates/01.png": 5,
        "runs/01_hero/image.png": 5, "runs/01_hero/preview.jpg": 5, "runs/01_hero/video.mp4": 900,
        "runs/01_hero/workflow.api.json": 5, "runs/01_hero/run.json": 5, "runs/01_hero/events.jsonl": 50,
        "runs/01_hero/preview.jpg.tmp": 5, "runs/01_hero/deep/extra.png": 5,
    }.items():
        path = src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "stale.txt").write_text("from an earlier copy")
    kept = slim_copy(src, dst)
    names = sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file())
    assert names == ["candidates/01.png", "events.jsonl", "inputs/source.mp4", "poster.png", "receipt.json",
                     "runs/01_hero/image.png", "runs/01_hero/preview.jpg", "runs/01_hero/run.json",
                     "runs/01_hero/workflow.api.json", "take.json", "take.mp4"]
    assert kept == sum((dst / n).stat().st_size for n in names) and kept < 1000


# -- the command ---------------------------------------------------------------------------------

def test_cli_dry_run_prints_the_plan_and_bad_specs_list_every_problem(world, capsys, monkeypatch):
    monkeypatch.delenv("COMFY_BASE_URL", raising=False)
    monkeypatch.delenv("COMFY_API_KEY", raising=False)
    assert cli_main(["showcase", "--spec", str(world.spec_path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Plan:" in out and "total 8 ComfyUI render(s)" in out

    assert cli_main(["showcase", "--spec", str(world.spec_path)]) == 1
    assert "COMFY_BASE_URL" in capsys.readouterr().err

    assert cli_main(["showcase", "--spec", str(world.spec_path), "--dry-run", "--only", "nope"]) == 1
    assert "no such take: nope" in capsys.readouterr().err

    world.spec_path.write_text(json.dumps({"takes": [{"name": "A B", "kind": "x"}]}), encoding="utf-8")
    assert cli_main(["showcase", "--spec", str(world.spec_path), "--dry-run"]) == 1
    err = capsys.readouterr().err
    assert "The spec has problems" in err and "name must be lowercase" in err


def test_cli_records_through_the_configured_backend(world, fake_api, capsys, monkeypatch):
    monkeypatch.setenv("COMFY_BASE_URL", fake_api.base_url)
    code = cli_main(["showcase", "--spec", str(world.spec_path), "--out", str(world.out),
                     "--work-dir", str(world.root / "cli-work"), "--benchmarks", str(world.root / "bench.md")])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "3 recorded, 0 skipped, 0 failed" in out
    report = json.loads((world.root / "report.json").read_text())
    assert report["backend"] == "GPU box" and report["summary"]["succeeded"] == 3
    assert "mara-dolly" in (world.root / "bench.md").read_text()
    again = cli_main(["showcase", "--spec", str(world.spec_path), "--out", str(world.out),
                      "--work-dir", str(world.root / "cli-work")])
    assert again == 0 and "0 recorded, 3 skipped" in capsys.readouterr().out
    shutil.rmtree(world.root / "cli-work")
