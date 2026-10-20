from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from openfield.cli import main as cli_main
from openfield.config import Settings
from openfield.engine import receipt as receipts
from openfield.ledger import write_json
from openfield.static_export import MANIFEST, StaticExportError, export_static, recorded_takes

GOOD = "tk_20261016_120000_aaaa"
NEWER = "tk_20261016_130000_bbbb"


def settings_for(tmp_path: Path, web: Path, showcase: Path) -> Settings:
    return Settings(
        host="127.0.0.1", port=0, data_dir=tmp_path / "data", backend="replay", comfy_base_url=None,
        has_api_key=False, workflow_dir=tmp_path / "wf", showcase_dir=showcase, web_dir=web)


def record(root: Path, take_id: str, *, created: str, status: str = "succeeded", replay: bool = False,
           kind: str = "direct", with_receipt: bool = True, with_video: bool = True) -> Path:
    folder = root / take_id
    (folder / "runs" / "01_hero").mkdir(parents=True)
    (folder / "inputs").mkdir()
    write_json(folder / "take.json", {
        "id": take_id, "kind": kind, "label": f"take {take_id[-4:]}", "status": status, "replay": replay,
        "created_at": created, "recipe": {"subject": "A lighthouse", "rig": {"movement": "static"}},
        "recipe_hash": f"hash-{take_id[-4:]}", "outputs": [{"role": "video", "file": "take.mp4"}]})
    if with_video:
        (folder / "take.mp4").write_bytes(b"mp4-bytes")
    (folder / "poster.png").write_bytes(b"png")
    (folder / "events.jsonl").write_text('{"t": 0, "type": "end", "status": "succeeded"}\n')
    (folder / "take.mp4.receipt.json").write_text("{}")
    (folder / "inputs" / "source.mp4").write_bytes(b"src")
    (folder / "runs" / "01_hero" / "image.png").write_bytes(b"still")
    (folder / "runs" / "01_hero" / "preview.jpg").write_bytes(b"jpg")
    (folder / "runs" / "01_hero" / "preview.jpg.tmp").write_bytes(b"half")
    (folder / "runs" / "01_hero" / "video.mp4").write_bytes(b"intermediate clip")
    (folder / "runs" / "01_hero" / "run.json").write_text("{}")
    write_json(folder / "runs" / "01_hero" / "workflow.api.json",
               {"1": {"class_type": "KSampler", "inputs": {}}})
    if with_receipt:
        raw = receipts.new_receipt(
            take_id=take_id, kind=kind, label="x", models=[],
            audit={"policy": "open-weights-only", "result": "pass", "disallowed": []})
        write_json(folder / "receipt.json", receipts.seal(raw))
    return folder


@pytest.fixture
def world(tmp_path):
    web = tmp_path / "web"
    (web / "js").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>OpenField</title>")
    (web / "js" / "app.js").write_text("export {};")
    (web / "package.json").write_text("{}")
    (web / "showcase" / "takes" / "stale").mkdir(parents=True)
    (web / "showcase" / "takes" / "stale" / "x.txt").write_text("x")
    root = tmp_path / "recorded"
    record(root, GOOD, created="2026-10-16T12:00:00Z")
    record(root, NEWER, created="2026-10-16T13:00:00Z", kind="reshoot")
    record(root, "tk_20261016_140000_cccc", created="2026-10-16T14:00:00Z", status="failed")
    record(root, "tk_20261016_150000_dddd", created="2026-10-16T15:00:00Z", replay=True)
    record(root, "tk_20261016_160000_eeee", created="2026-10-16T16:00:00Z", with_receipt=False)
    record(root, "tk_20261016_170000_ffff", created="2026-10-16T17:00:00Z", with_video=False)
    return tmp_path, web, root


def test_only_finished_rendered_takes_are_picked_newest_first(world):
    _, _, root = world
    assert [p.name for p in recorded_takes(root)] == [NEWER, GOOD]
    assert recorded_takes(root / "missing") == []


