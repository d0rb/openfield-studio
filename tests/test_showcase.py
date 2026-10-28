from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from openfield.backends.sdk import SdkBackend
from openfield.cast import CastStore
from openfield.cli import main as cli_main
from openfield.engine import receipt as receipts
from openfield.ledger import Ledger
from openfield.pipeline import Pipeline
from openfield.showcase import (
    SpecError,
    already_recorded,
    benchmarks_markdown,
    load_spec,
    plan_text,
    record,
    referenced_by,
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
             "prompt": "a woman with short dark hair", "background": "a rooftop at night", "seed": 9,
             "note": "Source footage rendered for the test; nobody was filmed."},
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
    assert "5 render(s)" in text and "total 5 ComfyUI render(s)" in text  # hero, three edited stills, one pass


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
    assert reshoot["notes"] == ["Source footage rendered for the test; nobody was filmed."]  # the spec's note travels with the take
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
    assert (world.out / forced[0].take_id).is_dir() and not (world.out / first[1].take_id).exists(),         "a forced re-render replaces the earlier recording of that entry"
    assert len(list(world.out.iterdir())) == 3

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


def test_a_partial_run_merges_into_the_report_instead_of_erasing_earlier_rows(tmp_path):
    from openfield.showcase import Outcome

    path = tmp_path / "report.json"
    first = [Outcome("mara-dolly", "direct", "succeeded", take_id="tk_1", seconds=120.0, runs=[{"stage": "hero"}]),
             Outcome("fx-rain", "direct", "succeeded", take_id="tk_2", seconds=170.0)]
    assert write_report(first, path, backend_label="GPU box")["summary"] == {"succeeded": 2, "failed": 0, "skipped": 0}

    # a later run with --only fx-rain: mara-dolly is reported as skipped by the CLI, fx-rain is re-rendered
    second = [Outcome("mara-dolly", "direct", "skipped", take_id="tk_1"),
              Outcome("fx-rain", "direct", "succeeded", take_id="tk_3", seconds=165.0),
              Outcome("fx-dust", "direct", "failed", error="boom")]
    report = write_report(second, path, backend_label="GPU box")
    rows = {t["name"]: t for t in report["takes"]}
    assert rows["mara-dolly"]["status"] == "succeeded" and rows["mara-dolly"]["seconds"] == 120.0, "the measured row survives"
    assert rows["fx-rain"]["take_id"] == "tk_3" and rows["fx-rain"]["seconds"] == 165.0, "a re-render replaces its own row"
    assert rows["fx-dust"]["status"] == "failed"
    assert report["summary"] == {"succeeded": 2, "failed": 1, "skipped": 0}
    assert json.loads(path.read_text(encoding="utf-8"))["summary"] == report["summary"]


async def test_a_spec_take_can_start_from_a_still_and_the_plan_does_not_count_it_as_a_render(world):
    from PIL import Image

    spec = good_spec()
    spec["takes"].append({"name": "mara-from-still", "kind": "direct", "cast": "Mara", "subject": "Mara on a pier at dusk",
                          "rig": {"movement": "dolly_in"}, "seed": 5, "source": "still.png"})
    world.spec_path.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(SpecError) as refused:
        load_spec(world.spec_path)
    assert any("source image not found" in p for p in refused.value.problems)

    Image.new("RGB", (640, 480), "orange").save(world.root / "still.png")
    loaded = load_spec(world.spec_path)
    plan = "\n".join(plan_text(loaded, {"mara-from-still"}))
    assert "mara-from-still" in plan and "2 render(s)" in plan and "from a still" in plan, "the hero is the given still"
    outcomes = await run(world, only={"mara-from-still"})
    done = {o.name: o for o in outcomes}["mara-from-still"]
    assert done.status == "succeeded" and (world.out / done.take_id / "inputs" / "hero.png").is_file(), "the still ships with the recorded take"
    assert [r["template"] for r in done.runs] == ["qwen21_edit", "ltx25_flf2v"]
    assert (world.root / "still.png").is_file(), "a spec file is never deleted"


def test_a_spec_take_names_its_quality_tier_and_a_bad_one_is_refused(world):
    spec = good_spec()
    spec["takes"][0]["quality"] = "fine"
    world.spec_path.write_text(json.dumps(spec), encoding="utf-8")
    plan = "\n".join(plan_text(load_spec(world.spec_path), {"mara-dolly"}))
    assert "fine quality" in plan
    spec["takes"][1]["quality"] = "ultra"
    world.spec_path.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(SpecError) as refused:
        load_spec(world.spec_path)
    assert any("unsupported quality" in p for p in refused.value.problems)


