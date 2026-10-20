"""Fixes from the independent review: each of these was a real failure before it was fixed."""
from __future__ import annotations

import ast
import asyncio
import codecs
import io
import json
import os
import threading
import time
import zipfile
from pathlib import Path

import pytest

from openfield import fsutil, share
from openfield.backends.replay import ReplayBackend
from openfield.backends.sdk import SdkBackend
from openfield.config import load_env_file, parse_env_line
from openfield.engine import receipt as receipts
from openfield.engine import rig
from openfield.fsutil import replace_file
from openfield.ledger import Ledger, write_json
from openfield.pipeline import Pipeline, PortraitRequest, ReshootRequest
from openfield.static_export import StaticExportError, export_static

from .test_pipeline import WORKFLOWS, direct, make_clip, make_image, stack, until  # noqa: F401 (stack is a fixture)
from .test_static_export import settings_for, world  # noqa: F401 (world is a fixture)


def awaiting(stack, take_id):  # noqa: F811
    return lambda: (t := stack.ledger.read(take_id))["status"] == "awaiting_approval" and t


# -- the stills are approved before the video, whatever the move -------------------------------------

async def test_a_prompt_only_move_still_waits_for_approval_of_its_hero_still(stack):  # noqa: F811
    take = await stack.pipeline.start_direct(direct(rig={"movement": "static"}, auto_approve=False))
    waiting = await until(awaiting(stack, take["id"]))
    folder = stack.ledger.take_dir(take["id"])
    assert [a["index"] for a in waiting["anchors"]] == [0]
    assert sorted(p.name for p in (folder / "runs").iterdir()) == ["01_hero"], "no video is paid for yet"

    stack.pipeline.approve(take["id"], reroll=[0])  # not that one: make another
    await until(lambda: (folder / "runs" / "02_hero").is_dir())
    await until(awaiting(stack, take["id"]))
    stack.pipeline.approve(take["id"], reroll=[])
    await stack.pipeline.wait(take["id"])
    assert stack.ledger.read(take["id"])["status"] == "succeeded"
    assert sorted(p.name for p in (folder / "runs").iterdir()) == ["01_hero", "02_hero", "03_shoot_1"]


async def test_quick_mode_also_asks_before_the_video_and_auto_approve_skips_it(stack):  # noqa: F811
    quick = await stack.pipeline.start_direct(direct(prompt_only=True, auto_approve=False))
    await until(awaiting(stack, quick["id"]))
    stack.pipeline.approve(quick["id"])
    skipped = await stack.pipeline.start_direct(direct(rig={"movement": "static"}, auto_approve=True))
    await stack.pipeline.wait(skipped["id"])
    await stack.pipeline.wait(quick["id"])
    assert stack.ledger.read(quick["id"])["status"] == stack.ledger.read(skipped["id"])["status"] == "succeeded"


# -- a take stays on the backend it started on -------------------------------------------------------

async def test_switching_the_backend_mid_take_does_not_move_the_take(tmp_path, fake_api):
    ledger = Ledger(tmp_path / "takes")
    holder = {"backend": SdkBackend(base_url=fake_api.base_url)}
    pipeline = Pipeline(ledger, lambda: holder["backend"], WORKFLOWS, timeout=60.0)
    take = await pipeline.start_direct(direct(rig={"movement": "static"}, auto_approve=False))
    await until(lambda: ledger.read(take["id"])["status"] == "awaiting_approval")
    holder["backend"] = ReplayBackend([tmp_path / "nothing"])  # the person flips the switch while it waits
    pipeline.approve(take["id"])
    await pipeline.wait(take["id"])
    done = ledger.read(take["id"])
    assert done["status"] == "succeeded", done["error"]
    receipt = json.loads((ledger.take_dir(take["id"]) / "receipt.json").read_text())
    assert receipt["backend"]["kind"] == "pod" and receipt["backend"]["label"] == "GPU box"
    assert done["backend"]["kind"] == "pod"


# -- uploads belong to the take and go with it ---------------------------------------------------------