def test_the_export_holds_the_app_the_manifest_and_only_what_viewers_need(world):
    tmp_path, web, root = world
    out = tmp_path / "site"
    result = export_static(settings_for(tmp_path, web, tmp_path / "unused"), out, takes_root=root, web_dir=web)
    assert result["takes"] == 2 and result["recorded"] == 2 and result["media_bytes"] > 0

    # the app, without the dev-only bits
    assert (out / "index.html").is_file() and (out / "js" / "app.js").is_file()
    assert not (out / "package.json").exists() and not (out / "showcase" / "takes" / "stale").exists()
    assert (out / ".nojekyll").is_file()

    manifest = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    assert manifest["static"] is True and manifest["cast"] == []
    status = manifest["status"]
    assert status["static"] and status["backend"]["locked"] and status["backend"]["kind"] == "replay"
    assert status["recorded_takes"] == 2 and status["face_check"]["available"] is False
    assert len(manifest["moves"]["moves"]) == 35
    assert [t["id"] for t in manifest["takes"]] == [NEWER, GOOD]
    assert manifest["takes"][1]["media_base"] == f"showcase/takes/{GOOD}"
    shelf = {r["id"]: r for r in manifest["recorded"]}
    assert shelf[GOOD]["media_base"] == f"showcase/takes/{GOOD}"
    assert shelf[GOOD]["recipe"]["subject"] == "A lighthouse"

    folder = out / "showcase" / "takes" / GOOD
    for name in ("take.json", "receipt.json", "events.jsonl", "take.mp4", "poster.png", "take.mp4.receipt.json",
                 "receipt.view.json", "workflows.zip", "sdk-snippet.py", "inputs/source.mp4",
                 "runs/01_hero/image.png", "runs/01_hero/preview.jpg"):
        assert (folder / name).is_file(), name
    for name in ("runs/01_hero/video.mp4", "runs/01_hero/workflow.api.json", "runs/01_hero/run.json",
                 "runs/01_hero/preview.jpg.tmp"):
        assert not (folder / name).exists(), name
    for skipped in ("tk_20261016_140000_cccc", "tk_20261016_150000_dddd", "tk_20261016_160000_eeee",
                    "tk_20261016_170000_ffff"):
        assert not (out / "showcase" / "takes" / skipped).exists(), skipped

    view = json.loads((folder / "receipt.view.json").read_text(encoding="utf-8"))
    assert view["verified"] is True and view["recipe_link"]
    archive = zipfile.ZipFile(io.BytesIO((folder / "workflows.zip").read_bytes()))
    assert sorted(archive.namelist()) == ["01_hero.api.json", "README.txt"]
    assert "01_hero.api.json" in (folder / "sdk-snippet.py").read_text(encoding="utf-8")


def test_the_site_never_carries_this_machines_paths(world):
    tmp_path, web, root = world
    out = tmp_path / "site"
    export_static(settings_for(tmp_path, web, tmp_path / "unused"), out, takes_root=root, web_dir=web)
    for path in out.rglob("*.json"):
        assert str(tmp_path) not in path.read_text(encoding="utf-8"), path


def test_exporting_over_a_previous_export_replaces_it_but_never_other_folders(world):
    tmp_path, web, root = world
    settings = settings_for(tmp_path, web, tmp_path / "unused")
    out = tmp_path / "site"
    export_static(settings, out, takes_root=root, web_dir=web)
    (out / "leftover.txt").write_text("from the last export")
    export_static(settings, out, takes_root=root, web_dir=web)
    assert not (out / "leftover.txt").exists()

    precious = tmp_path / "precious"
    precious.mkdir()
    (precious / "notes.txt").write_text("keep me")
    with pytest.raises(StaticExportError, match="not empty"):
        export_static(settings, precious, takes_root=root, web_dir=web)
    assert (precious / "notes.txt").read_text() == "keep me"

    for overlapping in (web / "dist", root / "site", tmp_path):
        with pytest.raises(StaticExportError, match="overlaps"):
            export_static(settings, overlapping, takes_root=root, web_dir=web)


def test_missing_pieces_fail_with_a_plain_message(world):
    tmp_path, web, root = world
    settings = settings_for(tmp_path, web, tmp_path / "unused")
    with pytest.raises(StaticExportError, match="no recorded takes"):
        export_static(settings, tmp_path / "a", takes_root=tmp_path / "empty", web_dir=web)
    with pytest.raises(StaticExportError, match="index.html"):
        export_static(settings, tmp_path / "b", takes_root=root, web_dir=tmp_path / "no-web")


def test_the_cli_command_reports_a_missing_app_plainly(world, monkeypatch, capsys):
    tmp_path, _, root = world
    monkeypatch.setenv("OPENFIELD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    assert cli_main(["export-static", "--out", str(tmp_path / "cli-site"), "--takes", str(root)]) in {0, 1}
    # until the UI exists the packaged web folder has no index.html; once it does this must succeed
    out, err = capsys.readouterr()
    assert ("Wrote the hosted Replay" in out) or ("index.html" in err)