# -- round 7: a shots board and a transition, from takes recorded earlier ----------------------------------------
async def test_a_spec_board_and_bridge_start_from_takes_recorded_on_an_earlier_run(world, fake_api):
    spec = good_spec()
    spec["takes"] += [
        {"name": "mara-board", "kind": "shots", "from": "mara-dolly", "cast": "Mara", "seed": 3},
        {"name": "mara-bridge", "kind": "transition", "first": "mara-dolly", "second": "mara-quick", "style": "whip",
         "seconds": 2, "seed": 6},
    ]
    world.spec_path.write_text(json.dumps(spec), encoding="utf-8")
    loaded = load_spec(world.spec_path)
    plan = "\n".join(plan_text(loaded, {"mara-board", "mara-bridge"}))
    assert "mara-board" in plan and "9 render(s)" in plan and "9 setups from take mara-dolly" in plan
    assert "whip bridge, 2s, mara-dolly to mara-quick" in plan
    with_shelf = Pipeline(world.ledger, lambda: SdkBackend(base_url=fake_api.base_url), WORKFLOWS, timeout=60.0,
                          shelves=[world.out])
    world.pipeline = with_shelf
    outcomes = {o.name: o for o in await run(world)}
    assert outcomes["mara-board"].status == "succeeded", outcomes["mara-board"].error
    assert outcomes["mara-bridge"].status == "succeeded", outcomes["mara-bridge"].error
    board = json.loads((world.out / outcomes["mara-board"].take_id / "take.json").read_text(encoding="utf-8"))
    assert board["kind"] == "shots" and len(board["shots"]) == 9 and board["recipe"]["take"] == outcomes["mara-dolly"].take_id
    assert all((world.out / board["id"] / s["file"]).is_file() for s in board["shots"]), "the stills ship with the board"
    bridge = json.loads((world.out / outcomes["mara-bridge"].take_id / "take.json").read_text(encoding="utf-8"))
    assert bridge["recipe"]["first"] == outcomes["mara-dolly"].take_id and bridge["recipe"]["second"] == outcomes["mara-quick"].take_id


def test_bad_board_and_bridge_entries_are_all_reported(world):
    spec = good_spec()
    spec["takes"] += [
        {"name": "board-both", "kind": "shots", "from": "mara-dolly", "source": "x.png"},
        {"name": "board-none", "kind": "shots"},
        {"name": "bridge-same", "kind": "transition", "first": "mara-dolly", "second": "mara-dolly"},
        {"name": "bridge-style", "kind": "transition", "first": "mara-dolly", "second": "mara-quick", "style": "spin", "seconds": 9},
    ]
    world.spec_path.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(SpecError) as refused:
        load_spec(world.spec_path)
    text = "\n".join(refused.value.problems)
    assert "board-both" in text and "board-none" in text and "exactly one of 'from'" in text
    assert "bridge-same" in text and "must be different takes" in text
    assert "unknown style 'spin'" in text and "seconds must be one of" in text


