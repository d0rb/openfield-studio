from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from openfield.cli import main as cli_main
from openfield.config import Settings
from openfield.engine import receipt as receipts
from openfield.ledger import write_json
from openfield.static_export import (
    MANIFEST,
    MEDIA_BASE,
    StaticExportError,
    export_static,
    recorded_takes,
    slim_identity,
)

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
    (web / "index.html").write_text(
        '<!doctype html><html><head><meta name="description" content="A test studio">'
        "<title>OpenField</title></head><body></body></html>")
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
    assert status["hero_take"] is None  # nothing named a hero
    assert status["hero_reel"] == []
    assert len(manifest["moves"]["moves"]) == 49
    assert [t["id"] for t in manifest["takes"]] == [NEWER, GOOD]
    assert all(t["media_base"] == f"showcase/takes/{t['id']}" for t in manifest["takes"])
    assert manifest["takes"][1]["recipe"]["subject"] == "A lighthouse"
    # the shelf is the ids of the recorded takes, newest first: the page joins their fields from `takes`, so nothing is sent twice
    assert manifest["recorded"] == [NEWER, GOOD]

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


REPORT = {"status": "pass", "score": 0.81, "threshold": 0.363, "best_ref": 0, "per_ref": [0.81], "faces_in_candidate": 1,
          "candidate_box": [486, 142, 155, 206], "refs_used": 1, "reason": "cosine 0.810 >= threshold 0.363 (best reference 0)",
          "face_px": 155, "enlarged": None, "frame": "first", "frames_checked": 3}


def test_the_manifest_lists_a_takes_face_check_by_the_keys_the_page_reads_and_the_take_folder_keeps_it_whole(world):
    tmp_path, web, root = world
    take = json.loads((root / GOOD / "take.json").read_text(encoding="utf-8"))
    take["identity"] = {"hero": dict(REPORT), "shoot_1": dict(REPORT, status="drift", score=0.2, retried=True), "face": {"status": "n/a"}}
    write_json(root / GOOD / "take.json", take)
    out = tmp_path / "site"
    export_static(settings_for(tmp_path, web, tmp_path / "unused"), out, takes_root=root, web_dir=web)

    listed = {t["id"]: t for t in json.loads((out / MANIFEST).read_text(encoding="utf-8"))["takes"]}
    assert listed[GOOD]["identity"] == {
        "hero": {"status": "pass", "score": 0.81, "threshold": 0.363},
        "shoot_1": {"status": "drift", "score": 0.2, "threshold": 0.363, "retried": True},
        "face": {"status": "n/a"},
    }
    assert "identity" not in listed[NEWER], "a take that has none lists none"
    kept = json.loads((out / "showcase" / "takes" / GOOD / "take.json").read_text(encoding="utf-8"))
    assert kept["identity"]["hero"] == REPORT, "the take's own folder keeps the whole report"
    assert slim_identity(None) is None and slim_identity({}) == {} and slim_identity({"hero": None}) == {"hero": None}


def test_the_page_joins_the_shelf_with_the_fields_the_server_lists(tmp_path):
    """The server lists a recorded take with some fields (`ReplayBackend.recorded`); the hosted page builds the same entry from the
    take (`shelfEntry` in lib/api-static.js). Python and JavaScript were written apart: the two lists must name the same fields."""
    from openfield.backends.replay import ReplayBackend

    root = tmp_path / "recorded"
    folder = record(root, GOOD, created="2026-10-16T12:00:00Z")
    take = json.loads((folder / "take.json").read_text(encoding="utf-8"))
    take.update(identity={"hero": {"status": "pass"}}, audit={"result": "pass"}, notes=["a note"], seconds=5.0,
                shots=[{"index": 1}], board=["a"], edit={"before": "x"})
    write_json(folder / "take.json", take)
    listed = ReplayBackend([root]).recorded({root: MEDIA_BASE})[0]

    page = (Path(__file__).resolve().parents[1] / "openfield" / "web" / "js" / "lib" / "api-static.js").read_text(encoding="utf-8")
    named = {name: re.findall(r'"([a-z_]+)"', re.search(rf"const {name} = \[([^\]]*)\]", page).group(1)) for name in ("SHELF_BASE", "SHELF_EXTRA")}
    assert set(listed) == set(named["SHELF_BASE"]) | set(named["SHELF_EXTRA"]) | {"created_at", "media_base"}