async def test_uploaded_files_are_deleted_however_the_take_ends(stack, tmp_path):  # noqa: F811
    def pair(name):
        return make_clip(tmp_path / f"{name}.mp4"), make_image(tmp_path / f"{name}.png")

    clip, ref = pair("good")
    done = await stack.pipeline.start_reshoot(ReshootRequest(clip, ref, "a courier in a raincoat", owned=(clip, ref)))
    await stack.pipeline.wait(done["id"])
    assert stack.ledger.read(done["id"])["status"] == "succeeded" and not clip.exists() and not ref.exists()

    bad = tmp_path / "bad.mp4"
    bad.write_text("this is not a video")
    ref2 = make_image(tmp_path / "bad.png")
    failed = await stack.pipeline.start_reshoot(ReshootRequest(bad, ref2, "a courier", owned=(bad, ref2)))
    await stack.pipeline.wait(failed["id"])
    assert stack.ledger.read(failed["id"])["status"] == "failed" and not bad.exists() and not ref2.exists()
    error = stack.ledger.read(failed["id"])["error"]  # its message quotes ffmpeg's complaint about the file
    message = f"{error['message']} {error.get('details', '')}"
    assert "bad.mp4" in message, "the complaint is kept; only the folder it came from goes"
    assert str(tmp_path) not in message and str(tmp_path).replace("\\", "/") not in message

    clip3, ref3 = pair("cancelled")
    cancelled = await stack.pipeline.start_reshoot(ReshootRequest(clip3, ref3, "a courier", owned=(clip3, ref3)))
    await stack.pipeline.cancel(cancelled["id"])  # before the task has taken a step
    assert stack.ledger.read(cancelled["id"])["status"] == "canceled" and not clip3.exists() and not ref3.exists()

    kept = make_image(tmp_path / "not-owned.png")
    clip4 = make_clip(tmp_path / "plain.mp4")
    plain = await stack.pipeline.start_reshoot(ReshootRequest(clip4, kept, "a courier"))
    await stack.pipeline.wait(plain["id"])
    assert clip4.exists() and kept.exists(), "files the pipeline was not given are never touched"


async def test_uploads_are_deleted_at_once_when_a_locked_backend_will_never_read_them(stack, tmp_path):  # noqa: F811
    replay = Pipeline(Ledger(tmp_path / "other"), lambda: ReplayBackend([tmp_path / "none"]), WORKFLOWS)
    clip, ref = make_clip(tmp_path / "r.mp4"), make_image(tmp_path / "r.png")
    take = await replay.start_reshoot(ReshootRequest(clip, ref, "a courier", owned=(clip, ref)))
    assert not clip.exists() and not ref.exists()
    await replay.wait(take["id"])
    assert replay.ledger.read(take["id"])["error"]["code"] == "replay_unavailable"


# -- takes that can never finish are not left hanging ------------------------------------------------

def test_a_take_waiting_for_approval_when_the_app_stopped_is_failed_on_restart(tmp_path):
    ledger = Ledger(tmp_path)
    waiting = ledger.create("direct", "x", {})
    running = ledger.create("direct", "y", {})
    done = ledger.create("direct", "z", {})
    ledger.update(waiting["id"], status="awaiting_approval")
    ledger.update(running["id"], status="running")
    ledger.update(done["id"], status="succeeded")
    fixed = Ledger(tmp_path).recover_interrupted()
    assert sorted(fixed) == sorted([waiting["id"], running["id"]])
    error = ledger.read(waiting["id"])["error"]
    assert error["code"] == "interrupted" and "waiting for your approval" in error["message"] and error["retryable"]
    assert "was running" in ledger.read(running["id"])["error"]["message"]
    assert ledger.read(done["id"])["status"] == "succeeded"


async def test_the_event_stream_of_a_finished_take_ends_even_without_an_end_event(stack):  # noqa: F811
    export = stack.ledger.create("export", "a crop", {})  # exports never publish events
    stack.ledger.update(export["id"], status="succeeded")

    async def collect():
        return [e async for e in stack.pipeline.subscribe(export["id"])]

    events = await asyncio.wait_for(collect(), timeout=5)
    assert [e["type"] for e in events] == ["take", "end"] and events[-1]["status"] == "succeeded"
    failed = stack.ledger.create("direct", "stopped", {})
    stack.ledger.update(failed["id"], status="failed")
    events = await asyncio.wait_for(collect_for(stack, failed["id"]), timeout=5)
    assert events[-1] == {"type": "end", "status": "failed"}


async def collect_for(stack, take_id):  # noqa: F811
    return [e async for e in stack.pipeline.subscribe(take_id)]


# -- what a take hands to other tools ---------------------------------------------------------------

