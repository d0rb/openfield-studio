from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import imageio_ffmpeg
import pytest
from PIL import Image, ImageChops, ImageOps, ImageStat

from openfield.backends.base import BackendError
from openfield.backends.replay import ReplayBackend
from openfield.backends.sdk import SdkBackend
from openfield.engine import receipt as receipts
from openfield.engine import video
from openfield.engine.rig import UPSCALE_TARGETS
from openfield.ledger import Ledger
from openfield.pipeline import (
    DirectRequest,
    EditRequest,
    ExtendRequest,
    Pipeline,
    PortraitRequest,
    ReshootRequest,
    ShotsRequest,
    TransitionRequest,
    UpscaleRequest,
    upscale_size,
)

WORKFLOWS = Path(__file__).resolve().parents[1] / "openfield" / "workflows"


@dataclass
class Stack:
    ledger: Ledger
    pipeline: Pipeline
    root: Path


class StubGate:
    """Scripted face check: yields the given statuses in order, then 'pass'."""

    def __init__(self, statuses: list[str]) -> None:
        self.statuses = list(statuses)
        self.calls = 0

    def check(self, refs, image):
        self.calls += 1
        status = self.statuses.pop(0) if self.statuses else "pass"
        score = {"pass": 0.71, "drift": 0.12}.get(status)
        report = {"status": status, "score": score, "threshold": 0.363, "refs_used": len(refs)}
        return SimpleNamespace(to_dict=lambda: report)


@pytest.fixture
def stack(tmp_path, fake_api) -> Stack:
    ledger = Ledger(tmp_path / "takes")
    backend = SdkBackend(base_url=fake_api.base_url)
    return Stack(ledger, Pipeline(ledger, lambda: backend, WORKFLOWS, timeout=60.0), tmp_path)


def make_image(path: Path, color: str = "red") -> Path:
    Image.new("RGB", (96, 54), color).save(path)
    return path


def make_clip(path: Path, seconds: int = 3) -> Path:
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=24:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
        check=True)
    return path