def test_with_a_site_url_the_export_unfurls_with_absolute_tags_and_take_pages(world):
    tmp_path, web, root = world
    poster = root / GOOD / "poster.png"
    Image.new("RGB", (1600, 900), (30, 60, 90)).save(poster)
    take = json.loads((root / GOOD / "take.json").read_text(encoding="utf-8"))
    take["size"] = [1280, 720]
    write_json(root / GOOD / "take.json", take)
    out = tmp_path / "site"
    export_static(settings_for(tmp_path, web, tmp_path / "unused"), out, takes_root=root, web_dir=web,
                  site_url="https://example.com/studio///", repo_url="https://github.com/example/studio")

    index = (out / "index.html").read_text(encoding="utf-8")
    assert 'property="og:image" content="https://example.com/studio/static/card.jpg"' in index
    assert 'name="twitter:card" content="summary_large_image"' in index
    assert 'rel="canonical" href="https://example.com/studio/"' in index
    assert (out / "static" / "card.jpg").is_file()

    page = (out / "t" / f"{GOOD}.html").read_text(encoding="utf-8")
    assert f'property="og:video" content="https://example.com/studio/showcase/takes/{GOOD}/take.mp4"' in page
    assert f'property="og:video:secure_url" content="https://example.com/studio/showcase/takes/{GOOD}/take.mp4"' in page
    assert 'property="og:video:width" content="1280"' in page
    assert 'http-equiv="refresh" content="0; url=../#/takes/' + GOOD + '"' in page
    assert f'location.replace("../#/takes/{GOOD}")' in page
    assert f'<a href="../#/takes/{GOOD}">Open the take</a>' in page

    site = json.loads((out / "static" / "site.json").read_text(encoding="utf-8"))
    assert site == {"site_url": "https://example.com/studio/",
                    "repo_url": "https://github.com/example/studio"}
    with Image.open(out / "t" / f"{GOOD}.jpg") as card:
        assert card.size == (1200, 630)


def test_without_a_site_url_there_are_no_open_graph_tags_and_site_json_is_null(world):
    tmp_path, web, root = world
    out = tmp_path / "site"
    export_static(settings_for(tmp_path, web, tmp_path / "unused"), out, takes_root=root, web_dir=web)
    assert "og:" not in (out / "index.html").read_text(encoding="utf-8")
    site = json.loads((out / "static" / "site.json").read_text(encoding="utf-8"))
    assert site == {"site_url": None, "repo_url": None}
    page = (out / "t" / f"{GOOD}.html").read_text(encoding="utf-8")
    assert f'http-equiv="refresh" content="0; url=../#/takes/{GOOD}"' in page
    assert "og:" not in page
    with Image.open(out / "static" / "card.jpg") as card:
        assert card.size == (1200, 630)


def test_a_subject_with_quotes_and_angle_brackets_is_escaped(world):
    tmp_path, web, root = world
    take = json.loads((root / GOOD / "take.json").read_text(encoding="utf-8"))
    take["recipe"]["subject"] = 'A "quoted" <lighthouse>'
    write_json(root / GOOD / "take.json", take)
    out = tmp_path / "site"
    export_static(settings_for(tmp_path, web, tmp_path / "unused"), out, takes_root=root, web_dir=web,
                  site_url="https://example.com/studio/")
    page = (out / "t" / f"{GOOD}.html").read_text(encoding="utf-8")
    assert "&quot;quoted&quot; &lt;lighthouse&gt;" in page
    assert '<lighthouse>' not in page and '"quoted"' not in page


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