async def test_the_workflow_zip_holds_each_steps_inputs_and_the_snippet_runs_anywhere(stack, tmp_path):  # noqa: F811
    take = await stack.pipeline.start_direct(direct())  # dolly_in: hero, anchor, one first-and-last-frame shot
    await stack.pipeline.wait(take["id"])
    folder = stack.ledger.take_dir(take["id"])
    archive = zipfile.ZipFile(io.BytesIO(share.workflows_zip(folder)))
    names = archive.namelist()
    assert {"01_hero.api.json", "02_anchor_1.api.json", "03_shoot_1.api.json", "README.txt"} <= set(names)
    graph = json.loads(archive.read("03_shoot_1.api.json").decode("utf-8"))
    loads = {n["inputs"]["image"] for n in graph.values() if n["class_type"] == "LoadImage"}
    assert loads == {"first_frame.png", "last_frame.png"}, "the two frames have different names"
    # (the fake API draws the same picture for every still, so the bytes may match; real renders differ)
    assert archive.read("inputs/03_shoot_1/first_frame.png")[:8] == b"\x89PNG\r\n\x1a\n"
    assert archive.read("inputs/03_shoot_1/last_frame.png")[:8] == b"\x89PNG\r\n\x1a\n"
    assert "inputs/<run>" not in archive.read("README.txt").decode()

    snippet = share.take_snippet(folder)
    ast.parse(snippet)  # valid Python
    assert 'encoding="utf-8"' in snippet, "the graph holds non-ASCII text; Windows would decode it as cp1252"
    assert "inputs/03_shoot_1/first_frame.png" in snippet and "inputs/03_shoot_1/last_frame.png" in snippet
    # the graph really does contain characters a cp1252 decode cannot read
    raw = (folder / "runs" / "03_shoot_1" / "workflow.api.json").read_bytes()
    with pytest.raises(UnicodeDecodeError):
        raw.decode("cp1252")


async def test_a_reference_photo_is_never_put_in_the_zip_but_the_zip_says_so(stack, tmp_path):  # noqa: F811
    ref = make_image(tmp_path / "mara.png")
    take = await stack.pipeline.start_direct(direct(rig={"movement": "static"}, cast_refs=[ref], cast_name="Mara"))
    await stack.pipeline.wait(take["id"])
    folder = stack.ledger.take_dir(take["id"])
    archive = zipfile.ZipFile(io.BytesIO(share.workflows_zip(folder)))
    assert not any(n.startswith("inputs/01_hero/") for n in archive.namelist()), "a cast photo is not copied out"
    readme = archive.read("README.txt").decode()
    assert "01_hero: base_image.png" in readme and "is not kept" in readme
    snippet = share.take_snippet(folder)  # the last step uses the hero still, which is kept
    assert "# this step uploads no files" not in snippet and "first_frame.png" in snippet
    record = json.loads((folder / "runs" / "01_hero" / "run.json").read_text())
    asset = next(a for a in record["assets"] if a["slot"] == "base_image")
    assert asset["from"] is None and len(asset["sha256"]) == 64


def test_the_zip_never_reaches_outside_the_take_folder(tmp_path):
    folder = tmp_path / "take"
    run = folder / "runs" / "01_hero"
    run.mkdir(parents=True)
    (run / "workflow.api.json").write_text("{}")
    secret = tmp_path / "secret.txt"
    secret.write_text("do not ship")
    (run / "run.json").write_text(json.dumps({"assets": [
        {"node": "1", "input": "image", "slot": "first_frame", "name": "x.png", "sha256": "0" * 64,
         "from": "../../../secret.txt"},
        {"node": "2", "input": "image", "slot": "last_frame", "name": "y.png", "sha256": "0" * 64, "from": "/etc/passwd"}]}))
    archive = zipfile.ZipFile(io.BytesIO(share.workflows_zip(folder)))
    assert sorted(archive.namelist()) == ["01_hero.api.json", "README.txt"]
    assert b"do not ship" not in b"".join(archive.read(n) for n in archive.namelist())


# -- the receipt rides in the images too -----------------------------------------------------------------

async def test_the_poster_and_the_generated_candidates_carry_the_receipt(stack):  # noqa: F811
    take = await stack.pipeline.start_direct(direct(rig={"movement": "static"}))
    await stack.pipeline.wait(take["id"])
    folder = stack.ledger.take_dir(take["id"])
    found, verified = receipts.read_media(folder / "poster.png")
    assert verified and found["take"]["id"] == take["id"]
    assert found == json.loads((folder / "receipt.json").read_text())

    portrait = await stack.pipeline.start_portrait(PortraitRequest("an old fisherman with a white beard", count=2, seed=5))
    await stack.pipeline.wait(portrait["id"])
    pfolder = stack.ledger.take_dir(portrait["id"])
    for name in ("candidates/01.png", "candidates/02.png"):
        found, verified = receipts.read_media(pfolder / name)
        assert verified and found["take"]["kind"] == "portrait", name
    assert not list(pfolder.rglob("*.embedded.png")), "no temporary copies are left behind"


# -- errors never carry this machine's paths -------------------------------------------------------------