# -- extend: continue a recorded take from its last frame --------------------------------------------------------------
async def test_a_spec_extension_starts_from_a_take_recorded_on_an_earlier_run(world, fake_api):
    spec = good_spec()
    spec["takes"] += [
        {"name": "mara-extend", "kind": "extend", "from": "mara-dolly", "seconds": 3, "seed": 6},
    ]
    world.spec_path.write_text(json.dumps(spec), encoding="utf-8")
    loaded = load_spec(world.spec_path)
    plan = "\n".join(plan_text(loaded, {"mara-extend"}))
    assert "mara-extend" in plan and "1 render(s)" in plan and "extend mara-dolly by 3s" in plan
    with_shelf = Pipeline(world.ledger, lambda: SdkBackend(base_url=fake_api.base_url), WORKFLOWS, timeout=60.0,
                          shelves=[world.out])
    world.pipeline = with_shelf
    outcomes = {o.name: o for o in await run(world)}
    assert outcomes["mara-extend"].status == "succeeded", outcomes["mara-extend"].error
    extended = json.loads((world.out / outcomes["mara-extend"].take_id / "take.json").read_text(encoding="utf-8"))
    assert extended["recipe"]["take"] == outcomes["mara-dolly"].take_id
    receipt = json.loads((world.out / outcomes["mara-extend"].take_id / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["inputs"]["take"]["sha256"] == receipts.sha256_file(world.out / outcomes["mara-dolly"].take_id / "take.mp4")
    assert [r["template"] for r in receipt["workflow"]["runs"]] == ["ltx25_i2v"]


def test_bad_extension_entries_are_reported(world):
    spec = good_spec()
    spec["takes"] += [
        {"name": "extend-bad-name", "kind": "extend", "from": "Mara Dolly", "seconds": 3},
        {"name": "extend-bad-seconds", "kind": "extend", "from": "mara-dolly", "seconds": 9},
    ]
    world.spec_path.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(SpecError) as refused:
        load_spec(world.spec_path)
    text = "\n".join(refused.value.problems)
    assert "extend-bad-name" in text and "'from' must be a take name" in text
    assert "extend-bad-seconds" in text and "seconds must be one of" in text


async def test_a_spec_edit_and_a_dub_start_from_recorded_takes(world, fake_api):
    spec = good_spec()
    spec["takes"] += [
        {"name": "mara-remove", "kind": "edit", "preset": "remove", "detail": "the lantern", "from": "mara-dolly", "seed": 3},
        {"name": "mara-dub", "kind": "direct", "from": "mara-dolly", "cast": "Mara", "subject": "Mara walks along a pier at dusk",
         "rig": {"movement": "static"}, "seed": 4, "line": "Hola, mar.", "language": "Spanish"},
    ]
    world.spec_path.write_text(json.dumps(spec), encoding="utf-8")
    plan = "\n".join(plan_text(load_spec(world.spec_path), {"mara-remove"}))
    assert "remove edit of take mara-dolly" in plan
    world.pipeline = Pipeline(world.ledger, lambda: SdkBackend(base_url=fake_api.base_url), WORKFLOWS, timeout=60.0, shelves=[world.out])
    outcomes = {o.name: o for o in await run(world)}
    assert outcomes["mara-remove"].status == "succeeded", outcomes["mara-remove"].error
    assert outcomes["mara-dub"].status == "succeeded", outcomes["mara-dub"].error
    dub = json.loads((world.out / outcomes["mara-dub"].take_id / "take.json").read_text(encoding="utf-8"))
    assert dub["recipe"]["language"] == "Spanish" and dub["recipe"]["source_sha256"]


async def test_a_spec_take_with_an_action_plans_and_records_it_and_a_bad_action_is_reported(world):
    spec = good_spec()
    action = "She turns to face the camera and smiles"
    spec["takes"].append({"name": "mara-turns", "kind": "direct", "cast": "Mara", "subject": "Mara stands on a pier at dusk",
                          "rig": {"movement": "static"}, "seed": 4, "action": action})
    world.spec_path.write_text(json.dumps(spec), encoding="utf-8")
    plan = "\n".join(plan_text(load_spec(world.spec_path), {"mara-turns"}))
    assert "mara-turns" in plan and "static (prompt_only), 5s" in plan
    done = {o.name: o for o in await run(world, only={"mara-turns"})}["mara-turns"]
    assert done.status == "succeeded", done.error
    take = json.loads((world.out / done.take_id / "take.json").read_text(encoding="utf-8"))
    assert take["recipe"]["action"] == action
    receipt = json.loads((world.out / done.take_id / "receipt.json").read_text(encoding="utf-8"))
    assert f"on a pier at dusk. {action}." in receipt["inputs"]["final_prompt"]

    for bad in (42, "x" * 301):
        spec["takes"][-1]["action"] = bad
        world.spec_path.write_text(json.dumps(spec), encoding="utf-8")
        with pytest.raises(SpecError) as refused:
            load_spec(world.spec_path)
        assert any(p.startswith("take 'mara-turns'") and "action" in p for p in refused.value.problems), bad


def test_a_named_take_is_found_in_the_run_or_on_a_shelf_that_ships(tmp_path):
    from openfield.ledger import write_json
    from openfield.showcase import recorded_id
    out, shelf = tmp_path / "out", tmp_path / "shipped"
    (shelf / "tk_20261020_120000_aaaa").mkdir(parents=True)
    (out / "tk_20261023_120000_bbbb").mkdir(parents=True)
    write_json(shelf / "tk_20261020_120000_aaaa" / "take.json", {"id": "tk_20261020_120000_aaaa", "status": "succeeded", "showcase_name": "dlg-mara", "created_at": "2026-10-20T12:00:00Z"})
    assert recorded_id(out, "dlg-mara", [shelf]) == "tk_20261020_120000_aaaa"
    with pytest.raises(ValueError):
        recorded_id(out, "dlg-mara")  # without the shelf it is not known
    write_json(out / "tk_20261023_120000_bbbb" / "take.json", {"id": "tk_20261023_120000_bbbb", "status": "succeeded", "showcase_name": "dlg-mara", "created_at": "2026-10-23T12:00:00Z"})
    assert recorded_id(out, "dlg-mara", [shelf]) == "tk_20261023_120000_bbbb", "the run's own recording wins"


async def test_a_forced_rerecord_keeps_what_others_still_use_and_moves_the_rest_aside(world):
    first = await run(world)
    old = first[1].take_id
    forced = await run(world, only={"mara-quick"}, force=True)
    assert not (world.out / old).exists() and (world.out.parent / "superseded" / old / "take.json").is_file(), \
        "nothing is deleted: the earlier recording is moved aside"
    # a recording built from the current take (here a hand-made board) keeps it on the shelf when its entry is re-recorded
    kept = forced[0].take_id
    board = world.out / "tk_board"
    board.mkdir()
    (board / "take.json").write_text(json.dumps({"id": "tk_board", "recipe": {"kind": "shots", "take": kept}}), encoding="utf-8")
    assert referenced_by(world.out, kept) == ["tk_board"]
    again = await run(world, only={"mara-quick"}, force=True)
    assert again[0].status == "succeeded" and (world.out / kept).is_dir(), "a take another recording uses is kept"


# -- an upscale of a take recorded earlier ---------------------------------------------------------------------------
async def test_a_spec_upscale_starts_from_a_take_recorded_on_an_earlier_run(world, fake_api):
    spec = good_spec()
    spec["takes"] += [{"name": "mara-4k", "kind": "upscale", "from": "mara-dolly", "target": "4k"}]
    world.spec_path.write_text(json.dumps(spec), encoding="utf-8")
    loaded = load_spec(world.spec_path)
    plan = "\n".join(plan_text(loaded, {"mara-4k"}))
    assert "mara-4k" in plan and "1 render(s)" in plan and "4k upscale of take mara-dolly" in plan
    world.pipeline = Pipeline(world.ledger, lambda: SdkBackend(base_url=fake_api.base_url), WORKFLOWS, timeout=60.0,
                              shelves=[world.out])
    outcomes = {o.name: o for o in await run(world, only={"mara-dolly", "mara-4k"})}
    assert outcomes["mara-4k"].status == "succeeded", outcomes["mara-4k"].error
    assert [r["template"] for r in outcomes["mara-4k"].runs] == ["esrgan_upscale"]
    shipped = json.loads((world.out / outcomes["mara-4k"].take_id / "take.json").read_text(encoding="utf-8"))
    assert shipped["kind"] == "upscale" and shipped["showcase_name"] == "mara-4k"
    assert shipped["recipe"] == {"kind": "upscale", "take": outcomes["mara-dolly"].take_id, "target": "4k"}
    assert (world.out / shipped["id"] / "take.mp4").is_file() and (world.out / shipped["id"] / "receipt.json").is_file()


def test_a_spec_upscale_defaults_to_4k_and_every_bad_entry_is_reported(world):
    spec = good_spec()
    spec["takes"] += [{"name": "mara-up", "kind": "upscale", "from": "mara-dolly"}]
    world.spec_path.write_text(json.dumps(spec), encoding="utf-8")
    assert "4k upscale of take mara-dolly" in "\n".join(plan_text(load_spec(world.spec_path), {"mara-up"}))
    spec["takes"] += [
        {"name": "up-target", "kind": "upscale", "from": "mara-dolly", "target": "8k"},
        {"name": "up-from", "kind": "upscale", "target": "2k"},
        {"name": "up-name", "kind": "upscale", "from": "Not A Name"},
        {"name": "up-kind", "kind": "uprez", "from": "mara-dolly"},
    ]
    world.spec_path.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(SpecError) as refused:
        load_spec(world.spec_path)
    text = "\n".join(refused.value.problems)
    assert "up-target" in text and "unknown target '8k' (one of 2k, 4k)" in text
    assert "up-from" in text and "up-name" in text and text.count("'from' must be a take name") == 2
    assert "kind must be 'direct', 'reshoot', 'shots', 'edit', 'transition', 'extend' or 'upscale'" in text


def test_a_slim_copy_drops_the_identity_check_frames(tmp_path):
    source = tmp_path / "src"
    (source / "runs" / "02_shoot_1").mkdir(parents=True)
    (source / "take.mp4").write_bytes(b"v")
    (source / "runs" / "02_shoot_1" / "preview.jpg").write_bytes(b"p")
    (source / "runs" / "02_shoot_1" / "identity_frame_last.png").write_bytes(b"i")
    slim_copy(source, tmp_path / "dst")
    assert (tmp_path / "dst" / "runs" / "02_shoot_1" / "preview.jpg").is_file()
    assert not (tmp_path / "dst" / "runs" / "02_shoot_1" / "identity_frame_last.png").exists()
