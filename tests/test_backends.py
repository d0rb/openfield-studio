from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from PIL import Image

from openfield.backends.base import BackendError, media_kind
from openfield.backends.replay import ReplayBackend, hero_reel, hero_take
from openfield.backends.sdk import SdkBackend, classify
from openfield.engine.workflows import load_template

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def patched(tmp_path):
    first, last = tmp_path / "first.png", tmp_path / "last.png"
    Image.new("RGB", (64, 36), "red").save(first)
    Image.new("RGB", (64, 36), "blue").save(last)
    template = load_template("mini_ltx_flf2v", FIXTURES)
    return template.patch({"prompt": "A lighthouse.", "first_frame": first, "last_frame": last})


def backend_for(fake_api, **kwargs):
    return SdkBackend(base_url=fake_api.base_url, **kwargs)


async def test_happy_path_records_events_and_downloads_a_real_video(fake_api, patched, tmp_path):
    seen: list[dict] = []
    backend = backend_for(fake_api)
    result = await backend.run(patched, out_dir=tmp_path / "run", on_event=seen.append)

    video = result.files["video"]
    assert result.status == "succeeded" and result.backend == "pod"
    assert video.path.is_file() and video.size_bytes > 1000
    # the proxy reports SaveVideo as type="image"; we classify by content type instead
    assert video.content_type == "video/mp4" and video.kind == "video"
    kinds = [e["kind"] for e in seen]
    assert kinds[:2] == ["uploading", "submitted"]
    assert {"progress", "preview", "output", "status"} <= set(kinds)
    assert (tmp_path / "run" / "preview.jpg").is_file()
    assert json.loads((tmp_path / "run" / "job.json").read_text())["job_id"] == result.job_id
    lines = (tmp_path / "run" / "events.jsonl").read_text().splitlines()
    assert len(lines) == len(seen) and all(json.loads(ln)["t"] >= 0 for ln in lines)
    assert sorted(fake_api.uploads) == ["first.png", "last.png"]


async def test_second_run_deduplicates_unchanged_uploads(fake_api, patched, tmp_path):
    backend = backend_for(fake_api)
    await backend.run(patched, out_dir=tmp_path / "a")
    before = len(fake_api.uploads)
    await backend.run(patched, out_dir=tmp_path / "b")
    assert len(fake_api.uploads) == before  # blake3 content addressing: nothing re-sent


async def test_auth_failure_is_a_clear_error_and_a_key_fixes_it(fake_api, patched, tmp_path):
    fake_api.token = "secret"
    with pytest.raises(BackendError) as info:
        await backend_for(fake_api).run(patched, out_dir=tmp_path / "x")
    assert info.value.code == "unauthorized"
    result = await backend_for(fake_api, api_key="secret").run(patched, out_dir=tmp_path / "y")
    assert result.status == "succeeded"


async def test_a_job_the_server_forgot_is_a_clear_retryable_error(fake_api, patched, tmp_path):
    fake_api.end_with = "expired"
    with pytest.raises(BackendError) as info:
        await backend_for(fake_api).run(patched, out_dir=tmp_path / "e")
    err = info.value
    assert err.code == "job_expired" and err.retryable and err.job_id
    assert "Run it again" in str(err) and "None" not in str(err)


async def test_a_job_cancelled_elsewhere_never_reads_as_none(fake_api, patched, tmp_path):
    fake_api.end_with = "canceled"
    with pytest.raises(BackendError) as info:
        await backend_for(fake_api).run(patched, out_dir=tmp_path / "c")
    assert info.value.code == "job_failed" and "None" not in str(info.value) and "canceled" in str(info.value)


async def test_job_failure_names_the_node(fake_api, patched, tmp_path):
    fake_api.fail_with = {
        "code": "node_execution_error", "message": "CUDA out of memory",
        "node_id": "251:211", "class_type": "SamplerCustomAdvanced",
    }
    with pytest.raises(BackendError) as info:
        await backend_for(fake_api).run(patched, out_dir=tmp_path / "f")
    err = info.value
    assert err.code == "job_failed" and err.job_id
    assert "251:211" in str(err) and "out of memory" in str(err)


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [(402, "insufficient_credits", "insufficient_credits"), (422, "invalid_workflow", "invalid_workflow"),
     (422, "missing_asset", "missing_asset")],
)
async def test_submit_rejections_map_to_stable_codes(fake_api, patched, tmp_path, status, code, expected):
    fake_api.reject_next_submit = (status, code, "nope")
    with pytest.raises(BackendError) as info:
        await backend_for(fake_api).run(patched, out_dir=tmp_path / "r")
    assert info.value.code == expected


async def test_unreachable_server_is_reported_as_such(patched, tmp_path):
    backend = SdkBackend(base_url="http://127.0.0.1:9", request_timeout=2.0)
    with pytest.raises(BackendError) as info:
        await backend.run(patched, out_dir=tmp_path / "u")
    assert info.value.code == "unreachable" and info.value.retryable