async def test_a_failure_message_does_not_leak_a_local_path(stack, fake_api):  # noqa: F811
    fake_api.fail_with = {"code": "node_execution_error", "node_id": "1", "class_type": "LoadVideo",
                          "message": "Cannot open C:" + "\\Users\\Alex\\Videos\\clip.mp4 for reading"}
    take = await stack.pipeline.start_direct(direct(rig={"movement": "static"}))
    await stack.pipeline.wait(take["id"])
    error = stack.ledger.read(take["id"])["error"]
    assert error["code"] == "job_failed" and "clip.mp4" in error["message"]
    text = json.dumps(error)
    assert "Alex" not in text and ("C:" + "\\Users") not in text


# -- files written by two threads, read by a third (Windows) ------------------------------------------------

def test_replace_file_rides_out_a_destination_that_is_briefly_locked(tmp_path, monkeypatch):
    calls = {"n": 0}
    real = os.replace

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 4:
            raise PermissionError(13, "Access is denied")
        real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    source, target = tmp_path / "a.txt", tmp_path / "b.txt"
    source.write_text("new")
    target.write_text("old")
    replace_file(source, target)
    assert calls["n"] == 4 and target.read_text() == "new"

    calls["n"] = -1000  # never succeeds
    source.write_text("again")
    with pytest.raises(PermissionError):
        replace_file(source, target, attempts=5)


def test_a_json_write_that_cannot_complete_leaves_no_temporary_file(tmp_path, monkeypatch):
    target = tmp_path / "take.json"
    write_json(target, {"v": 1})
    monkeypatch.setattr(fsutil.time, "sleep", lambda _: None)

    def locked(src, dst):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(os, "replace", locked)
    with pytest.raises(PermissionError):
        write_json(target, {"v": 2})
    monkeypatch.undo()
    assert json.loads(target.read_text()) == {"v": 1}, "the old file is intact"
    assert not list(tmp_path.glob("*.tmp")), "and no temporary file is left"


def test_concurrent_updates_never_lose_each_others_changes(tmp_path):
    ledger = Ledger(tmp_path)
    take = ledger.create("direct", "x", {})
    barrier = threading.Barrier(16)

    def work(i):
        barrier.wait()
        for round_ in range(5):
            ledger.update(take["id"], **{f"k{i}_{round_}": i})

    threads = [threading.Thread(target=work, args=(i,)) for i in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    final = ledger.read(take["id"])
    written = [key for key in final if key.startswith("k") and "_" in key]  # the take's own "kind" field is not ours
    assert len(written) == 16 * 5
    assert not list((tmp_path / take["id"]).glob("*.tmp"))


def test_reading_a_take_retries_while_a_writer_holds_the_file(tmp_path, monkeypatch):
    ledger = Ledger(tmp_path)
    take = ledger.create("direct", "x", {})
    real = Path.read_text
    state = {"n": 0}

    def flaky(self, *args, **kwargs):
        if self.name == "take.json" and state["n"] < 3:
            state["n"] += 1
            raise PermissionError(13, "The process cannot access the file")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky)
    monkeypatch.setattr(fsutil.time, "sleep", lambda _: None)
    assert ledger.read(take["id"])["id"] == take["id"] and state["n"] == 3


def test_files_the_library_writes_are_byte_identical_on_every_os(tmp_path, world):  # noqa: F811
    """Text mode would write CRLF on Windows: showcase files and hashes must not depend on the OS."""
    ledger = Ledger(tmp_path / "ledger")
    take = ledger.create("direct", "x", {"a": 1})
    assert b"\r" not in (ledger.take_dir(take["id"]) / "take.json").read_bytes()

    sealed = receipts.seal(receipts.new_receipt(take_id=take["id"], kind="direct", label="x"))
    media = tmp_path / "take.mp4"
    media.write_bytes(b"x")
    receipts.write_sidecar(media, sealed)
    assert b"\r" not in (tmp_path / "take.mp4.receipt.json").read_bytes()

    base, web, root = world
    out = base / "site"
    export_static(settings_for(base, web, base / "unused"), out, takes_root=root, web_dir=web)
    for path in out.rglob("*"):
        if path.suffix in {".json", ".py"} and "showcase" in path.parts or path.name == "manifest.json":
            assert b"\r" not in path.read_bytes(), path


# -- .env files as Windows tools write them ------------------------------------------------------------------

ENV_TEXT = ('A_ONE=1\nexport B_TWO="two # not a comment"\nC_THREE=three # a comment\n# D_FOUR=skipped\n'
            "  E_FIVE = 'five'  \nnot a pair\nbad name=1\nF_SIX=\nG_SEVEN=a#b\n")