def test_bundled_cast_members_ship_with_their_portraits(world):
    tmp_path, web, root = world
    cast_root = tmp_path / "cast"
    member = cast_root / "ca_0123abcd"
    (member / "refs").mkdir(parents=True)
    write_json(member / "cast.json", {
        "id": "ca_0123abcd", "name": "Mara", "kind": "character", "consent": "fictional",
        "created_at": "2026-10-20T14:23:26Z", "refs": [{"file": "ref_1.png", "faces": 1}]})
    (member / "refs" / "ref_1.png").write_bytes(b"portrait")
    (member / "refs" / "scratch.tmp").write_bytes(b"not listed, not shipped")
    (cast_root / "notes.txt").write_text("ignored")

    out = tmp_path / "site"
    result = export_static(settings_for(tmp_path, web, tmp_path / "unused"), out, takes_root=root, web_dir=web,
                           cast_root=cast_root)
    assert result["cast"] == 1
    manifest = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    assert [c["id"] for c in manifest["cast"]] == ["ca_0123abcd"]
    assert manifest["cast"][0]["refs"][0]["file"] == "ref_1.png" and manifest["cast"][0]["bundled"] is True
    assert (out / "showcase" / "cast" / "ca_0123abcd" / "ref_1.png").read_bytes() == b"portrait"
    assert not (out / "showcase" / "cast" / "ca_0123abcd" / "scratch.tmp").exists()


def test_a_cast_portrait_wider_than_768_px_ships_with_a_smaller_copy_the_manifest_names(world):
    tmp_path, web, root = world
    cast_root = tmp_path / "cast"
    member = cast_root / "ca_0123abcd"
    (member / "refs").mkdir(parents=True)
    write_json(member / "cast.json", {
        "id": "ca_0123abcd", "name": "Mara", "kind": "character", "consent": "fictional", "created_at": "2026-10-20T14:23:26Z",
        "refs": [{"file": "ref_1.png", "size": [1024, 1024], "faces": 1}, {"file": "ref_2.png", "size": [600, 600], "faces": 1},
                 {"file": "ref_3.png", "faces": 0}]})
    Image.new("RGB", (1024, 1024), (200, 120, 40)).save(member / "refs" / "ref_1.png")
    Image.new("RGB", (600, 600), (40, 120, 200)).save(member / "refs" / "ref_2.png")
    (member / "refs" / "ref_3.png").write_bytes(b"not a picture")

    out = tmp_path / "site"
    result = export_static(settings_for(tmp_path, web, tmp_path / "unused"), out, takes_root=root, web_dir=web, cast_root=cast_root)
    folder = out / "showcase" / "cast" / "ca_0123abcd"
    with Image.open(folder / "ref_1-768.jpg") as small:
        assert small.size == (768, 768) and small.format == "JPEG"
    assert (folder / "ref_1.png").is_file(), "the original is still there for the sharpest screens"
    assert not (folder / "ref_2-768.jpg").exists(), "a portrait no wider than the copy needs none"
    assert not (folder / "ref_3-768.jpg").exists(), "a file that is not a picture is shipped as it is, and nothing breaks"
    refs = json.loads((out / MANIFEST).read_text(encoding="utf-8"))["cast"][0]["refs"]
    assert refs[0]["small"] == {"file": "ref_1-768.jpg", "width": 768}
    assert "small" not in refs[1] and "small" not in refs[2]
    assert result["media_bytes"] >= (folder / "ref_1-768.jpg").stat().st_size + (folder / "ref_1.png").stat().st_size


def test_the_hosted_copy_drops_the_identity_check_frames(tmp_path):
    from openfield.static_export import served_files
    take = tmp_path / "tk_20260101_000000_abcd"
    (take / "runs" / "02_shoot_1").mkdir(parents=True)
    for name in ("take.mp4", "receipt.json", "poster.png"):
        (take / name).write_bytes(b"x")
    for name in ("preview.jpg", "identity_frame.png", "identity_frame_first.png", "identity_frame_last.png"):
        (take / "runs" / "02_shoot_1" / name).write_bytes(b"x")
    served = {p.as_posix() for p in served_files(take)}
    assert "runs/02_shoot_1/preview.jpg" in served and "poster.png" in served
    assert not any("identity_frame" in p for p in served)