async def until(predicate, timeout: float = 20.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if value := predicate():
            return value
        await asyncio.sleep(0.05)
    raise AssertionError("condition not reached in time")


def direct(**overrides) -> DirectRequest:
    base = {"subject": "A lighthouse at dusk", "rig": {"movement": "dolly_in"}, "seed": 7,
            "auto_approve": True}
    return DirectRequest(**(base | overrides))


async def test_keyframed_direct_take_runs_all_stages_and_seals_a_receipt(stack):
    take = await stack.pipeline.start_direct(direct())
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    folder = stack.ledger.take_dir(take["id"])

    assert done["status"] == "succeeded" and done["progress"] == 1.0 and done["error"] is None
    assert [o["role"] for o in done["outputs"]] == ["video", "poster", "receipt"]
    runs = sorted(p.name for p in (folder / "runs").iterdir())
    assert runs == ["01_hero", "02_anchor_1", "03_shoot_1"]
    for run in (folder / "runs").iterdir():
        assert (run / "workflow.api.json").is_file() and (run / "run.json").is_file()

    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    assert receipts.verify(receipt)
    assert receipt["audit"] == {"policy": "open-weights-only", "result": "pass", "disallowed": []}
    assert {m["role"] for m in receipt["models"]} >= {"video:ltx-2.5", "image:qwen-image-2.1"}
    assert any(m["attribution"] == "Built with Qwen" for m in receipt["models"])
    assert receipt["inputs"]["final_prompt"].startswith("A lighthouse at dusk.")
    assert receipt["inputs"]["move"] == "dolly_in" and receipt["inputs"]["seed"] == 7
    assert [r["template"] for r in receipt["workflow"]["runs"]] == ["qwen21_t2i", "qwen21_edit", "ltx25_flf2v"]
    assert str(stack.root) not in json.dumps(receipt)  # no machine paths leak into a shareable file

    found, verified = receipts.read_media(folder / "take.mp4")
    assert verified and found["take"]["id"] == take["id"]  # embedded in the video itself
    assert video.probe(folder / "take.mp4").duration_s > 0


async def test_quick_mode_skips_anchor_stills_and_is_part_of_the_recipe(stack):
    full = await stack.pipeline.start_direct(direct())
    quick = await stack.pipeline.start_direct(direct(prompt_only=True))
    await stack.pipeline.wait(full["id"])
    await stack.pipeline.wait(quick["id"])
    runs = sorted(p.name for p in (stack.ledger.take_dir(quick["id"]) / "runs").iterdir())
    assert runs == ["01_hero", "02_shoot_1"], "one still, then image-to-video: no anchor edit, no first-last-frame"
    done_full, done_quick = stack.ledger.read(full["id"]), stack.ledger.read(quick["id"])
    assert done_full["recipe_hash"] != done_quick["recipe_hash"]
    assert done_quick["recipe"]["prompt_only"] is True and "prompt_only" not in done_full["recipe"]
    assert "effect" not in done_full["recipe"]["rig"], "no effect means no key, so recipes made before effects keep their fingerprint"
    receipt = json.loads((stack.ledger.take_dir(quick["id"]) / "receipt.json").read_text(encoding="utf-8"))
    assert [r["template"] for r in receipt["workflow"]["runs"]] == ["qwen21_t2i", "ltx25_i2v"]
    assert receipt["inputs"]["mode"] == "prompt_only"


def test_an_effect_is_part_of_the_recipe_only_when_one_is_set():
    from openfield.engine.rig import CameraRig
    from openfield.pipeline import recipe_rig
    assert "effect" not in recipe_rig(CameraRig())
    assert recipe_rig(CameraRig(effect="rain"))["effect"] == "rain"
    assert recipe_rig(CameraRig(effect="rain")) != recipe_rig(CameraRig())


async def test_events_cover_stages_runs_and_end(stack):
    take = await stack.pipeline.start_direct(direct(rig={"movement": "static"}))
    seen = [e async for e in stack.pipeline.subscribe(take["id"])]
    kinds = {e["type"] for e in seen}
    assert {"take", "stage", "run", "end"} <= kinds and seen[-1] == {**seen[-1], "type": "end", "status": "succeeded"}
    stages = [e["stage"] for e in seen if e["type"] == "stage" and e["state"] == "start"]
    assert stages == ["hero", "shoot_1", "finish"]  # static = one hero still, then image-to-video
    late = [e async for e in stack.pipeline.subscribe(take["id"])]  # history replays for a late joiner
    assert late[-1]["type"] == "end"


async def test_approval_gate_lets_the_user_reroll_an_anchor(stack):
    take = await stack.pipeline.start_direct(direct(auto_approve=False))
    waiting = await until(lambda: (t := stack.ledger.read(take["id"]))["status"] == "awaiting_approval" and t)
    assert [a["index"] for a in waiting["anchors"]] == [0, 1]
    first_count = len(list((stack.ledger.take_dir(take["id"]) / "runs").iterdir()))
    stack.pipeline.approve(take["id"], reroll=[1])
    await until(lambda: len(list((stack.ledger.take_dir(take["id"]) / "runs").iterdir())) > first_count)
    await until(lambda: stack.ledger.read(take["id"])["status"] == "awaiting_approval")
    stack.pipeline.approve(take["id"], reroll=[])
    await stack.pipeline.wait(take["id"])
    assert stack.ledger.read(take["id"])["status"] == "succeeded"
    with pytest.raises(ValueError, match="not waiting"):
        stack.pipeline.approve(take["id"])


async def test_a_late_joiner_replaying_history_ends_on_the_right_status_after_an_approval(stack):
    """The interface replays a take's events on every connection. If an approval's resume left no snapshot,
    it would end the replay on 'awaiting approval' and ask the person to approve a take that is already working.
    A re-roll is the case that matters: stills render again with no stage change to announce it."""
    take = await stack.pipeline.start_direct(direct(auto_approve=False))
    await until(lambda: stack.ledger.read(take["id"])["status"] == "awaiting_approval")
    runs = lambda: len(list((stack.ledger.take_dir(take["id"]) / "runs").iterdir()))  # noqa: E731
    before = runs()
    stack.pipeline.approve(take["id"], reroll=[1])
    await until(lambda: runs() > before)  # the anchor is being rendered again
    snapshots = [e["take"]["status"] for e in stack.pipeline.bus.history(take["id"]) if e["type"] == "take"]
    assert snapshots[-1] == "running", "a late joiner must learn the re-roll is under way"
    await until(lambda: stack.ledger.read(take["id"])["status"] == "awaiting_approval")
    stack.pipeline.approve(take["id"])
    await stack.pipeline.wait(take["id"])
    final = [e["take"]["status"] for e in stack.pipeline.bus.history(take["id"]) if e["type"] == "take"]
    assert final[-1] == "succeeded"
    stages = [e["take"]["stage"] for e in stack.pipeline.bus.history(take["id"]) if e["type"] == "take"]
    assert any(s and s.startswith("shoot") for s in stages), "the shoot stage reaches late joiners too"


async def test_the_live_stream_keeps_warm_and_cleans_up_when_the_client_leaves(stack):
    take = stack.ledger.create("direct", "idle", {"kind": "direct"})  # nothing is running it
    seen: list[object] = []

    async def consume():
        async for event in stack.pipeline.subscribe(take["id"], keepalive=0.05):
            seen.append(event)

    task = asyncio.create_task(consume())
    await until(lambda: len(seen) >= 2)
    assert seen[:2] == [None, None], "a quiet take still sends keepalives"
    assert stack.pipeline.bus._queues[take["id"]], "the client is subscribed while it listens"
    task.cancel()  # the browser went away
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not stack.pipeline.bus._queues[take["id"]], "its queue is released, not leaked"


async def test_a_take_whose_failure_could_not_be_recorded_is_still_marked_failed_and_logged(stack, caplog):
    """If writing the failure itself loses a race (a Windows file lock), the task dies with an exception nobody
    sees, because the task is kept for the take's life. The take must not stay 'running' for ever."""
    take = stack.ledger.create("direct", "doomed", {"kind": "direct"})
    stack.ledger.update(take["id"], status="running")
    real_finish = stack.pipeline._finish
    calls: list[str] = []

    def flaky_finish(take_id, status, error):
        calls.append(status)
        if len(calls) == 1:
            raise PermissionError("the file is in use")
        return real_finish(take_id, status, error)

    stack.pipeline._finish = flaky_finish

    async def boom():
        raise RuntimeError("the renderer fell over")

    with caplog.at_level("ERROR", logger="openfield.pipeline"):
        stack.pipeline._spawn(stack.ledger.read(take["id"]), boom())
        with pytest.raises(PermissionError):
            await stack.pipeline._tasks[take["id"]]
        await asyncio.sleep(0.05)  # the done-callback runs on the next turns of the loop
    assert "unhandled PermissionError" in caplog.text
    done = stack.ledger.read(take["id"])
    assert done["status"] == "failed" and "PermissionError" in done["error"]["message"]


async def test_a_take_waiting_for_the_gpu_says_so(stack):
    """With one GPU slot, the second take waits behind the first. The Monitor must show that it is queued,
    not an idle 'working', so the app announces it before the backend has been asked for anything."""
    first = await stack.pipeline.start_direct(direct(rig={"movement": "static"}, prompt_only=True, auto_approve=True))
    second = await stack.pipeline.start_direct(direct(rig={"movement": "static"}, prompt_only=True, auto_approve=True))
    await stack.pipeline.wait(first["id"])
    await stack.pipeline.wait(second["id"])

    def waits(take_id):
        return [e for e in stack.pipeline.bus.history(take_id)
                if e["type"] == "run" and e["event"].get("kind") == "status" and e["event"].get("queue_position") is None
                and e["event"].get("status") == "queued" and "t" not in e["event"]]

    assert len(waits(first["id"])) + len(waits(second["id"])) >= 1, "someone waited for the other"
    waiting = waits(second["id"]) or waits(first["id"])
    history = stack.pipeline.bus.history(second["id"] if waits(second["id"]) else first["id"])
    first_backend = next(i for i, e in enumerate(history) if e["type"] == "run" and e["event"].get("kind") == "uploading")
    assert history.index(waiting[0]) < first_backend, "it is announced before the backend is asked for anything"


async def test_single_pass_records_mid_strength_and_patches_the_workflow(stack, monkeypatch):
    from openfield.engine import rig

    monkeypatch.setattr(rig, "SINGLE_PASS", True)
    monkeypatch.setattr(rig, "MID_GUIDE_STRENGTH", 0.35)
    take = await stack.pipeline.start_direct(direct(rig={"movement": "orbit_360", "duration_seconds": 5}))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "succeeded", done.get("error")
    folder = stack.ledger.take_dir(take["id"])
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["inputs"]["segments"][0]["guides"][0]["strength"] == 0.35
    shot = json.loads((folder / "runs" / "05_shoot_1" / "workflow.api.json").read_text(encoding="utf-8"))
    assert shot["251:204_mids_0"]["inputs"]["strength"] == 0.35


async def test_full_orbit_joins_four_segments(stack, monkeypatch):
    from openfield.engine import rig as rig_module

    monkeypatch.setattr(rig_module, "SINGLE_PASS", False)  # the segmented path, still available behind the flag
    take = await stack.pipeline.start_direct(direct(rig={"movement": "orbit_360", "duration_seconds": 5}))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "succeeded"
    folder = stack.ledger.take_dir(take["id"])
    shoots = [p for p in (folder / "runs").iterdir() if "shoot" in p.name]
    assert len(shoots) == 4
    assert video.probe(folder / "take.mp4").duration_s > 3.0  # four 1s fake clips joined
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["inputs"]["anchors"][-1]["index"] == 4  # the loop closes on the hero frame


async def test_identity_drift_triggers_exactly_one_reroll_and_keeps_the_better_still(stack, tmp_path):
    refs = [make_image(tmp_path / "ref.png")]
    stack.pipeline.gate = StubGate(["drift", "pass"])  # hero drifts, the re-roll passes
    take = await stack.pipeline.start_direct(direct(rig={"movement": "static"}, cast_refs=refs, cast_name="Mara"))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "succeeded"
    stages = sorted(p.name for p in (stack.ledger.take_dir(take["id"]) / "runs").iterdir())
    assert "02_hero_retry" in stages and len([s for s in stages if "retry" in s]) == 1
    assert done["identity"]["hero"]["retried"] is True and done["identity"]["hero"]["status"] == "pass"
    receipt = json.loads((stack.ledger.take_dir(take["id"]) / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["identity"]["status"] == "pass" and receipt["identity"]["refs_used"] == 1


async def test_the_face_check_may_be_a_live_provider_so_late_downloads_take_effect(stack, tmp_path):
    gates: list[StubGate] = []

    def provider():
        gates.append(StubGate([]))  # a fresh, "newly available" gate on every call
        return gates[-1]

    stack.pipeline.gate = provider
    refs = [make_image(tmp_path / "ref.png")]
    take = await stack.pipeline.start_direct(direct(rig={"movement": "static"}, cast_refs=refs))
    await stack.pipeline.wait(take["id"])
    assert stack.ledger.read(take["id"])["identity"]["hero"]["status"] == "pass"
    assert gates and sum(g.calls for g in gates) == 4, "the hero still and the rendered shot (three frames) are all checked"


async def test_the_shot_is_checked_too_and_a_drifting_shot_is_reported_not_re_rendered(stack, tmp_path):
    refs = [make_image(tmp_path / "ref.png")]
    gate = StubGate(["pass", "drift", "drift", "drift"])  # the hero holds; the shot drifts on all three frames checked
    stack.pipeline.gate = gate
    take = await stack.pipeline.start_direct(direct(rig={"movement": "static"}, cast_refs=refs, cast_name="Mara"))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    folder = stack.ledger.take_dir(take["id"])
    assert done["status"] == "succeeded" and gate.calls == 4  # the hero still, then the shot's first, middle and last frame
    assert done["identity"]["shoot_1"]["frames_checked"] == 3
    assert done["identity"]["hero"]["status"] == "pass" and done["identity"]["shoot_1"]["status"] == "drift"
    runs = sorted(p.name for p in (folder / "runs").iterdir())
    assert not any("retry" in r for r in runs), "a video is never re-rolled automatically"
    assert (folder / "runs" / "02_shoot_1" / "identity_frame.png").is_file()
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["identity"]["status"] == "drift" and set(receipt["identity"]["reports"]) == {"hero", "shoot_1"}


async def test_nothing_is_checked_without_references(stack):
    gate = StubGate([])
    stack.pipeline.gate = gate
    take = await stack.pipeline.start_direct(direct(rig={"movement": "static"}))
    await stack.pipeline.wait(take["id"])
    assert gate.calls == 0 and stack.ledger.read(take["id"])["identity"] == {}


async def test_job_failure_ends_the_take_with_a_clear_error(stack, fake_api):
    fake_api.fail_with = {"code": "node_execution_error", "message": "CUDA out of memory",
                          "node_id": "251:211", "class_type": "SamplerCustomAdvanced"}
    take = await stack.pipeline.start_direct(direct(rig={"movement": "static"}))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "failed" and done["error"]["code"] == "job_failed"
    assert "out of memory" in done["error"]["message"]
    assert (await anext(aiter(stack.pipeline.subscribe(take["id"])), None)) is not None


async def test_cancel_stops_the_take_and_the_remote_job(stack, fake_api):
    fake_api.delay = 3.0  # long enough that the job is still running when the cancel lands, even on a loaded machine
    take = await stack.pipeline.start_direct(direct(rig={"movement": "static"}))
    await until(lambda: fake_api.jobs)
    await stack.pipeline.cancel(take["id"])
    assert stack.ledger.read(take["id"])["status"] == "canceled"
    assert any(j.cancel_requested for j in fake_api.jobs.values())


async def test_reshoot_prepares_the_source_and_keeps_both_clips(stack, tmp_path):
    clip = make_clip(tmp_path / "phone.mp4")
    ref = make_image(tmp_path / "hero.png", "blue")
    take = await stack.pipeline.start_reshoot(
        ReshootRequest(source=clip, reference=ref, prompt="A robot dancing in the rain", seed=3))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    folder = stack.ledger.take_dir(take["id"])
    assert done["status"] == "succeeded", done["error"]
    assert (folder / "inputs" / "source.mp4").is_file() and (folder / "inputs" / "reference.png").is_file()
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["workflow"]["runs"][0]["template"] == "wan_animate2"
    assert receipt["models"] and all(m["open_weights"] for m in receipt["models"])
    assert receipts.verify(receipt)


async def test_reshoot_validates_before_creating_anything(stack, tmp_path):
    with pytest.raises(ValueError, match="describe"):
        await stack.pipeline.start_reshoot(ReshootRequest(
            source=make_clip(tmp_path / "a.mp4"), reference=make_image(tmp_path / "a.png"), prompt="  "))
    with pytest.raises(ValueError, match="not found"):
        await stack.pipeline.start_reshoot(ReshootRequest(
            source=tmp_path / "nope.mp4", reference=make_image(tmp_path / "b.png"), prompt="x"))
    assert stack.ledger.list() == []


async def test_a_workflow_with_a_partner_node_is_refused_before_it_is_submitted(stack, fake_api, tmp_path):
    broken = tmp_path / "workflows"
    shutil.copytree(WORKFLOWS, broken)
    path = broken / "qwen21_t2i.api.json"
    graph = json.loads(path.read_text())
    graph["99"] = {"class_type": "KlingTextToVideoNode", "inputs": {"prompt": "x"}}
    graph["461"]["inputs"]["extra"] = ["99", 0]  # make it reachable from the output so it would execute
    path.write_text(json.dumps(graph))
    pipeline = Pipeline(stack.ledger, stack.pipeline.backend, broken, timeout=30.0)
    take = await pipeline.start_direct(direct(rig={"movement": "static"}))
    await pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "failed"
    assert not fake_api.jobs  # never reached the server


async def test_portrait_take_makes_candidates_with_a_receipt(stack):
    take = await stack.pipeline.start_portrait(
        PortraitRequest("a woman in her thirties with short dark hair and a navy wool coat", count=2, seed=40))
    seen = [e async for e in stack.pipeline.subscribe(take["id"])]
    done = stack.ledger.read(take["id"])
    folder = stack.ledger.take_dir(take["id"])

    assert done["kind"] == "portrait" and done["status"] == "succeeded" and done["progress"] == 1.0
    assert done["candidates"] == ["candidates/01.png", "candidates/02.png"]
    assert [o["role"] for o in done["outputs"]] == ["candidate", "candidate", "receipt"]
    for name in done["candidates"]:
        with Image.open(folder / name) as image:
            assert image.size[0] > 0 and image.format == "PNG"
    stages = [e["stage"] for e in seen if e["type"] == "stage" and e["state"] == "start"]
    assert stages == ["candidate_1", "candidate_2", "finish"]
    assert sorted(p.name for p in (folder / "runs").iterdir()) == ["01_candidate_1", "02_candidate_2"]

    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    assert receipts.verify(receipt) and receipt["take"]["kind"] == "portrait"
    assert receipt["audit"]["result"] == "pass"
    assert {m["role"] for m in receipt["models"]} >= {"image:qwen-image-2.1"}
    assert receipt["inputs"]["final_prompt"].startswith("A photographic head-and-shoulders portrait of a woman")
    assert [o["file"] for o in receipt["outputs"]] == done["candidates"]
    assert str(stack.root) not in json.dumps(receipt)
    graphs = [json.loads((r / "workflow.api.json").read_text()) for r in sorted((folder / "runs").iterdir())]
    assert graphs[0] != graphs[1], "each candidate uses its own seed"


async def test_portrait_requests_are_validated_before_anything_is_created(stack):
    for bad in (PortraitRequest("ab"), PortraitRequest("x" * 401), PortraitRequest("a nude figure study"),
                PortraitRequest("a calm sailor", count=0), PortraitRequest("a calm sailor", count=5)):
        with pytest.raises(ValueError):
            await stack.pipeline.start_portrait(bad)
    assert stack.ledger.list() == []


async def test_direct_and_reshoot_text_goes_through_the_content_guard(stack, tmp_path):
    with pytest.raises(ValueError, match="safe-for-work"):
        await stack.pipeline.start_direct(direct(subject="two people having sex"))
    with pytest.raises(ValueError, match="safe-for-work"):
        await stack.pipeline.start_direct(direct(audio="gory screams"))
    source = make_clip(tmp_path / "clip.mp4")
    reference = make_image(tmp_path / "ref.png")
    with pytest.raises(ValueError, match="safe-for-work"):
        await stack.pipeline.start_reshoot(ReshootRequest(source, reference, "a nude dancer"))
    assert stack.ledger.list() == []


async def test_a_recorded_portrait_take_can_be_replayed_with_its_candidates(stack, tmp_path):
    request = PortraitRequest("an old fisherman with a white beard", count=1, seed=3)
    live = await stack.pipeline.start_portrait(request)
    await stack.pipeline.wait(live["id"])
    replay_ledger = Ledger(tmp_path / "other-takes")
    replay = Pipeline(replay_ledger, lambda: ReplayBackend([stack.ledger.root]), WORKFLOWS)
    again = await replay.start_portrait(request)
    await replay.wait(again["id"])
    played = replay_ledger.read(again["id"])
    assert played["status"] == "succeeded" and played["replay"] is True
    assert played["candidates"] == ["candidates/01.png"]
    assert (replay_ledger.take_dir(again["id"]) / "candidates" / "01.png").is_file()


async def test_replay_plays_recorded_recipes_and_refuses_everything_else(stack, tmp_path):
    live = await stack.pipeline.start_direct(direct(rig={"movement": "static"}))
    await stack.pipeline.wait(live["id"])
    recorded = stack.ledger.read(live["id"])
    assert recorded["status"] == "succeeded"

    replay_ledger = Ledger(tmp_path / "other-takes")
    replay = Pipeline(replay_ledger, lambda: ReplayBackend([stack.ledger.root]), WORKFLOWS)
    again = await replay.start_direct(direct(rig={"movement": "static"}))
    await replay.wait(again["id"])
    played = replay_ledger.read(again["id"])
    assert played["status"] == "succeeded" and played["replay"] is True
    assert played["replay_of"] == live["id"] and played["backend"]["kind"] == "replay"
    src, dst = stack.ledger.take_dir(live["id"]), replay_ledger.take_dir(again["id"])
    assert (dst / "take.mp4").read_bytes() == (src / "take.mp4").read_bytes()
    # the graphs that ran travel with a replayed take, so Open in ComfyUI and the SDK snippet still work
    recorded_graphs = sorted(p.relative_to(src) for p in src.glob("runs/*/workflow.api.json"))
    assert recorded_graphs and recorded_graphs == sorted(p.relative_to(dst) for p in dst.glob("runs/*/workflow.api.json"))
    assert (dst / recorded_graphs[0].parent / "run.json").is_file()
    assert not list(dst.glob("runs/*/*.mp4")), "heavy per-step video is not copied"
    events = replay.bus.history(again["id"])
    assert any(e.get("replayed") for e in events) and events[-1]["type"] == "end"

    edited = await replay.start_direct(direct(rig={"movement": "static"}, subject="A different subject"))
    await replay.wait(edited["id"])
    refused = replay_ledger.read(edited["id"])
    assert refused["status"] == "failed" and refused["error"]["code"] == "replay_unavailable"
    assert "never fakes" in refused["error"]["message"]


async def test_a_replayed_take_has_its_media_on_disk_before_the_events_that_show_them(stack, tmp_path):
    live = await stack.pipeline.start_direct(direct(rig={"movement": "static"}))
    await stack.pipeline.wait(live["id"])
    replay_ledger = Ledger(tmp_path / "other-takes")
    replay = Pipeline(replay_ledger, lambda: ReplayBackend([stack.ledger.root]), WORKFLOWS)
    on_disk_when_announced: list[bool] = []
    real_publish = replay.bus.publish

    def spy(take_id, event):
        if event.get("type") == "run" and event["event"].get("kind") == "preview":
            path = replay_ledger.take_dir(take_id) / "runs" / event["run"] / "preview.jpg"
            on_disk_when_announced.append(path.is_file())
        real_publish(take_id, event)

    replay.bus.publish = spy
    again = await replay.start_direct(direct(rig={"movement": "static"}))
    await replay.wait(again["id"])
    assert on_disk_when_announced, "the recording has previews to replay"
    assert all(on_disk_when_announced), "a preview must exist when its event reaches the browser, or the browser gets a 404"


async def test_interrupted_takes_are_recovered_as_failed(tmp_path):
    ledger = Ledger(tmp_path / "t")
    take = ledger.create("direct", "x", {})
    ledger.update(take["id"], status="running")
    assert ledger.recover_interrupted() == [take["id"]]
    assert ledger.read(take["id"])["error"]["code"] == "interrupted"


async def test_bad_requests_are_rejected_before_a_take_exists(stack):
    with pytest.raises(ValueError):
        await stack.pipeline.start_direct(direct(rig={"movement": "teleport"}))
    with pytest.raises(ValueError, match="orientation"):
        await stack.pipeline.start_direct(direct(orientation="square"))
    assert stack.ledger.list() == []
    with pytest.raises(BackendError):
        raise BackendError("x", "y")  # the error type the API maps to HTTP statuses


# -- start from your own image: the still is the hero, nothing is rendered for it ----------------------------------
def photo(path: Path, size=(1000, 1000), color="green") -> Path:
    Image.new("RGB", size, color).save(path)
    return path


async def test_a_sourced_hero_skips_the_text_to_image_run_and_is_fitted_to_the_still(stack, tmp_path):
    import hashlib

    source = photo(tmp_path / "me.jpg")
    take = await stack.pipeline.start_direct(direct(source=source))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    folder = stack.ledger.take_dir(take["id"])
    assert done["status"] == "succeeded", done.get("error")
    assert sorted(p.name for p in (folder / "runs").iterdir()) == ["01_anchor_1", "02_shoot_1"], "no hero run: the still was given"
    hero = folder / "inputs" / "hero.png"
    with Image.open(hero) as img:
        assert img.size == (1344, 768), "fitted to the still size so the anchors and the LTX frames share one aspect"
    assert done["recipe"]["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert source.exists(), "a file the pipeline was not given to own is never deleted"

    plain = await stack.pipeline.start_direct(direct())
    await stack.pipeline.wait(plain["id"])
    assert "source_sha256" not in stack.ledger.read(plain["id"])["recipe"], "only a sourced hero carries the key"
    assert stack.ledger.read(plain["id"])["recipe_hash"] != done["recipe_hash"]

    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    src = receipt["inputs"]["source"]
    assert src["sha256"] == done["recipe"]["source_sha256"] and src["original_size"] == [1000, 1000]
    assert src["size"] == [1344, 768] and src["crop"] == [0, 214, 1000, 571], "a centre cover-crop to 7:4"
    assert src["identity_reference"] == "photo"
    assert receipt["inputs"]["anchors"][0]["file"] == "inputs/hero.png"
    assert [r["template"] for r in receipt["workflow"]["runs"]] == ["qwen21_edit", "ltx25_flf2v"]
    assert any("own image" in n for n in done["notes"]) and receipts.verify(receipt)

    portrait = await stack.pipeline.start_direct(direct(source=photo(tmp_path / "tall.png", (600, 1200)), orientation="portrait"))
    await stack.pipeline.wait(portrait["id"])
    with Image.open(stack.ledger.take_dir(portrait["id"]) / "inputs" / "hero.png") as img:
        assert img.size == (768, 1344)


async def test_a_sourced_hero_is_checked_against_the_cast_or_stands_as_the_reference(stack, tmp_path):
    stack.pipeline.gate = StubGate([])
    source, ref = photo(tmp_path / "photo.png"), make_image(tmp_path / "ref.png", "blue")
    with_cast = await stack.pipeline.start_direct(direct(source=source, cast_refs=[ref], cast_name="Mara"))
    await stack.pipeline.wait(with_cast["id"])
    done = stack.ledger.read(with_cast["id"])
    assert done["status"] == "succeeded" and done["identity"]["hero"]["refs_used"] == 1, "the photo is checked as the cast, once"
    receipt = json.loads((stack.ledger.take_dir(with_cast["id"]) / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["inputs"]["source"]["identity_reference"] == "cast" and receipt["inputs"]["cast"]["name"] == "Mara"

    alone = await stack.pipeline.start_direct(direct(source=source))
    await stack.pipeline.wait(alone["id"])
    done = stack.ledger.read(alone["id"])
    assert "hero" not in done["identity"], "a photo is never compared with itself"
    assert done["identity"]["anchor_1"]["refs_used"] == 1 and done["identity"]["shoot_1"]["refs_used"] == 1, "the photo is the reference for the rest"
    receipt = json.loads((stack.ledger.take_dir(alone["id"]) / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["identity"]["refs_used"] == 1 and receipt["inputs"]["source"]["identity_reference"] == "photo"


async def test_a_sourced_hero_cannot_be_re_rolled_but_its_anchors_can(stack, tmp_path):
    take = await stack.pipeline.start_direct(direct(source=photo(tmp_path / "p.png"), auto_approve=False))
    await until(lambda: stack.ledger.read(take["id"])["status"] == "awaiting_approval")
    with pytest.raises(ValueError, match="your photo"):
        stack.pipeline.approve(take["id"], [0])
    assert stack.ledger.read(take["id"])["status"] == "awaiting_approval", "a refused approval changes nothing"
    stack.pipeline.approve(take["id"], [1])
    runs_dir = stack.ledger.take_dir(take["id"]) / "runs"
    await until(lambda: stack.ledger.read(take["id"])["status"] == "awaiting_approval" and len(list(runs_dir.iterdir())) == 2)
    stack.pipeline.approve(take["id"], [])
    await stack.pipeline.wait(take["id"])
    assert stack.ledger.read(take["id"])["status"] == "succeeded"
    assert sorted(p.name for p in runs_dir.iterdir()) == ["01_anchor_1", "02_anchor_1", "03_shoot_1"], "the anchor was re-rolled from the same photo"


async def test_an_owned_source_image_is_deleted_however_the_take_ends(stack, tmp_path):
    owned = photo(tmp_path / "owned.png")
    take = await stack.pipeline.start_direct(direct(source=owned, owned=(owned,)))
    await stack.pipeline.wait(take["id"])
    assert stack.ledger.read(take["id"])["status"] == "succeeded" and not owned.exists()

    bad = tmp_path / "bad.png"
    bad.write_text("not an image")
    failed = await stack.pipeline.start_direct(direct(source=bad, owned=(bad,)))
    await stack.pipeline.wait(failed["id"])
    assert stack.ledger.read(failed["id"])["status"] == "failed" and not bad.exists()
    assert "bad.png" in stack.ledger.read(failed["id"])["error"]["message"]

    gone = photo(tmp_path / "gone.png")
    replay = Pipeline(stack.ledger, lambda: ReplayBackend([stack.root / "nothing"]), WORKFLOWS, timeout=60.0)
    refused = await replay.start_direct(direct(source=gone, owned=(gone,)))
    await replay.wait(refused["id"])
    assert stack.ledger.read(refused["id"])["error"]["code"] == "replay_unavailable" and not gone.exists(), "Replay never reads the upload"

    with pytest.raises(ValueError, match="not found"):
        await stack.pipeline.start_direct(direct(source=tmp_path / "missing.png"))


async def test_a_shot_from_the_persons_own_image_never_dresses_them_down(stack, tmp_path):
    before = len(stack.ledger.list())
    for words in ({"subject": "Me on the beach in a bikini"}, {"subject": "Me on a pier", "action": "she changes into a swimsuit"},
                  {"subject": "Me in a bathing suit on the diving board"}):
        upload = photo(tmp_path / "me.png")
        with pytest.raises(ValueError, match="never puts the person in underwear, swimwear or lingerie"):
            await stack.pipeline.start_direct(direct(rig={"movement": "static"}, source=upload, owned=(upload,), **words))
        assert not upload.exists(), "the refused upload is deleted"
    assert len(stack.ledger.list()) == before, "refused before any take exists"
    invented = await stack.pipeline.start_direct(direct(rig={"movement": "static"}, subject="A surfer on the beach in a bikini"))
    await stack.pipeline.wait(invented["id"])
    assert stack.ledger.read(invented["id"])["status"] == "succeeded", "an invented character is not a real person's photo"


# -- quality tiers: sizes and still steps, nothing the templates cannot honestly change ----------------------------
async def test_quality_tiers_change_sizes_and_still_steps_and_only_show_in_the_recipe_when_set(stack):
    draft = await stack.pipeline.start_direct(direct(quality="draft"))
    standard = await stack.pipeline.start_direct(direct())
    fine = await stack.pipeline.start_direct(direct(quality="fine", seed=8))
    for take in (draft, standard, fine):
        await stack.pipeline.wait(take["id"])
    assert stack.ledger.read(draft["id"])["recipe"]["quality"] == "draft"
    assert "quality" not in stack.ledger.read(standard["id"])["recipe"], "standard is what every earlier recipe rendered at"
    assert stack.ledger.read(draft["id"])["recipe_hash"] != stack.ledger.read(standard["id"])["recipe_hash"]

    hero = json.loads((stack.ledger.take_dir(draft["id"]) / "runs" / "01_hero" / "workflow.api.json").read_text(encoding="utf-8"))
    assert hero["459:458"]["inputs"]["steps"] == 12 and hero["459:456"]["inputs"]["width"] == 896 and hero["459:456"]["inputs"]["height"] == 512
    receipt = json.loads((stack.ledger.take_dir(draft["id"]) / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["inputs"]["quality"] == "draft" and receipt["workflow"].get("snapped", {}) in ({}, {"shoot_1": {}})
    shot = json.loads((stack.ledger.take_dir(fine["id"]) / "runs" / "03_shoot_1" / "workflow.api.json").read_text(encoding="utf-8"))
    from openfield.engine.workflows import load_template

    flf = load_template("ltx25_flf2v", WORKFLOWS)
    width, height = flf.slots["width"], flf.slots["height"]
    assert shot[width.node]["inputs"][width.input] == 1920 and shot[height.node]["inputs"][height.input] == 1088, "fine renders the video at 1920x1088, unsnapped"
    standard_receipt = json.loads((stack.ledger.take_dir(standard["id"]) / "receipt.json").read_text(encoding="utf-8"))
    assert standard_receipt["inputs"]["quality"] == "standard"
    with pytest.raises(ValueError, match="unsupported quality"):
        await stack.pipeline.start_direct(direct(quality="ultra"))


async def test_the_estimate_is_measured_from_this_installs_own_renders_or_null(stack):
    nothing = stack.pipeline.estimate_direct(quality_tier="standard", movement="dolly_in", duration_seconds=5)
    assert nothing["seconds"] is None and nothing["samples"] == 0 and "approvals not counted" in nothing["basis"]
    first = await stack.pipeline.start_direct(direct())
    second = await stack.pipeline.start_direct(direct(seed=9))
    await stack.pipeline.wait(first["id"])
    await stack.pipeline.wait(second["id"])
    measured = stack.pipeline.estimate_direct(quality_tier="standard", movement="dolly_in", duration_seconds=5)
    assert measured["samples"] == 2 and measured["seconds"] is not None and measured["low"] <= measured["seconds"] <= measured["high"]
    runs = sum(json.loads(r.read_text())["timings"]["total_s"] for r in (stack.ledger.take_dir(first["id"]) / "runs").glob("*/run.json"))
    assert measured["low"] <= round(runs, 1) + 0.11, "the figure is the sum of the model runs, not the wall clock with approvals"
    assert stack.pipeline.estimate_direct(quality_tier="draft", movement="dolly_in", duration_seconds=5)["samples"] == 0, "another tier is another shape"
    assert stack.pipeline.estimate_direct(quality_tier="standard", movement="dolly_in", duration_seconds=5, prompt_only=True)["samples"] == 0
    assert stack.pipeline.estimate_direct(quality_tier="standard", movement="static", duration_seconds=5)["samples"] == 0
    with pytest.raises(ValueError):
        stack.pipeline.estimate_direct(quality_tier="standard", movement="no_such_move", duration_seconds=5)


async def test_the_estimate_for_a_shot_from_an_image_counts_one_still_fewer(stack, tmp_path):
    sourced = await stack.pipeline.start_direct(direct(source=photo(tmp_path / "p.png")))
    await stack.pipeline.wait(sourced["id"])
    assert stack.pipeline.estimate_direct(quality_tier="standard", movement="dolly_in", duration_seconds=5, source=True)["samples"] == 1
    assert stack.pipeline.estimate_direct(quality_tier="standard", movement="dolly_in", duration_seconds=5)["samples"] == 0, "a sourced take is not a sample for a rendered hero"


def test_a_rig_at_its_defaults_records_exactly_the_keys_earlier_recordings_have():
    """Every preset added later (effect, grade) is left out at its default, or all recorded fingerprints would change."""
    from openfield.engine.rig import CameraRig
    from openfield.pipeline import recipe_rig

    assert set(recipe_rig(CameraRig())) == {"sensor", "lens", "focal_length_mm", "aperture", "lighting", "movement",
                                            "duration_seconds", "speed"}
    assert recipe_rig(CameraRig(grade="pastel"))["grade"] == "pastel"
    assert "grade" not in recipe_rig(CameraRig(effect="rain"))


async def test_an_angled_take_re_shoots_the_hero_first_and_re_rolls_only_the_angle(stack, tmp_path):
    take = await stack.pipeline.start_direct(direct(rig={"movement": "dolly_in", "angle": "back_left/low/wide"}, auto_approve=False))
    await until(lambda: stack.ledger.read(take["id"])["status"] == "awaiting_approval")
    shown = stack.ledger.read(take["id"])["anchors"]
    assert [a["role"] for a in shown] == ["angle", "edit"], "the first still for approval is the angled one"
    stack.pipeline.approve(take["id"], [0])
    runs_dir = stack.ledger.take_dir(take["id"]) / "runs"
    await until(lambda: stack.ledger.read(take["id"])["status"] == "awaiting_approval" and len(list(runs_dir.iterdir())) == 5)
    stack.pipeline.approve(take["id"], [])
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "succeeded", done.get("error")
    assert sorted(p.name for p in runs_dir.iterdir()) == ["01_hero", "02_angle", "03_anchor_1", "04_angle", "05_anchor_1", "06_shoot_1"], \
        "re-roll 0 re-shoots the angle from the hero (and the anchor from it), never the hero itself"
    receipt = json.loads((stack.ledger.take_dir(take["id"]) / "receipt.json").read_text(encoding="utf-8"))
    angle = receipt["inputs"]["angle"]
    assert angle["id"] == "back_left/low/wide" and angle["source_file"].startswith("runs/01_hero/") and angle["tested"] is True, "checked on its still (Oct 25)"
    assert "将镜头向左旋转135度" in angle["directive"] and "Move only the camera" in angle["directive"]
    assert receipt["inputs"]["anchors"][0]["file"].startswith("runs/04_angle/"), "the shot's first still is the angled one"
    assert done["recipe"]["rig"]["angle"] == "back_left/low/wide"
    assert [r["template"] for r in receipt["workflow"]["runs"]][:3] == ["qwen21_t2i", "qwen21_edit", "qwen21_edit"]

    plain = await stack.pipeline.start_direct(direct())
    await stack.pipeline.wait(plain["id"])
    assert "angle" not in stack.ledger.read(plain["id"])["recipe"]["rig"], "the default angle adds nothing to a recipe"

    sourced = await stack.pipeline.start_direct(direct(source=photo(tmp_path / "p.png"), rig={"movement": "dolly_in", "angle": "right/eye/close"}, auto_approve=False))
    await until(lambda: stack.ledger.read(sourced["id"])["status"] == "awaiting_approval")
    stack.pipeline.approve(sourced["id"], [0])  # allowed: it re-shoots the angle from the photo, never the photo itself
    runs_dir = stack.ledger.take_dir(sourced["id"]) / "runs"
    await until(lambda: stack.ledger.read(sourced["id"])["status"] == "awaiting_approval" and len(list(runs_dir.iterdir())) == 4)
    stack.pipeline.approve(sourced["id"], [])
    await stack.pipeline.wait(sourced["id"])
    assert stack.ledger.read(sourced["id"])["status"] == "succeeded"
    assert sorted(p.name for p in runs_dir.iterdir()) == ["01_angle", "02_anchor_1", "03_angle", "04_anchor_1", "05_shoot_1"]
    receipt = json.loads((stack.ledger.take_dir(sourced["id"]) / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["inputs"]["angle"]["source_file"] == "inputs/hero.png"


async def test_a_transformation_edits_the_end_state_and_skips_the_face_check_when_the_face_changes(stack, tmp_path):
    stack.pipeline.gate = StubGate([])
    ref = make_image(tmp_path / "ref.png", "blue")
    take = await stack.pipeline.start_direct(direct(rig={"movement": "static", "effect": "gold"}, cast_refs=[ref], cast_name="Mara"))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "succeeded", done.get("error")
    runs = sorted(p.name for p in (stack.ledger.take_dir(take["id"]) / "runs").iterdir())
    assert runs == ["01_hero", "02_transform_1", "03_shoot_1"]
    assert "transform_1" not in done["identity"] and "shoot_1" not in done["identity"], "a gold statue is not the same face on purpose"
    receipt = json.loads((stack.ledger.take_dir(take["id"]) / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["identity"]["skipped"] == {"transform_1": "the transformation changes the face on purpose", "shoot_1": "the transformation changes the face on purpose"}
    assert receipt["inputs"]["transformation"] == "gold" and receipt["inputs"]["segments"][0]["template"] == "ltx25_flf2v"
    assert "negative" not in receipt["inputs"], "no negative prompt is recorded: LTX 2.5 distilled never applies one"
    assert done["recipe"]["rig"]["effect"] == "gold"

    kept = await stack.pipeline.start_direct(direct(rig={"movement": "static", "effect": "ignite"}, cast_refs=[ref], cast_name="Mara"))
    await stack.pipeline.wait(kept["id"])
    done = stack.ledger.read(kept["id"])
    assert done["status"] == "succeeded" and "transform_1" in done["identity"] and "shoot_1" in done["identity"]


async def test_a_spoken_line_is_in_the_recipe_the_prompt_and_the_receipt_only_when_given(stack):
    take = await stack.pipeline.start_direct(direct(rig={"movement": "static"}, line='"Come home."', delivery="whisper", language="English"))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "succeeded"
    assert done["recipe"]["line"] == "Come home." and done["recipe"]["delivery"] == "whisper" and done["recipe"]["language"] == "English"
    receipt = json.loads((stack.ledger.take_dir(take["id"]) / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["inputs"]["dialogue"] == {"line": "Come home.", "delivery": "whisper", "language": "English", "tested": True}
    assert 'lips moving with the words: "Come home."' in receipt["inputs"]["final_prompt"]
    silent = await stack.pipeline.start_direct(direct(rig={"movement": "static"}))
    await stack.pipeline.wait(silent["id"])
    quiet = stack.ledger.read(silent["id"])
    assert "line" not in quiet["recipe"] and "delivery" not in quiet["recipe"], "silent recipes keep their fingerprint"
    assert "dialogue" not in json.loads((stack.ledger.take_dir(silent["id"]) / "receipt.json").read_text(encoding="utf-8"))["inputs"]


async def test_an_action_is_in_the_shot_the_recipe_and_the_receipt_only_when_given_and_never_in_a_still(stack):
    from openfield.engine.rig import CameraRig
    from openfield.pipeline import fingerprint, recipe_rig

    action = "He draws the katana in one swift motion"
    take = await stack.pipeline.start_direct(direct(subject="A samurai in a bamboo grove", action=f" {action}  "))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "succeeded", done.get("error")
    assert done["recipe"]["action"] == action
    core = {k: v for k, v in done["recipe"].items() if k not in {"cast_name", "auto_approve"}}
    without = {k: v for k, v in core.items() if k != "action"}
    assert done["recipe_hash"] == fingerprint(core) != fingerprint(without), "Replay never plays a take made without the action"
    assert any(n.startswith("action: a keyframed move") for n in done["notes"]), "dolly_in pins both ends, and says so"
    folder = stack.ledger.take_dir(take["id"])
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["inputs"]["action"] == action
    assert receipt["inputs"]["final_prompt"].startswith(f"A samurai in a bamboo grove. {action}. ")
    graph = lambda run: (folder / "runs" / run / "workflow.api.json").read_text(encoding="utf-8")  # noqa: E731
    assert action not in graph("01_hero") and action not in graph("02_anchor_1"), "the stills show the moment before"
    assert f"{action}." in graph("03_shoot_1")

    blank = await stack.pipeline.start_direct(direct(subject="A samurai in a bamboo grove", rig={"movement": "static"}, action="   "))
    await stack.pipeline.wait(blank["id"])
    plain = stack.ledger.read(blank["id"])
    assert plain["status"] == "succeeded" and "action" not in plain["recipe"]
    before = {"kind": "direct", "subject": "A samurai in a bamboo grove", "rig": recipe_rig(CameraRig(movement="static")),
              "audio": None, "seed": 7, "orientation": "landscape", "cast_refs": []}
    assert plain["recipe_hash"] == fingerprint(before), "no action, no key: earlier recordings keep their fingerprint"
    assert "action" not in json.loads((stack.ledger.take_dir(blank["id"]) / "receipt.json").read_text(encoding="utf-8"))["inputs"]


async def test_the_remix_fixtures_hold_what_a_real_direct_receipt_holds(stack):
    """tests/js/fixtures/remix_receipts.json is built from a copy of what _run_direct writes: real receipts keep it honest."""
    path = Path(__file__).parent / "js" / "make_fixtures.py"
    spec = importlib.util.spec_from_file_location("make_fixtures", path)
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    for name in ("talking_acted_draft", "dolly_in_quick", "spoken_line_no_language"):
        req = fixtures.remix_requests()[name]
        take = await stack.pipeline.start_direct(req)
        await stack.pipeline.wait(take["id"])
        assert stack.ledger.read(take["id"])["status"] == "succeeded", name
        inputs = json.loads((stack.ledger.take_dir(take["id"]) / "receipt.json").read_text(encoding="utf-8"))["inputs"]
        expected = fixtures.receipt_inputs(req)
        assert {key: inputs.get(key) for key in expected} == expected, name


# -- transitions: one LTX bridge between two finished takes ------------------------------------------------------

async def _two_takes(pipeline):
    a = await pipeline.start_direct(direct(rig={"movement": "static"}, subject="Mara on the pier at golden hour"))
    b = await pipeline.start_direct(direct(rig={"movement": "static"}, subject="Oskar at the net", seed=8))
    await pipeline.wait(a["id"])
    await pipeline.wait(b["id"])
    return a["id"], b["id"]


async def test_a_transition_bridges_two_finished_takes_and_plays_them_joined(stack):
    a, b = await _two_takes(stack.pipeline)
    take = await stack.pipeline.start_transition(TransitionRequest(first=a, second=b, style="whip", seconds=2, seed=5))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    folder = stack.ledger.take_dir(take["id"])
    assert done["status"] == "succeeded", done["error"]
    assert done["kind"] == "transition" and done["recipe"]["first"] == a and done["recipe"]["second"] == b
    assert sorted(p.name for p in (folder / "runs").iterdir()) == ["01_bridge"]
    assert (folder / "inputs" / "first_last_frame.png").is_file()
    assert (folder / "inputs" / "second_first_frame.png").is_file()
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    assert receipts.verify(receipt)
    assert [r["template"] for r in receipt["workflow"]["runs"]] == ["ltx25_flf2v"]
    inputs = receipt["inputs"]
    assert inputs["first"]["take"] == a and inputs["second"]["take"] == b and inputs["style"] == "whip"
    assert inputs["first"]["sha256"] == receipts.sha256_file(stack.ledger.take_dir(a) / "take.mp4")
    assert "whip pan" in inputs["final_prompt"].lower()
    assert "Mara on the pier" in inputs["final_prompt"] and "Oskar at the net" in inputs["final_prompt"]
    assert receipt["identity"]["skipped"]["bridge"]
    graph = json.loads((folder / "runs" / "01_bridge" / "workflow.api.json").read_text(encoding="utf-8"))
    assert graph, "the bridge's graph travels with the take"
    first_size = video.probe(stack.ledger.take_dir(a) / "take.mp4")
    w, h = inputs["frame"]
    assert w % 32 == 0 and h % 32 == 0 and 512 <= min(w, h) and max(w, h) <= 1920
    assert abs(w / h - first_size.width / first_size.height) < 0.08  # the first take's shape, so the join letterboxes nothing
    parts = sum(video.probe(stack.ledger.take_dir(t) / "take.mp4").duration_s for t in (a, b))
    assert video.probe(folder / "take.mp4").duration_s > parts - 0.5  # both takes and the bridge, joined


async def test_a_transition_is_validated_before_any_take_exists(stack):
    a, b = await _two_takes(stack.pipeline)
    before = len(stack.ledger.list())
    bad = [
        TransitionRequest(first=a, second=a),
        TransitionRequest(first=a, second=b, style="spin"),
        TransitionRequest(first=a, second=b, seconds=7),
        TransitionRequest(first="../../etc", second=b),
        TransitionRequest(first=a, second="tk_20990101_000000_abcd"),
    ]
    for req in bad:
        with pytest.raises(ValueError):
            await stack.pipeline.start_transition(req)
    assert len(stack.ledger.list()) == before


async def test_a_transition_may_land_on_a_recorded_take_from_the_shelf(stack, tmp_path, fake_api):
    backend = SdkBackend(base_url=fake_api.base_url)
    shelf = Ledger(tmp_path / "shelf")
    recorder = Pipeline(shelf, lambda: backend, WORKFLOWS, timeout=60.0)
    recorded = await recorder.start_direct(direct(rig={"movement": "static"}, subject="A lighthouse in a storm"))
    await recorder.wait(recorded["id"])
    mine = await stack.pipeline.start_direct(direct(rig={"movement": "static"}, seed=9))
    await stack.pipeline.wait(mine["id"])
    with pytest.raises(ValueError):  # without the shelf, the recorded take is not known here
        await stack.pipeline.start_transition(TransitionRequest(first=mine["id"], second=recorded["id"]))
    shelved = Pipeline(stack.ledger, lambda: backend, WORKFLOWS, timeout=60.0, shelves=[shelf.root])
    take = await shelved.start_transition(TransitionRequest(first=mine["id"], second=recorded["id"], seed=1))
    await shelved.wait(take["id"])
    assert stack.ledger.read(take["id"])["status"] == "succeeded"


async def test_replay_plays_a_recorded_transition_and_refuses_a_new_one(stack, tmp_path):
    a, b = await _two_takes(stack.pipeline)
    live = await stack.pipeline.start_transition(TransitionRequest(first=a, second=b, style="morph", seed=5))
    await stack.pipeline.wait(live["id"])
    assert stack.ledger.read(live["id"])["status"] == "succeeded"
    replay_ledger = Ledger(tmp_path / "replayed")
    replay = Pipeline(replay_ledger, lambda: ReplayBackend([stack.ledger.root]), WORKFLOWS, shelves=[stack.ledger.root])
    again = await replay.start_transition(TransitionRequest(first=a, second=b, style="morph", seed=5))
    await replay.wait(again["id"])
    played = replay_ledger.read(again["id"])
    assert played["status"] == "succeeded" and played["replay_of"] == live["id"]
    other = await replay.start_transition(TransitionRequest(first=b, second=a, style="morph", seed=5))
    await replay.wait(other["id"])
    refused = replay_ledger.read(other["id"])
    assert refused["status"] == "failed" and refused["error"]["code"] == "replay_unavailable"


def test_the_bridge_keeps_the_first_takes_shape_inside_the_templates_limits():
    from openfield.pipeline import bridge_size
    assert bridge_size(1280, 704) == (1280, 704)  # a Standard take: its own size
    assert bridge_size(704, 1280) == (704, 1280)
    assert bridge_size(896, 512) == (896, 512)  # a Draft take
    assert bridge_size(640, 360) == (896, 512)  # scaled up to the 512 floor, same shape
    assert bridge_size(3840, 2160) == (1920, 1056)  # scaled down to the 1920 ceiling
    assert bridge_size(0, 0) == (1280, 704)


# -- extend: continue a finished take from its last frame --------------------------------------------------------------

async def _one_take(pipeline):
    a = await pipeline.start_direct(direct(rig={"movement": "static"}, subject="Mara on the pier at golden hour"))
    await pipeline.wait(a["id"])
    return a["id"]


async def test_an_extend_continues_a_finished_take_and_plays_it_joined(stack):
    a = await _one_take(stack.pipeline)
    take = await stack.pipeline.start_extend(ExtendRequest(take=a, seconds=3, seed=5))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    folder = stack.ledger.take_dir(take["id"])
    assert done["status"] == "succeeded", done["error"]
    assert done["kind"] == "extend" and done["recipe"]["take"] == a
    assert sorted(p.name for p in (folder / "runs").iterdir()) == ["01_extend"]
    assert (folder / "inputs" / "last_frame.png").is_file()
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    assert receipts.verify(receipt)
    assert [r["template"] for r in receipt["workflow"]["runs"]] == ["ltx25_i2v"]
    inputs = receipt["inputs"]
    assert inputs["take"]["id"] == a and inputs["seconds"] == 3
    assert inputs["take"]["sha256"] == receipts.sha256_file(stack.ledger.take_dir(a) / "take.mp4")
    assert inputs["take"]["frame"] == "inputs/last_frame.png"
    assert "Mara on the pier" in inputs["final_prompt"]
    assert receipt["identity"]["skipped"]["extend"]
    graph = json.loads((folder / "runs" / "01_extend" / "workflow.api.json").read_text(encoding="utf-8"))
    assert graph, "the extension's graph travels with the take"
    original = video.probe(stack.ledger.take_dir(a) / "take.mp4")
    joined = video.probe(folder / "take.mp4")
    assert joined.duration_s > original.duration_s, "the joined take is longer than the original"
    w, h = inputs["frame"]
    assert w % 32 == 0 and h % 32 == 0 and 512 <= min(w, h) and max(w, h) <= 1920
    assert abs(w / h - original.width / original.height) < 0.08


def test_an_extensions_words_follow_the_delivered_move(tmp_path):
    """Oct 26: a take played backwards (through object) is continued with its own words, not the dolly out it was
    rendered as, so the extension pushes on instead of turning round at the join."""
    take = {"kind": "direct", "recipe": {"subject": "Oskar at a table in a fisherman's hut at dusk", "rig": {"movement": "through_object"}}}
    words = Pipeline._continuing_words(take, tmp_path)
    assert "dollies out" not in words and "through" in words.lower()


async def test_an_extend_is_validated_before_any_take_exists(stack):
    a = await _one_take(stack.pipeline)
    before = len(stack.ledger.list())
    bad = [
        ExtendRequest(take=a, seconds=7),
        ExtendRequest(take="../../etc"),
        ExtendRequest(take="tk_20990101_000000_abcd"),
    ]
    for req in bad:
        with pytest.raises(ValueError):
            await stack.pipeline.start_extend(req)
    assert len(stack.ledger.list()) == before


async def test_an_extend_may_continue_a_recorded_take_from_the_shelf(stack, tmp_path, fake_api):
    backend = SdkBackend(base_url=fake_api.base_url)
    shelf = Ledger(tmp_path / "shelf")
    recorder = Pipeline(shelf, lambda: backend, WORKFLOWS, timeout=60.0)
    recorded = await recorder.start_direct(direct(rig={"movement": "static"}, subject="A lighthouse in a storm"))
    await recorder.wait(recorded["id"])
    mine = await stack.pipeline.start_direct(direct(rig={"movement": "static"}, seed=9))
    await stack.pipeline.wait(mine["id"])
    with pytest.raises(ValueError):  # without the shelf, the recorded take is not known here
        await stack.pipeline.start_extend(ExtendRequest(take=recorded["id"], seconds=3))
    shelved = Pipeline(stack.ledger, lambda: backend, WORKFLOWS, timeout=60.0, shelves=[shelf.root])
    take = await shelved.start_extend(ExtendRequest(take=recorded["id"], seconds=3, seed=1))
    await shelved.wait(take["id"])
    assert stack.ledger.read(take["id"])["status"] == "succeeded"


async def test_replay_plays_a_recorded_extension_and_refuses_a_new_one(stack, tmp_path):
    a = await _one_take(stack.pipeline)
    live = await stack.pipeline.start_extend(ExtendRequest(take=a, seconds=3, seed=5))
    await stack.pipeline.wait(live["id"])
    assert stack.ledger.read(live["id"])["status"] == "succeeded"
    replay_ledger = Ledger(tmp_path / "replayed")
    replay = Pipeline(replay_ledger, lambda: ReplayBackend([stack.ledger.root]), WORKFLOWS, shelves=[stack.ledger.root])
    again = await replay.start_extend(ExtendRequest(take=a, seconds=3, seed=5))
    await replay.wait(again["id"])
    played = replay_ledger.read(again["id"])
    assert played["status"] == "succeeded" and played["replay_of"] == live["id"]
    other = await replay.start_extend(ExtendRequest(take=a, seconds=5, seed=5))
    await replay.wait(other["id"])
    refused = replay_ledger.read(other["id"])
    assert refused["status"] == "failed" and refused["error"]["code"] == "replay_unavailable"


async def test_an_extension_continues_the_shot_without_speaking_its_line_or_replaying_its_action_again(stack):
    from openfield.engine.rig import EXTEND_LEAD, SOUNDSCAPES, TRANSFORMATIONS

    talking = await stack.pipeline.start_direct(direct(rig={"movement": "static", "soundscape": "harbour"},
                                                       subject="Mara on the pier", line="We leave at first light.",
                                                       audio="gulls overhead"))
    acted = await stack.pipeline.start_direct(direct(rig={"movement": "static", "effect": "ignite"}, seed=8,
                                                     subject="A samurai in a bamboo grove",
                                                     action="He draws the katana and raises the blade"))
    for take in (talking, acted):
        await stack.pipeline.wait(take["id"])
        assert stack.ledger.read(take["id"])["status"] == "succeeded"

    async def extend(take_id: str) -> tuple[dict, str]:
        ext = await stack.pipeline.start_extend(ExtendRequest(take=take_id, seconds=3, seed=5))
        await stack.pipeline.wait(ext["id"])
        done = stack.ledger.read(ext["id"])
        assert done["status"] == "succeeded", done.get("error")
        receipt = json.loads((stack.ledger.take_dir(ext["id"]) / "receipt.json").read_text(encoding="utf-8"))
        return done, receipt["inputs"]["final_prompt"]

    said, prompt = await extend(talking["id"])
    assert prompt.startswith(f"{EXTEND_LEAD} Mara on the pier.")
    assert "first light" not in prompt and "lips moving" not in prompt, "the line is spoken once"
    assert "gulls overhead" in prompt and SOUNDSCAPES["harbour"] in prompt, "the sound carries on"
    _, prompt = await extend(acted["id"])
    assert "A samurai in a bamboo grove." in prompt
    assert "katana" not in prompt, "the action is not played again"
    assert TRANSFORMATIONS["ignite"].phrase not in prompt and "Flames" not in prompt, "the transformation does not restart"
    again, prompt = await extend(said["id"])  # an extension of an extension continues the same shot
    assert prompt.count(EXTEND_LEAD) == 1 and prompt.startswith(f"{EXTEND_LEAD} Mara on the pier.")
    assert "first light" not in prompt and "gulls overhead" in prompt
    assert again["recipe"]["take"] == said["id"] and again["label"] == said["label"] == "extend: Mara on the pier"


# -- upscale: one Real-ESRGAN pass over a finished take ---------------------------------------------------------------

async def _rendered_take(pipeline, **overrides):
    take = await pipeline.start_direct(direct(rig={"movement": "static"}, **overrides))
    await pipeline.wait(take["id"])
    return take["id"]


async def test_an_upscale_runs_the_official_graph_on_a_finished_take_and_seals_a_receipt(stack, fake_api):
    source = await _rendered_take(stack.pipeline)
    stack.ledger.update(source, size=[1280, 704])  # a Standard take (the fake renders a small clip): the x4 model reaches 5120x2816
    source_mp4 = stack.ledger.take_dir(source) / "take.mp4"
    take = await stack.pipeline.start_upscale(UpscaleRequest(take=source, target="4k"))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    folder = stack.ledger.take_dir(take["id"])
    assert done["status"] == "succeeded", done["error"]
    assert done["kind"] == "upscale" and done["recipe"] == {"kind": "upscale", "take": source, "target": "4k"}
    assert done["label"].startswith("upscale 4K: ") and "lighthouse" in done["label"]
    assert [o["role"] for o in done["outputs"]] == ["video", "poster", "receipt"]
    assert sorted(p.name for p in (folder / "runs").iterdir()) == ["01_upscale"]
    assert (folder / "take.mp4").is_file() and video.probe(folder / "take.mp4").duration_s > 0

    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    assert receipts.verify(receipt) and receipt["take"]["kind"] == "upscale"
    assert [r["template"] for r in receipt["workflow"]["runs"]] == ["esrgan_upscale"]
    digest = receipts.sha256_file(source_mp4)
    assert receipt["inputs"] == {"take": {"id": source, "sha256": digest}, "target": "4k", "size": [3840, 2112],
                                 "recipe_hash": done["recipe_hash"]}
    assert receipt["audit"] == {"policy": "open-weights-only", "result": "pass", "disallowed": []}
    (model,) = receipt["models"]
    assert model["file"] == "RealESRGAN_x4plus.safetensors" and model["role"] == "upscaler:real-esrgan"
    assert model["license"] == "BSD 3-Clause License" and model["open_weights"] is True and model["attribution"] is None
    assert model["source"].startswith("https://huggingface.co/")
    assert receipt["identity"]["status"] == "n/a" and receipt["identity"]["skipped"]["upscale"]
    assert str(stack.root) not in json.dumps(receipt)  # no machine paths in a shareable file
    found, verified = receipts.read_media(folder / "take.mp4")
    assert verified and found["take"]["id"] == take["id"]  # embedded in the video itself

    (note,) = done["notes"]
    assert "Real-ESRGAN x4plus" in note and "3840x2112" in note and "GAN upscaler" in note
    assert "nothing beyond that is invented" in note

    # the graph that ran: the take's clip goes in as a video asset, ImageScale lands the x4 result on the frame
    run = json.loads((folder / "runs" / "01_upscale" / "run.json").read_text(encoding="utf-8"))
    assert run["assets"] == [{"node": "9", "input": "file", "slot": "video", "name": "video.mp4", "sha256": digest, "from": None}]
    graph = json.loads((folder / "runs" / "01_upscale" / "workflow.api.json").read_text(encoding="utf-8"))
    assert graph["9"]["inputs"]["file"] == "video.mp4" and graph["1"]["inputs"]["model_name"] == "RealESRGAN_x4plus.safetensors"
    assert graph["13"]["inputs"] == {"upscale_method": "area", "width": 3840, "height": 2112, "crop": "disabled", "image": ["2", 0]}
    sent = list(fake_api.jobs.values())[-1].workflow
    assert sent["9"]["inputs"]["file"]["__type"] == "core/ASSET", "the clip was uploaded, not named"
    assert (sent["13"]["inputs"]["width"], sent["13"]["inputs"]["height"]) == (3840, 2112)

    events = stack.pipeline.bus.history(take["id"])
    assert [e["stage"] for e in events if e["type"] == "stage" and e["state"] == "start"] == ["upscale", "finish"]
    assert receipts.sha256_file(source_mp4) == digest, "the take that was enlarged is untouched"


async def test_a_target_above_four_times_the_take_is_enlarged_with_bicubic_not_area(stack):
    source = await _rendered_take(stack.pipeline)  # the fake renders a 320x180 clip: 2k is 8x, past what the x4 model reaches
    take = await stack.pipeline.start_upscale(UpscaleRequest(take=source, target="2k"))
    await stack.pipeline.wait(take["id"])
    assert stack.ledger.read(take["id"])["status"] == "succeeded"
    info = video.probe(stack.ledger.take_dir(source) / "take.mp4")
    width, height = upscale_size(info.width, info.height, "2k")
    folder = stack.ledger.take_dir(take["id"])
    graph = json.loads((folder / "runs" / "01_upscale" / "workflow.api.json").read_text(encoding="utf-8"))
    assert graph["13"]["inputs"]["upscale_method"] == "bicubic"
    assert (graph["13"]["inputs"]["width"], graph["13"]["inputs"]["height"]) == (width, height) == (2560, 1440)
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["inputs"]["size"] == [2560, 1440] and receipt["inputs"]["target"] == "2k"


def test_an_upscale_keeps_the_takes_shape_in_even_numbers():
    assert upscale_size(1280, 704, "4k") == (3840, 2112) and upscale_size(1280, 704, "2k") == (2560, 1408)
    assert upscale_size(1280, 720, "4k") == (3840, 2160)  # a 720p take lands on UHD
    assert upscale_size(704, 1280, "4k") == (2112, 3840), "the long side is the height of a portrait take"
    assert upscale_size(896, 512, "2k") == (2560, 1462)  # a Draft take: 1462.9 snaps to the even number
    assert upscale_size(482, 854, "4k") == (2168, 3840)  # Wan Animate 2 working size
    assert upscale_size(1920, 1088, "4k") == (3840, 2176)
    for width, height in ((1280, 704), (896, 512), (482, 854), (1000, 333), (99, 77), (1920, 1088), (320, 180)):
        for target, side in UPSCALE_TARGETS.items():
            w, h = upscale_size(width, height, target)
            assert max(w, h) == side and w % 2 == 0 and h % 2 == 0, (width, height, target)
            assert abs(w / h - width / height) <= 2 / min(w, h) * (w / h), (width, height, target)  # off by at most one even step
    for bad in ((0, 704, "4k"), (1280, -1, "4k"), (1280, 704, "8k")):
        with pytest.raises(ValueError):
            upscale_size(*bad)


async def test_an_upscale_is_refused_before_any_take_exists_when_it_cannot_be_done(stack):
    source = await _rendered_take(stack.pipeline)
    before = len(stack.ledger.list())
    refused = [
        (UpscaleRequest(take=source, target="8k"), "unknown upscale target"),
        (UpscaleRequest(take=source, target=""), "unknown upscale target"),
        (UpscaleRequest(take="../../etc"), "not a take id"),
        (UpscaleRequest(take="tk_20990101_000000_abcd"), "not a finished take"),
    ]
    for req, message in refused:
        with pytest.raises(ValueError, match=message):
            await stack.pipeline.start_upscale(req)
    assert len(stack.ledger.list()) == before
    unfinished = stack.ledger.create("direct", "still rendering", {"kind": "direct"})
    with pytest.raises(ValueError, match="not a finished take"):
        await stack.pipeline.start_upscale(UpscaleRequest(take=unfinished["id"]))
    stack.ledger.update(source, size=[3840, 2160])  # already as large as the target: the model would only run for nothing
    with pytest.raises(ValueError, match="already 3840x2160"):
        await stack.pipeline.start_upscale(UpscaleRequest(take=source, target="4k"))
    with pytest.raises(ValueError, match="already 3840x2160"):
        await stack.pipeline.start_upscale(UpscaleRequest(take=source, target="2k"))
    assert len(stack.ledger.list()) == before + 1  # the unfinished take made above, and nothing else
    stack.ledger.update(source, size=[640, 360])
    import openfield.pipeline as pipeline_module
    limit = pipeline_module.UPSCALE_MAX_BYTES
    pipeline_module.UPSCALE_MAX_BYTES = 1024  # any clip is too long for this limit
    try:
        with pytest.raises(ValueError, match="too long to upscale in one pass"):
            await stack.pipeline.start_upscale(UpscaleRequest(take=source, target="2k"))
    finally:
        pipeline_module.UPSCALE_MAX_BYTES = limit
    assert len(stack.ledger.list()) == before + 1, "refused before any take exists"


def test_the_upscale_memory_limit_comes_from_the_environment_when_set(monkeypatch):
    from openfield.pipeline import UPSCALE_MAX_BYTES, upscale_max_bytes
    monkeypatch.delenv("OPENFIELD_UPSCALE_MAX_GB", raising=False)
    assert upscale_max_bytes() == UPSCALE_MAX_BYTES == 24 * 2**30
    monkeypatch.setenv("OPENFIELD_UPSCALE_MAX_GB", "48")
    assert upscale_max_bytes() == 48 * 2**30
    monkeypatch.setenv("OPENFIELD_UPSCALE_MAX_GB", " 0.5 ")
    assert upscale_max_bytes() == 2**29
    for junk in ("", "lots", "0", "-3", "nan", "inf"):
        monkeypatch.setenv("OPENFIELD_UPSCALE_MAX_GB", junk)
        assert upscale_max_bytes() == UPSCALE_MAX_BYTES, junk


async def test_an_upscale_reads_its_memory_limit_on_each_request(stack, monkeypatch):
    import openfield.pipeline as pipeline_module
    source = await _rendered_take(stack.pipeline)
    before = len(stack.ledger.list())
    monkeypatch.setenv("OPENFIELD_UPSCALE_MAX_GB", "0.000001")  # about a kilobyte: any clip is too long
    with pytest.raises(ValueError, match="too long to upscale in one pass"):
        await stack.pipeline.start_upscale(UpscaleRequest(take=source, target="2k"))
    assert len(stack.ledger.list()) == before, "refused before any take exists"
    monkeypatch.setattr(pipeline_module, "UPSCALE_MAX_BYTES", 1024)  # the default alone would refuse it now
    monkeypatch.setenv("OPENFIELD_UPSCALE_MAX_GB", "64")  # a box with more memory says so
    take = await stack.pipeline.start_upscale(UpscaleRequest(take=source, target="2k"))
    await stack.pipeline.wait(take["id"])
    assert stack.ledger.read(take["id"])["status"] == "succeeded"


async def test_an_upscale_is_never_upscaled_again(stack):
    source = await _rendered_take(stack.pipeline)
    first = await stack.pipeline.start_upscale(UpscaleRequest(take=source, target="2k"))
    await stack.pipeline.wait(first["id"])
    assert stack.ledger.read(first["id"])["status"] == "succeeded"
    before = len(stack.ledger.list())
    with pytest.raises(ValueError, match="already an upscale"):
        await stack.pipeline.start_upscale(UpscaleRequest(take=first["id"], target="4k"))
    assert len(stack.ledger.list()) == before


async def test_a_take_whose_size_was_not_recorded_is_measured_from_its_video(stack):
    source = await _rendered_take(stack.pipeline)
    take_json = stack.ledger.take_dir(source) / "take.json"
    data = json.loads(take_json.read_text(encoding="utf-8"))
    del data["size"]
    take_json.write_text(json.dumps(data), encoding="utf-8")
    take = await stack.pipeline.start_upscale(UpscaleRequest(take=source, target="2k"))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "succeeded", done["error"]
    assert done["recipe"]["take"] == source


async def test_replay_plays_a_recorded_upscale_and_refuses_a_new_one(stack, tmp_path):
    source = await _rendered_take(stack.pipeline)
    live = await stack.pipeline.start_upscale(UpscaleRequest(take=source, target="2k"))
    await stack.pipeline.wait(live["id"])
    assert stack.ledger.read(live["id"])["status"] == "succeeded"
    replay_ledger = Ledger(tmp_path / "replayed")
    replay = Pipeline(replay_ledger, lambda: ReplayBackend([stack.ledger.root]), WORKFLOWS, shelves=[stack.ledger.root])
    again = await replay.start_upscale(UpscaleRequest(take=source, target="2k"))
    await replay.wait(again["id"])
    played = replay_ledger.read(again["id"])
    assert played["status"] == "succeeded" and played["replay"] is True and played["replay_of"] == live["id"]
    assert played["kind"] == "upscale" and played["backend"]["kind"] == "replay"
    src, dst = stack.ledger.take_dir(live["id"]), replay_ledger.take_dir(again["id"])
    assert (dst / "take.mp4").read_bytes() == (src / "take.mp4").read_bytes()
    assert (dst / "runs" / "01_upscale" / "workflow.api.json").is_file(), "the graph that ran travels with a replayed take"
    other = await replay.start_upscale(UpscaleRequest(take=source, target="4k"))  # a different recipe: never faked
    await replay.wait(other["id"])
    refused = replay_ledger.read(other["id"])
    assert refused["status"] == "failed" and refused["error"]["code"] == "replay_unavailable"
    assert "never fakes" in refused["error"]["message"]


# -- shots: one still re-shot as a board of nine setups -------------------------------------------------------------

async def test_a_shots_board_re_shoots_a_takes_still_nine_ways_and_plays_them_in_order(stack):
    from openfield.engine.rig import SHOTS_BOARD, SHOTS_SECONDS_EACH
    source = await stack.pipeline.start_direct(direct(rig={"movement": "static"}, subject="Oskar at the net"))
    await stack.pipeline.wait(source["id"])
    take = await stack.pipeline.start_shots(ShotsRequest(take=source["id"], seed=4))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    folder = stack.ledger.take_dir(take["id"])
    assert done["status"] == "succeeded", done["error"]
    assert done["kind"] == "shots" and done["recipe"]["take"] == source["id"]
    assert [s["angle"] for s in done["shots"]] == [a for a, _ in SHOTS_BOARD]
    assert [s["label"] for s in done["shots"]][:4] == ["Wide", "Three-quarter left", "Three-quarter right", "Close-up"]
    assert all((folder / s["file"]).is_file() for s in done["shots"])
    assert (folder / "board.jpg").is_file() and (folder / "inputs" / "source.png").is_file()
    assert len(list((folder / "runs").iterdir())) == 9
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    assert receipts.verify(receipt)
    assert {r["template"] for r in receipt["workflow"]["runs"]} == {"qwen21_edit"}  # no video model ran
    assert receipt["inputs"]["shots"][0]["directive"].startswith("Re-shoot the same scene from")
    assert receipt["inputs"]["identity_reference"] == "image"
    assert video.probe(folder / "take.mp4").duration_s == pytest.approx(9 * SHOTS_SECONDS_EACH, abs=0.15)


async def test_a_shots_board_can_start_from_an_upload_which_is_deleted_afterwards(stack, tmp_path):
    upload = make_image(tmp_path / "upload.png", "green")
    take = await stack.pipeline.start_shots(ShotsRequest(source=upload, seed=2, owned=(upload,)))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "succeeded", done["error"]
    assert "take" not in done["recipe"] and done["recipe"]["source_sha256"]
    assert not upload.exists(), "the person's upload is kept nowhere once the take is over"


async def test_a_shots_board_is_validated_before_any_take_exists(stack, tmp_path):
    before = len(stack.ledger.list())
    upload = make_image(tmp_path / "upload.png")
    with pytest.raises(ValueError):
        await stack.pipeline.start_shots(ShotsRequest())
    with pytest.raises(ValueError):
        await stack.pipeline.start_shots(ShotsRequest(source=upload, take="tk_20261022_120000_abcd", owned=(upload,)))
    assert not upload.exists(), "a refused upload is deleted too"
    with pytest.raises(ValueError):
        await stack.pipeline.start_shots(ShotsRequest(take="tk_20990101_000000_abcd"))
    with pytest.raises(ValueError):
        await stack.pipeline.start_shots(ShotsRequest(source=tmp_path / "missing.png"))
    assert len(stack.ledger.list()) == before


async def test_a_takes_still_is_its_first_anchor_and_never_a_path_outside_its_folder(stack):
    source = await stack.pipeline.start_direct(direct(rig={"movement": "static"}))
    await stack.pipeline.wait(source["id"])
    take, folder = stack.pipeline.finished_take(source["id"])
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    first = receipt["inputs"]["anchors"][0]["file"]
    assert stack.pipeline.take_still(take, folder) == (folder / first).resolve()
    receipt["inputs"]["anchors"][0]["file"] = "../../outside.png"
    (folder / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    assert stack.pipeline.take_still(take, folder) == (folder / "poster.png").resolve()


async def test_replay_plays_a_recorded_shots_board_with_its_stills(stack, tmp_path):
    source = await stack.pipeline.start_direct(direct(rig={"movement": "static"}))
    await stack.pipeline.wait(source["id"])
    live = await stack.pipeline.start_shots(ShotsRequest(take=source["id"], seed=4))
    await stack.pipeline.wait(live["id"])
    replay_ledger = Ledger(tmp_path / "replayed")
    replay = Pipeline(replay_ledger, lambda: ReplayBackend([stack.ledger.root]), WORKFLOWS, shelves=[stack.ledger.root])
    again = await replay.start_shots(ShotsRequest(take=source["id"], seed=4))
    await replay.wait(again["id"])
    played = replay_ledger.read(again["id"])
    assert played["status"] == "succeeded" and played["replay_of"] == live["id"]
    assert len(played["shots"]) == 9 and played["board"] == "board.jpg"
    assert (replay_ledger.take_dir(again["id"]) / "board.jpg").is_file(), "the board a replay names is on disk"
    assert all((replay_ledger.take_dir(again["id"]) / s["file"]).is_file() for s in played["shots"])


async def test_a_reframing_transformation_lets_the_end_state_widen_the_view(stack):
    take = await stack.pipeline.start_direct(direct(rig={"movement": "static", "effect": "bts"}))
    await stack.pipeline.wait(take["id"])
    folder = stack.ledger.take_dir(take["id"])
    assert stack.ledger.read(take["id"])["status"] == "succeeded"
    graph = (folder / "runs" / "02_transform_1" / "workflow.api.json").read_text(encoding="utf-8")
    assert "the view may widen" in graph and "film set" in graph
    plain = await stack.pipeline.start_direct(direct(rig={"movement": "static", "effect": "freeze"}, seed=9))
    await stack.pipeline.wait(plain["id"])
    graph = (stack.ledger.take_dir(plain["id"]) / "runs" / "02_transform_1" / "workflow.api.json").read_text(encoding="utf-8")
    assert "Keep the same framing" in graph and "the view may widen" not in graph


# -- edit with words, and the face-only re-shoot ---------------------------------------------------------------------
async def test_an_edit_swaps_a_face_from_a_cast_and_plays_before_and_after(stack, tmp_path):
    source = await stack.pipeline.start_direct(direct(rig={"movement": "static"}))
    await stack.pipeline.wait(source["id"])
    face = [make_image(tmp_path / "face.png", "blue")]
    take = await stack.pipeline.start_edit(EditRequest(preset="face_swap", take=source["id"], cast_refs=face, cast_name="Ines", seed=3))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    folder = stack.ledger.take_dir(take["id"])
    assert done["status"] == "succeeded", done["error"]
    assert done["kind"] == "edit" and done["edit"]["preset"] == "face_swap" and (folder / done["edit"]["after"]).is_file()
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    assert receipts.verify(receipt) and receipt["inputs"]["identity_reference"] == "cast"
    assert receipt["inputs"]["final_prompt"].startswith("Replace the face of the person")
    graph = json.loads((folder / "runs" / "01_edit" / "workflow.api.json").read_text(encoding="utf-8"))
    assert graph and [r["template"] for r in receipt["workflow"]["runs"]] == ["qwen21_edit"]
    assert video.probe(folder / "take.mp4").duration_s == pytest.approx(2.4, abs=0.15)


async def test_an_edit_is_refused_before_a_take_exists_when_it_cannot_be_done(stack, tmp_path):
    source = await stack.pipeline.start_direct(direct(rig={"movement": "static"}))
    await stack.pipeline.wait(source["id"])
    before = len(stack.ledger.list())
    upload = make_image(tmp_path / "up.png")
    with pytest.raises(ValueError):  # a face is only taken from a Cast
        await stack.pipeline.start_edit(EditRequest(preset="face_swap", source=upload, owned=(upload,)))
    assert not upload.exists()
    with pytest.raises(ValueError):  # words are needed
        await stack.pipeline.start_edit(EditRequest(preset="remove", take=source["id"]))
    with pytest.raises(ValueError):  # never a path outside the take
        await stack.pipeline.start_edit(EditRequest(preset="remove", detail="the boat", take=source["id"], still="../../x.png"))
    assert len(stack.ledger.list()) == before


async def test_an_edit_of_an_upload_keeps_the_person_and_deletes_the_upload(stack, tmp_path):
    upload = make_image(tmp_path / "mine.png", "green")
    take = await stack.pipeline.start_edit(EditRequest(preset="relight", detail="neon", source=upload, owned=(upload,), seed=2))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "succeeded", done["error"]
    receipt = json.loads((stack.ledger.take_dir(take["id"]) / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["inputs"]["identity_reference"] == "picture" and "neon" in receipt["inputs"]["final_prompt"]
    assert not upload.exists()


async def test_a_face_only_reshoot_swaps_the_first_frames_face_then_re_performs_the_clip(stack, tmp_path):
    clip = make_clip(tmp_path / "dance.mp4")
    faces = [make_image(tmp_path / "face.png", "blue")]
    with pytest.raises(ValueError):
        await stack.pipeline.start_reshoot(ReshootRequest(source=clip, reference=faces[0], prompt="the same dancer", face_only=True))
    take = await stack.pipeline.start_reshoot(ReshootRequest(
        source=clip, reference=faces[0], prompt="the same dancer", seed=3, face_only=True, face_refs=faces))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    folder = stack.ledger.take_dir(take["id"])
    assert done["status"] == "succeeded", done["error"]
    assert done["recipe"]["face_only"] is True
    assert [p.name for p in sorted((folder / "runs").iterdir())] == ["01_face", "02_motion"]
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    assert [r["template"] for r in receipt["workflow"]["runs"]] == ["qwen21_edit", "wan_animate2"]
    assert receipt["inputs"]["face_only"]["reference"].startswith("runs/01_face/")
    assert (folder / "inputs" / "source_first.png").is_file()
    motion = (folder / "runs" / "02_motion" / "workflow.api.json").read_text(encoding="utf-8")
    assert "the same setting as in the reference image" in motion and "studio backdrop" not in motion, \
        "a face-only re-shoot keeps the clip's own set"


def test_a_frame_of_another_shape_is_letterboxed_into_the_bridge(tmp_path):
    from openfield.pipeline import _letterbox
    tall = tmp_path / "tall.png"
    Image.new("RGB", (360, 640), "white").save(tall)
    _letterbox(tall, (1280, 704))
    with Image.open(tall) as img:
        assert img.size == (1280, 704)
        assert img.getpixel((10, 352)) == (0, 0, 0) and img.getpixel((640, 352)) == (255, 255, 255)  # padded, not stretched


async def test_behind_the_scenes_never_rerolls_over_the_crew_and_still_checks_the_shot(stack, tmp_path):
    stack.pipeline.gate = StubGate([])
    ref = make_image(tmp_path / "ref.png", "blue")
    take = await stack.pipeline.start_direct(direct(rig={"movement": "static", "effect": "bts"}, cast_refs=[ref], cast_name="Mara"))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "succeeded", done.get("error")
    runs = sorted(p.name for p in (stack.ledger.take_dir(take["id"]) / "runs").iterdir())
    assert runs == ["01_hero", "02_transform_1", "03_shoot_1"]
    receipt = json.loads((stack.ledger.take_dir(take["id"]) / "receipt.json").read_text(encoding="utf-8"))
    assert "crew" in receipt["identity"]["skipped"]["transform_1"] and "shoot_1" in done["identity"]
    graph = (stack.ledger.take_dir(take["id"]) / "runs" / "02_transform_1" / "workflow.api.json").read_text(encoding="utf-8")
    assert "face and identity stay exactly the same" in graph, "the prompt still asks to keep the face"


async def test_each_face_changing_transformation_records_its_own_reason(stack, tmp_path):
    stack.pipeline.gate = StubGate([])
    ref = make_image(tmp_path / "ref.png", "blue")
    take = await stack.pipeline.start_direct(direct(rig={"movement": "static", "effect": "clones"}, cast_refs=[ref], cast_name="Mara"))
    await stack.pipeline.wait(take["id"])
    receipt = json.loads((stack.ledger.take_dir(take["id"]) / "receipt.json").read_text(encoding="utf-8"))
    skipped = receipt["identity"]["skipped"]
    assert "copies" in skipped["transform_1"] and "copies" in skipped["shoot_1"]


async def test_a_transition_records_its_idea_only_when_given(stack):
    a, b = await _two_takes(stack.pipeline)
    take = await stack.pipeline.start_transition(TransitionRequest(first=a, second=b, style="push", seed=4,
                                                                   idea="the camera flies through the net into the sea"))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "succeeded", done.get("error")
    assert done["recipe"]["idea"] == "the camera flies through the net into the sea"
    receipt = json.loads((stack.ledger.take_dir(take["id"]) / "receipt.json").read_text(encoding="utf-8"))
    assert "How it gets there: the camera flies through the net into the sea." in receipt["inputs"]["final_prompt"]
    assert receipt["inputs"]["idea"] == "the camera flies through the net into the sea", "the receipt names the idea too"
    plain = await stack.pipeline.start_transition(TransitionRequest(first=a, second=b, style="push", seed=5))
    await stack.pipeline.wait(plain["id"])
    assert "idea" not in stack.ledger.read(plain["id"])["recipe"], "recorded transitions keep their fingerprint"
    assert "idea" not in json.loads((stack.ledger.take_dir(plain["id"]) / "receipt.json").read_text(encoding="utf-8"))["inputs"]


async def test_a_dutch_angle_is_rendered_level_and_larger_then_turned_and_cropped_to_the_frame(stack):
    take = await stack.pipeline.start_direct(direct(rig={"movement": "dutch_angle"}))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "succeeded", done.get("error")
    folder = stack.ledger.take_dir(take["id"])
    shoot = json.loads(next((folder / "runs").glob("*_shoot_1/workflow.api.json")).read_text(encoding="utf-8"))
    hero = json.loads(next((folder / "runs").glob("*_hero/workflow.api.json")).read_text(encoding="utf-8"))
    assert (shoot["398:372"]["inputs"]["value"], shoot["398:360"]["inputs"]["value"]) == (1856, 1024),         "standard's 1280x704 frame, enlarged for a 15 degree turn"
    assert (hero["459:456"]["inputs"]["width"], hero["459:456"]["inputs"]["height"]) == (1920, 1088), "a larger hero"
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    roll = receipt["inputs"]["roll"]
    assert roll["degrees"] == 15.0 and roll["size"] == [1280, 704] and roll["how"].startswith("rendered level")
    assert receipts.verify(receipt)
    info = video.probe(folder / "take.mp4")
    assert (info.width, info.height) == (1280, 704), "the take is the tier's usual frame"
    assert receipt["inputs"]["anchors"][0]["file"].startswith("runs/01_hero/"), "the shot starts from the level hero"
    assert "roll" not in done["recipe"]["rig"], "the roll comes from the move, so the recipe (and its fingerprint) is unchanged"


async def test_a_dutch_angle_from_a_persons_photo_says_how_much_of_the_photo_the_turn_keeps(stack, tmp_path):
    # a photo was not framed with room for the turn's crop (a generated hero is), so the take says what the crop keeps
    take = await stack.pipeline.start_direct(direct(source=photo(tmp_path / "me.jpg"), rig={"movement": "dutch_angle"}))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "succeeded", done.get("error")
    roll = json.loads((stack.ledger.take_dir(take["id"]) / "receipt.json").read_text(encoding="utf-8"))["inputs"]["roll"]
    kept = round(100 * roll["crop"][0] / roll["rendered"][0])
    assert 50 < kept < 90, roll
    assert f"The turn keeps the centre {kept}% of the width of your photo's frame" in " ".join(done["notes"]), done["notes"]
    plain = await stack.pipeline.start_direct(direct(rig={"movement": "dutch_angle"}))
    await stack.pipeline.wait(plain["id"])
    assert not any("The turn keeps" in n for n in stack.ledger.read(plain["id"])["notes"]), "a generated hero was framed for it"


async def test_a_mirrored_move_hands_ltx_the_flipped_hero_and_flips_the_take_back(stack):
    take = await stack.pipeline.start_direct(direct(rig={"movement": "track_left"}))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "succeeded", done.get("error")
    folder = stack.ledger.take_dir(take["id"])
    hero = next((folder / "runs").glob("*_hero"))
    still = next(p for p in hero.iterdir() if p.suffix == ".png" and not p.stem.endswith("_mirrored"))
    flipped = still.with_name(f"{still.stem}_mirrored{still.suffix}")
    assert flipped.is_file(), "the flipped hero sits beside the hero"
    with Image.open(still) as a, Image.open(flipped) as b:
        assert ImageOps.mirror(a.convert("RGB")).tobytes() == b.convert("RGB").tobytes()
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["inputs"]["mirror"]["rendered_as"] == "track_right" and receipts.verify(receipt)
    assert receipt["inputs"]["anchors"][0]["file"] == str(still.relative_to(folder)).replace("\\", "/"), "the kept hero is as made"
    assert done["recipe"]["rig"]["movement"] == "track_left", "the recipe keeps the move that was asked for"


async def test_the_dolly_zoom_renders_a_dolly_out_larger_and_zooms_it_to_the_frame(stack):
    take = await stack.pipeline.start_direct(direct(rig={"movement": "vertigo"}, auto_approve=True))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "succeeded", done.get("error")
    folder = stack.ledger.take_dir(take["id"])
    shoot = json.loads(next((folder / "runs").glob("*_shoot_1/workflow.api.json")).read_text(encoding="utf-8"))
    sizes = {node["inputs"].get("value") for node in shoot.values() if isinstance(node.get("inputs", {}).get("value"), int)}
    assert {1920, 1088} <= sizes, "rendered at the largest size the template allows"
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    made = receipt["inputs"]["reframe"]
    assert made["zoom"] == [1.0, 1.8] and made["size"] == [1280, 704] and receipts.verify(receipt)
    info = video.probe(folder / "take.mp4")
    assert (info.width, info.height) == (1280, 704), "the take is the tier's usual frame"
    assert made["track"] == "face" and made["tracked"] is False, "no face detector here: the fixed curve stands"
    assert made["reason"] == "no face detector was available, so the zoom followed the fixed curve"
    assert "No face detector was available, so the zoom followed the fixed curve." in done["notes"], "and the take says so"


class ShrinkingFace:
    """A face detector that sees one face, smaller in every frame it is shown, as a dolly-out renders it."""

    def __init__(self, heights: list[int]) -> None:
        self.heights = heights
        self.shown = 0

    def faces(self, image):
        h = self.heights[min(self.shown, len(self.heights) - 1)]
        self.shown += 1
        return [SimpleNamespace(box=(160 - 0.4 * h, 70 - h / 2, 0.8 * h, h))]  # the fake render is 320 x 180


class NoFace(ShrinkingFace):
    def faces(self, image):
        self.shown += 1
        return []


async def test_the_dolly_zoom_follows_the_face_so_it_keeps_its_size(stack):
    heights = [90, 80, 70, 60, 50, 45]
    gate = ShrinkingFace(heights)
    stack.pipeline.gate = gate
    take = await stack.pipeline.start_direct(direct(rig={"movement": "vertigo"}))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "succeeded", done.get("error")
    folder = stack.ledger.take_dir(take["id"])
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    made = receipt["inputs"]["reframe"]
    assert made["track"] == "face" and made["tracked"] is True and "reason" not in made and receipts.verify(receipt)
    assert made["found"] == made["samples"] == gate.shown >= 4, "the fake one-second render, sampled four times a second"
    last = heights[made["samples"] - 1]
    assert made["face_height_px"] == [90, last], "as detected, in the first and last frame"
    assert made["zoom"][0] == 1.0 and made["zoom"][1] == pytest.approx(90 / last, abs=1e-3), "the face holds its first height"
    assert made["keyframes"] == made["samples"] and made["size"] == [1280, 704] and "height" not in made
    info = video.probe(folder / "take.mp4")
    assert (info.width, info.height) == (1280, 704), "the take is the tier's usual frame"
    assert not any("fixed curve." in n for n in done["notes"])
    blind = NoFace([])
    stack.pipeline.gate = blind
    again = await stack.pipeline.start_direct(direct(rig={"movement": "vertigo"}, seed=8))
    await stack.pipeline.wait(again["id"])
    made = json.loads((stack.ledger.take_dir(again["id"]) / "receipt.json").read_text(encoding="utf-8"))["inputs"]["reframe"]
    assert made["tracked"] is False and made["zoom"] == [1.0, 1.8] and made["found"] == 0 and made["samples"] == blind.shown
    assert made["reason"] == (f"a face was found in 0 of {blind.shown} frames, too few to follow, so the zoom followed "
                              "the fixed curve")


class FramesSeen(StubGate):
    """A StubGate that keeps the images it was asked to check."""

    def __init__(self) -> None:
        super().__init__([])
        self.seen: list[Path] = []

    def check(self, refs, image):
        self.seen.append(Path(image))
        return super().check(refs, image)


def mean_difference(a: Path, b: Path) -> float:
    with Image.open(a) as x, Image.open(b) as y:
        return sum(ImageStat.Stat(ImageChops.difference(x.convert("RGB"), y.convert("RGB"))).mean) / 3


async def test_through_object_renders_a_dolly_out_and_delivers_it_played_backwards(stack, tmp_path):
    gate = FramesSeen()
    stack.pipeline.gate = gate
    ref = make_image(tmp_path / "ref.png", "blue")
    take = await stack.pipeline.start_direct(direct(rig={"movement": "through_object"}, cast_refs=[ref], cast_name="Mara"))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "succeeded", done.get("error")
    folder = stack.ledger.take_dir(take["id"])
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["inputs"]["reversed"] == {"picture": "reversed in code", "sound": "kept as rendered", "rendered_as": "dolly_out"}
    assert receipts.verify(receipt)
    assert "The camera dollies out" in receipt["inputs"]["final_prompt"] and "Your still is where the shot ends." in done["notes"]
    assert done["recipe"]["rig"]["movement"] == "through_object", "the recipe keeps the move that was asked for"
    hero = (next((folder / "runs").glob("*_hero/workflow.api.json"))).read_text(encoding="utf-8")
    assert "just inside an open doorway or window" in hero, "the still is where the push through ends"
    # the face is checked once, on the take as delivered, whose first frame is the render's last
    assert gate.calls == 4 and done["identity"]["shoot_1"]["frames_checked"] == 3, "the hero, then three frames of the take"
    checked = folder / "identity_frame_first.png"
    assert checked.is_file() and checked in gate.seen
    assert not list((folder / "runs").glob("*_shoot_1/identity_frame*.png")), "the render itself is not checked"
    render = next((folder / "runs").glob("*_shoot_1/*.mp4"))
    video.extract_frame(render, tmp_path / "render_first.png", "first")
    video.extract_frame(render, tmp_path / "render_last.png", "last")
    assert mean_difference(checked, tmp_path / "render_last.png") < mean_difference(checked, tmp_path / "render_first.png"), \
        "the frame checked first is the render's last: the face was checked on the reversed take"
    assert video.probe(folder / "take.mp4").has_audio, "the sound is kept"