async def test_timeout_cancels_the_job(fake_api, patched, tmp_path):
    fake_api.delay = 1.0
    with pytest.raises(BackendError) as info:
        await backend_for(fake_api).run(patched, out_dir=tmp_path / "t", timeout=0.2)
    assert info.value.code == "timeout"
    await asyncio.sleep(0.1)
    assert any(j.cancel_requested for j in fake_api.jobs.values())


async def test_cancelling_the_task_cancels_the_remote_job(fake_api, patched, tmp_path):
    fake_api.delay = 0.5
    task = asyncio.create_task(backend_for(fake_api).run(patched, out_dir=tmp_path / "c"))
    await asyncio.sleep(0.8)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert any(j.cancel_requested for j in fake_api.jobs.values())


async def test_any_failure_after_submit_cancels_the_remote_job(fake_api, patched, tmp_path):
    """A full disk while recording, a dropped connection, anything: a job left running is billed unseen."""
    fake_api.delay = 0.2

    def disk_full(event):
        if event["kind"] == "progress":
            raise OSError(28, "No space left on device")

    with pytest.raises(BackendError) as info:
        await backend_for(fake_api).run(patched, out_dir=tmp_path / "d", on_event=disk_full, timeout=30)
    assert info.value.code == "unexpected" and "No space left" in str(info.value)
    await asyncio.sleep(0.5)  # the fake notices a cancel request at its next step
    jobs = list(fake_api.jobs.values())
    assert len(jobs) == 1 and jobs[0].cancel_requested and jobs[0].status == "canceled"


async def test_a_finished_job_is_never_cancelled_after_the_fact(fake_api, patched, tmp_path):
    fake_api.fail_with = {"code": "node_execution_error", "message": "boom", "node_id": "1", "class_type": "X"}
    with pytest.raises(BackendError):
        await backend_for(fake_api).run(patched, out_dir=tmp_path / "f")
    assert not any(j.cancel_requested for j in fake_api.jobs.values())


async def test_the_timeout_is_one_budget_for_the_whole_render(fake_api, patched, tmp_path):
    """The wait after the event stream must not get a fresh fixed minute (nor cut a long render short)."""
    fake_api.delay = 0.3
    started = asyncio.get_running_loop().time()
    result = await backend_for(fake_api).run(patched, out_dir=tmp_path / "b", timeout=60)
    assert result.status == "succeeded"
    assert asyncio.get_running_loop().time() - started < 30


async def test_health_reports_reachability(fake_api):
    assert (await backend_for(fake_api).health())["ok"] is True
    down = await SdkBackend(base_url="http://127.0.0.1:9").health()
    assert down["ok"] is False
    assert down["code"] == "unreachable" and "tunnel" in down["detail"]
    fake_api.plain_comfy = True  # the person pasted ComfyUI's own address instead of the proxy's
    plain = await backend_for(fake_api).health()
    assert plain["ok"] is False and plain["code"] == "not_a_proxy" and "comfy-api-proxy" in plain["detail"]
    fake_api.plain_comfy = False
    fake_api.token = "t0k3n"
    assert (await backend_for(fake_api).health())["code"] == "missing_api_key"
    assert (await backend_for(fake_api, api_key="nope").health())["code"] == "unauthorized"
    assert (await backend_for(fake_api, api_key="t0k3n").health())["ok"] is True


def test_backend_kinds():
    assert classify(None)[0] == "cloud"
    assert classify("https://cloud.comfy.org")[0] == "cloud"
    assert classify("https://abc.run.comfy.app")[0] == "deployment"
    assert classify("http://127.0.0.1:8189")[0] == "pod"


def test_media_kind_ignores_the_api_type_field():
    assert media_kind("video/mp4", "x.bin") == "video"
    assert media_kind("", "clip.MP4") == "video"
    assert media_kind("application/octet-stream", "a.png") == "image"
    assert media_kind("audio/wav", "") == "audio"