def test_the_hosted_zip_lists_its_inputs_instead_of_packing_them():
    import io
    import zipfile

    from openfield import share
    candidates = [p for p in sorted((Path(__file__).resolve().parents[1] / "openfield" / "web" / "showcase" / "takes").glob("tk_*"))
                  if (p / "runs").is_dir()]
    if not candidates:
        pytest.skip("the bundled showcase takes are not in this copy")
    take = candidates[0]
    full = zipfile.ZipFile(io.BytesIO(share.workflows_zip(take)))
    slim = zipfile.ZipFile(io.BytesIO(share.workflows_zip(take, include_inputs=False)))
    assert any(n.startswith("inputs/") for n in full.namelist()), "the live zip packs the inputs"
    assert not any(n.startswith("inputs/") for n in slim.namelist()), "the hosted zip packs graphs only"
    assert [n for n in slim.namelist() if n.endswith(".api.json")] == [n for n in full.namelist() if n.endswith(".api.json")]
    assert "is served beside this zip at runs/" in slim.read("README.txt").decode("utf-8")



def test_the_hosted_zip_works_from_a_relative_takes_folder(monkeypatch):
    """`openfield export-static --takes openfield/web/showcase/takes` passed a relative folder, and the zip's notes
    (resolved paths) could not be made relative to it."""
    import io
    import zipfile

    from openfield import share
    root = Path(__file__).resolve().parents[1]
    candidates = [p for p in sorted((root / "openfield" / "web" / "showcase" / "takes").glob("tk_*")) if (p / "runs").is_dir()]
    if not candidates:
        pytest.skip("the bundled showcase takes are not in this copy")
    monkeypatch.chdir(root)
    relative = candidates[0].relative_to(root)
    slim = zipfile.ZipFile(io.BytesIO(share.workflows_zip(relative, include_inputs=False)))
    assert "is served beside this zip at runs/" in slim.read("README.txt").decode("utf-8")


def test_the_manifest_sums_the_gpu_time_the_receipts_list(world):
    from openfield.backends.replay import recorded_gpu
    tmp_path, web, root = world
    for take_id, seconds in ((GOOD, 120.5), (NEWER, 60)):
        path = root / take_id / "receipt.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["backend"] = {"kind": "pod", "timings": {"total_s": seconds}}
        write_json(path, receipts.seal(raw))
    out = tmp_path / "site"
    export_static(settings_for(tmp_path, web, tmp_path / "unused"), out, takes_root=root, web_dir=web)
    status = json.loads((out / MANIFEST).read_text(encoding="utf-8"))["status"]
    assert status["gpu"] == {"takes": 2, "seconds": 180.5}
    assert recorded_gpu([root / "tk_20261016_160000_eeee", root / "missing"]) is None, "no receipt, no time"


def test_the_showcase_gpu_total_is_read_again_only_when_the_takes_change(tmp_path):
    import os

    from openfield.backends import replay
    takes = tmp_path / "showcase" / "takes"
    (takes / GOOD).mkdir(parents=True)
    write_json(takes / GOOD / "receipt.json", {"backend": {"timings": {"total_s": 100}}})
    (takes / "notes").mkdir()  # not a take
    assert replay.showcase_gpu(tmp_path / "showcase") == {"takes": 1, "seconds": 100.0}
    write_json(takes / GOOD / "receipt.json", {"backend": {"timings": {"total_s": 999}}})
    assert replay.showcase_gpu(tmp_path / "showcase")["seconds"] == 100.0, "the folder did not change: the total stands"
    (takes / NEWER).mkdir()
    write_json(takes / NEWER / "receipt.json", {"backend": {"timings": {"total_s": 50}}})
    later = takes.stat().st_mtime_ns + 1_000_000_000
    os.utime(takes, ns=(later, later))  # a coarse clock must not hide the new take
    assert replay.showcase_gpu(tmp_path / "showcase") == {"takes": 2, "seconds": 1049.0}
    assert replay.showcase_gpu(tmp_path / "nowhere") is None