@pytest.mark.parametrize("encode", [
    lambda text: text.encode("utf-8"),
    lambda text: codecs.BOM_UTF8 + text.encode("utf-8"),  # PowerShell: Out-File -Encoding utf8
    lambda text: text.encode("utf-16"),                    # PowerShell 5.1: echo K=V > .env
    lambda text: text.replace("\n", "\r\n").encode("utf-8"),
], ids=["utf8", "utf8-bom", "utf16", "crlf"])
def test_env_files_are_read_whatever_encoding_a_windows_tool_wrote(tmp_path, monkeypatch, encode):
    monkeypatch.setattr(os, "environ", {})
    path = tmp_path / ".env"
    path.write_bytes(encode(ENV_TEXT))
    assert load_env_file(path) == 6
    assert os.environ == {"A_ONE": "1", "B_TWO": "two # not a comment", "C_THREE": "three", "E_FIVE": "five",
                          "F_SIX": "", "G_SEVEN": "a#b"}, "the first line is not lost to a BOM"


def test_env_loading_never_overrides_what_is_already_set(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", {"A_ONE": "from the shell"})
    path = tmp_path / ".env"
    path.write_text("A_ONE=from the file\nB_TWO=2\n", encoding="utf-8")
    assert load_env_file(path) == 1 and os.environ["A_ONE"] == "from the shell"
    assert load_env_file(tmp_path / "missing.env") == 0
    assert parse_env_line("COMFY_API_KEY=abc  # secret!") == ("COMFY_API_KEY", "abc")
    assert parse_env_line("=nothing") is None


# -- limits that must agree ---------------------------------------------------------------------------------

def test_the_longest_shot_the_rig_allows_is_the_longest_the_templates_accept():
    folder = Path(__file__).resolve().parents[1] / "openfield" / "workflows"
    for name in ("ltx25_i2v", "ltx25_flf2v"):
        slot = json.loads((folder / f"{name}.slots.json").read_text(encoding="utf-8"))["slots"]["duration"]
        assert (slot["min"], slot["max"]) == (rig.MIN_DURATION_SECONDS, rig.MAX_DURATION_SECONDS), name
    for seconds in (rig.MIN_DURATION_SECONDS, rig.MAX_DURATION_SECONDS):
        rig.CameraRig(duration_seconds=seconds).validate()
    for seconds in (rig.MIN_DURATION_SECONDS - 1, rig.MAX_DURATION_SECONDS + 1, 20):
        with pytest.raises(ValueError, match="between 2 and 10"):
            rig.CameraRig(duration_seconds=seconds).validate()
    catalog = rig.catalog()
    assert catalog["limits"]["duration_seconds"] == [2, 10] and catalog["defaults"]["movement"] == "dolly_in"


def test_a_too_long_shot_is_refused_up_front_not_after_the_stills_are_paid_for(client):
    body = {"subject": "A lighthouse at dusk", "rig": {"movement": "static", "duration_seconds": 12}}
    for path in ("/api/direct/plan", "/api/takes/direct"):
        r = client.post(path, json=body)
        assert r.status_code == 422 and "between 2 and 10" in r.json()["error"]["message"], path
    assert client.get("/api/takes").json() == []


# -- export-static deletes only what it made ------------------------------------------------------------------

def test_export_static_never_deletes_a_folder_that_merely_looks_similar(world):  # noqa: F811
    tmp_path, web, root = world
    settings = settings_for(tmp_path, web, tmp_path / "unused")
    foreign = tmp_path / "someone-elses-site"
    (foreign / "static").mkdir(parents=True)
    (foreign / "static" / "manifest.json").write_text('{"name": "A PWA", "start_url": "/"}')
    (foreign / "src").mkdir()
    (foreign / "src" / "precious.py").write_text("keep me")
    with pytest.raises(StaticExportError, match="not empty"):
        export_static(settings, foreign, takes_root=root, web_dir=web)
    assert (foreign / "src" / "precious.py").read_text() == "keep me"

    broken = tmp_path / "broken"
    (broken / "static").mkdir(parents=True)
    (broken / "static" / "manifest.json").write_text("not json")
    (broken / "keep.txt").write_text("keep me")
    with pytest.raises(StaticExportError):
        export_static(settings, broken, takes_root=root, web_dir=web)
    assert (broken / "keep.txt").exists()

    ours = tmp_path / "ours"
    export_static(settings, ours, takes_root=root, web_dir=web)
    (ours / "stale.txt").write_text("from an earlier export")
    export_static(settings, ours, takes_root=root, web_dir=web)
    assert not (ours / "stale.txt").exists(), "a real previous export is replaced"