async def test_replay_indexes_only_complete_recorded_takes_and_never_renders(patched, tmp_path):
    root = tmp_path / "takes"

    def record(name, **take):
        folder = root / name
        folder.mkdir(parents=True)
        (folder / "take.json").write_text(json.dumps({
            "id": name, "kind": "direct", "label": name, "recipe": {"subject": name},
            "outputs": [], "status": "succeeded", "replay": False, **take}))
        return folder

    good = record("tk_20261016_120000_aaaa", recipe_hash="h-good")
    (good / "receipt.json").write_text("{}")
    record("tk_20261016_120001_bbbb", recipe_hash="h-no-receipt")  # no receipt.json
    unfinished = record("tk_20261016_120002_cccc", recipe_hash="h-failed", status="failed")
    (unfinished / "receipt.json").write_text("{}")
    echo = record("tk_20261016_120003_dddd", recipe_hash="h-echo", replay=True)  # a replay of a replay
    (echo / "receipt.json").write_text("{}")

    replay = ReplayBackend([root, tmp_path / "missing-dir"])
    assert replay.locked and replay.kind == "replay"
    assert set(replay.index()) == {"h-good"}
    assert replay.find("h-good") == good and replay.find("h-failed") is None
    assert [r["recipe_hash"] for r in replay.recorded()] == ["h-good"]
    assert "media_base" not in replay.recorded()[0]
    shelf = replay.recorded({root: "/showcase/takes/{id}", tmp_path / "unrelated": "/x/{id}"})
    assert shelf[0]["media_base"] == "/showcase/takes/tk_20261016_120000_aaaa"
    proof = json.loads((good / "take.json").read_text(encoding="utf-8"))
    proof.update(identity={"hero": {"status": "same", "score": 0.81}}, audit={"result": "pass"})
    (good / "take.json").write_text(json.dumps(proof), encoding="utf-8")
    entry = replay.recorded()[0]
    assert entry["identity"]["hero"]["score"] == 0.81 and entry["audit"] == {"result": "pass"}
    assert replay.folder("tk_20261016_120000_aaaa") == good and replay.folder("tk_20261016_120001_bbbb") is None
    assert replay.folder("../etc") is None
    assert "1 recorded take" in (await replay.health())["detail"]

    with pytest.raises(BackendError) as info:
        await replay.run(patched, out_dir=tmp_path / "nope")
    assert info.value.code == "replay_unavailable"


def test_a_kept_superseded_take_never_shadows_its_re_record(tmp_path):
    """A forced re-record of an unchanged spec has the same recipe hash; the old folder stays when other takes point at it."""
    def record(root, name, created, digest="h-lava"):
        folder = root / name
        folder.mkdir(parents=True)
        (folder / "take.json").write_text(json.dumps({
            "id": name, "kind": "direct", "label": name, "recipe": {"subject": "lava surfer"}, "outputs": [],
            "status": "succeeded", "recipe_hash": digest, "created_at": created}), encoding="utf-8")
        (folder / "receipt.json").write_text("{}", encoding="utf-8")
        return folder

    shelf = tmp_path / "showcase"
    record(shelf, "tk_20261021_090000_aaaa", "2026-10-21T09:00:00Z")  # kept: a transition and an extension point at it
    redo = record(shelf, "tk_20261023_100000_bbbb", "2026-10-23T10:00:00Z")
    record(shelf, "tk_20261022_090000_cccc", "2026-10-22T09:00:00Z")
    replay = ReplayBackend([shelf])
    assert replay.find("h-lava") == redo and [r["id"] for r in replay.recorded()] == [redo.name]
    mine = record(tmp_path / "takes", "tk_20261020_080000_dddd", "2026-10-20T08:00:00Z")
    assert ReplayBackend([tmp_path / "takes", shelf]).find("h-lava") == mine, "an earlier root still wins, as before"


def test_the_showcase_names_its_hero_and_the_filmstrip_order(tmp_path):
    assert hero_take(tmp_path) is None and hero_reel(tmp_path) == []
    (tmp_path / "hero.json").write_text(json.dumps({"take": "tk_a", "reel": ["tk_b", "", 3, "tk_a"]}), encoding="utf-8")
    assert hero_take(tmp_path) == "tk_a"
    assert hero_reel(tmp_path) == ["tk_b", "tk_a"]  # names only, in the order given
    (tmp_path / "hero.json").write_text("{not json", encoding="utf-8")
    assert hero_take(tmp_path) is None and hero_reel(tmp_path) == []


def test_the_per_request_timeout_comes_from_the_environment_or_the_default(monkeypatch):
    from openfield.backends import sdk as sdk_module

    monkeypatch.delenv("OPENFIELD_REQUEST_TIMEOUT", raising=False)
    assert SdkBackend(base_url="http://127.0.0.1:9")._request_timeout == sdk_module.DEFAULT_REQUEST_TIMEOUT
    monkeypatch.setenv("OPENFIELD_REQUEST_TIMEOUT", "900")
    assert SdkBackend(base_url="http://127.0.0.1:9")._request_timeout == 900.0
    assert SdkBackend(base_url="http://127.0.0.1:9", request_timeout=2.0)._request_timeout == 2.0, "an explicit value wins"
    monkeypatch.setenv("OPENFIELD_REQUEST_TIMEOUT", "soon")
    assert SdkBackend(base_url="http://127.0.0.1:9")._request_timeout == sdk_module.DEFAULT_REQUEST_TIMEOUT
    monkeypatch.setenv("OPENFIELD_REQUEST_TIMEOUT", "-5")
    assert SdkBackend(base_url="http://127.0.0.1:9")._request_timeout == sdk_module.DEFAULT_REQUEST_TIMEOUT