def test_the_stills_ship_as_webp_while_the_receipt_and_the_shot_stay_byte_for_byte(world):
    """A take's stills are photographs kept as PNG and cost about twenty times their weight, so the hosted copy
    ships them as WebP. What a receipt stands behind must not move with them: receipt.json is never rewritten,
    take.mp4 is the file it hashes, and inputs/ holds the person's own photo exactly as they gave it.
    """
    tmp_path, web, root = world
    folder = root / GOOD
    # the fixture writes stand-in bytes, which cannot be opened as pictures; these are real ones, so the export converts
    Image.new("RGB", (64, 48), (180, 90, 20)).save(folder / "poster.png")
    Image.new("RGB", (64, 48), (20, 90, 180)).save(folder / "runs" / "01_hero" / "image.png")
    Image.new("RGB", (32, 32), (10, 10, 10)).save(folder / "inputs" / "reference.png")
    # a recorded take names its poster among its outputs, the way the pipeline writes it; the fixture keeps only the video
    take_record = json.loads((folder / "take.json").read_text(encoding="utf-8"))
    take_record["outputs"].append({"role": "poster", "file": "poster.png", "kind": "image",
                                   "content_type": "image/png"})
    write_json(folder / "take.json", take_record)
    before = {name: (folder / name).read_bytes() for name in ("receipt.json", "take.mp4")}
    kept = (folder / "inputs" / "reference.png").read_bytes()

    out = tmp_path / "site"
    export_static(settings_for(tmp_path, web, tmp_path / "unused"), out, takes_root=root, web_dir=web)
    shipped = out / MEDIA_BASE.format(id=GOOD)

    assert (shipped / "poster.webp").is_file(), "the poster ships as WebP"
    assert not (shipped / "poster.png").exists(), "and the PNG is not shipped beside it"
    assert (shipped / "runs" / "01_hero" / "image.webp").is_file()
    assert not (shipped / "runs" / "01_hero" / "image.png").exists()

    # what the site reads names the copies, so nothing asks for a file that is no longer there
    take = json.loads((shipped / "take.json").read_text(encoding="utf-8"))
    poster = next(o for o in take["outputs"] if o["role"] == "poster")
    assert poster["file"] == "poster.webp"
    assert poster.get("content_type") in (None, "image/webp")
    view = json.loads((shipped / "receipt.view.json").read_text(encoding="utf-8"))
    for anchor in view.get("inputs", {}).get("anchors", []):
        assert (shipped / anchor["file"]).is_file(), anchor["file"]

    # the evidence is untouched
    for name, raw in before.items():
        assert (shipped / name).read_bytes() == raw, f"{name} must survive the export byte for byte"
    assert (shipped / "inputs" / "reference.png").read_bytes() == kept, "the person's own photo is left as given"


def test_the_password_gate_carries_only_a_hash_and_is_absent_without_one(world):
    """`--password` puts a latch on the front door: the page asks before it shows. The word itself never ships, only
    the SHA-256 the answer is checked against, and the gate moves out of <body> because the app mounts there.
    """
    import hashlib

    tmp_path, web, root = world
    plain = tmp_path / "plain"
    export_static(settings_for(tmp_path, web, tmp_path / "unused"), plain, takes_root=root, web_dir=web)
    assert 'id="gate"' not in (plain / "index.html").read_text(encoding="utf-8"), "no password, no gate"

    locked = tmp_path / "locked"
    export_static(settings_for(tmp_path, web, tmp_path / "unused"), locked, takes_root=root, web_dir=web,
                  password="a velvet rope")
    page = (locked / "index.html").read_text(encoding="utf-8")
    assert 'id="gate"' in page
    assert "a velvet rope" not in page, "the password itself must never ship"
    assert hashlib.sha256("a velvet rope".encode("utf-8")).hexdigest() in page
    assert "documentElement.appendChild(gate)" in page, "the app replaces the body's children, so the gate leaves it"
