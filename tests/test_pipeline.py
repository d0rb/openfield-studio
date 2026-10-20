from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import imageio_ffmpeg
import pytest
from PIL import Image

from openfield.backends.base import BackendError
from openfield.backends.replay import ReplayBackend
from openfield.backends.sdk import SdkBackend
from openfield.engine import receipt as receipts
from openfield.engine import video
from openfield.ledger import Ledger
from openfield.pipeline import DirectRequest, Pipeline, PortraitRequest, ReshootRequest

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

    receipt = json.loads((folder / "receipt.json").read_text())
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
    receipt = json.loads((stack.ledger.take_dir(quick["id"]) / "receipt.json").read_text())
    assert [r["template"] for r in receipt["workflow"]["runs"]] == ["qwen21_t2i", "ltx25_i2v"]
    assert receipt["inputs"]["mode"] == "prompt_only"


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


async def test_full_orbit_joins_four_segments(stack):
    take = await stack.pipeline.start_direct(direct(rig={"movement": "orbit_360", "duration_seconds": 5}))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    assert done["status"] == "succeeded"
    folder = stack.ledger.take_dir(take["id"])
    shoots = [p for p in (folder / "runs").iterdir() if "shoot" in p.name]
    assert len(shoots) == 4
    assert video.probe(folder / "take.mp4").duration_s > 3.0  # four 1s fake clips joined
    receipt = json.loads((folder / "receipt.json").read_text())
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
    receipt = json.loads((stack.ledger.take_dir(take["id"]) / "receipt.json").read_text())
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
    assert gates and sum(g.calls for g in gates) == 2, "the hero still and the rendered shot are both checked"


async def test_the_shot_is_checked_too_and_a_drifting_shot_is_reported_not_re_rendered(stack, tmp_path):
    refs = [make_image(tmp_path / "ref.png")]
    gate = StubGate(["pass", "drift"])  # the hero holds, the rendered shot does not
    stack.pipeline.gate = gate
    take = await stack.pipeline.start_direct(direct(rig={"movement": "static"}, cast_refs=refs, cast_name="Mara"))
    await stack.pipeline.wait(take["id"])
    done = stack.ledger.read(take["id"])
    folder = stack.ledger.take_dir(take["id"])
    assert done["status"] == "succeeded" and gate.calls == 2
    assert done["identity"]["hero"]["status"] == "pass" and done["identity"]["shoot_1"]["status"] == "drift"
    runs = sorted(p.name for p in (folder / "runs").iterdir())
    assert not any("retry" in r for r in runs), "a video is never re-rolled automatically"
    assert (folder / "runs" / "02_shoot_1" / "identity_frame.png").is_file()
    receipt = json.loads((folder / "receipt.json").read_text())
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
    fake_api.delay = 0.5
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
    receipt = json.loads((folder / "receipt.json").read_text())
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

    receipt = json.loads((folder / "receipt.json").read_text())
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
