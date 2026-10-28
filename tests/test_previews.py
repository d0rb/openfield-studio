from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from openfield.config import Settings
from openfield.engine import video
from openfield.ledger import write_json
from openfield.previews import (
    PREVIEW_SECONDS,
    PREVIEW_WIDTH,
    PREVIEW_WIDTH_HD,
    PREVIEW_WIDTH_MID,
    THUMB_WIDTH,
    build_previews,
    check_previews,
)
from openfield.static_export import export_static


def _run_ffmpeg(*args: str) -> None:
    subprocess.run(
        [video.ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args],
        check=True,
    )


def _make_video(path: Path, size: str = "640x360") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=24:duration=4",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        str(path),
    )


def _make_take(
    root: Path,
    take_id: str,
    *,
    movement: str,
    created_at: str,
    effect: str | None = None,
    showcase_name: str | None = None,
    size: str = "640x360",
) -> Path:
    folder = root / take_id
    folder.mkdir(parents=True)
    recipe = {"subject": "A lighthouse", "rig": {"movement": movement}}
    if effect:
        recipe["rig"]["effect"] = effect
    take = {
        "id": take_id,
        "kind": "direct",
        "label": take_id[-4:],
        "status": "succeeded",
        "replay": False,
        "created_at": created_at,
        "recipe": recipe,
    }
    if showcase_name:
        take["showcase_name"] = showcase_name
    write_json(folder / "take.json", take)
    (folder / "receipt.json").write_text("{}", encoding="utf-8")
    _make_video(folder / "take.mp4", size)
    return folder


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        host="127.0.0.1", port=0, data_dir=tmp_path / "data", backend="replay",
        comfy_base_url=None, has_api_key=False, workflow_dir=tmp_path / "wf",
        showcase_dir=tmp_path / "showcase", web_dir=tmp_path / "web",
    )


@pytest.fixture
def world(tmp_path: Path):
    web = tmp_path / "web"
    showcase = web / "showcase"
    takes = showcase / "takes"
    previews = showcase / "previews"
    web.mkdir(parents=True, exist_ok=True)
    (web / "index.html").write_text("<!doctype html><title>OpenField</title>")

    sheet_dolly = "tk_20261016_120000_aaab"
    newer_dolly = "tk_20261016_130000_aaac"
    static_id = "tk_20261016_140000_aaad"
    rain_id = "tk_20261016_150000_aaae"

    _make_take(takes, sheet_dolly, movement="dolly_in",
               created_at="2026-10-16T12:00:00Z", showcase_name="sheet-dolly-in")
    _make_take(takes, newer_dolly, movement="dolly_in",
               created_at="2026-10-16T13:00:00Z")
    _make_take(takes, static_id, movement="static",
               created_at="2026-10-16T14:00:00Z")
    _make_take(takes, rain_id, movement="static", effect="rain",
               created_at="2026-10-16T15:00:00Z")

    index_path = showcase / "previews.json"
    return tmp_path, takes, previews, index_path, {
        "sheet_dolly": sheet_dolly,
        "newer_dolly": newer_dolly,
        "static": static_id,
        "rain": rain_id,
    }


def test_build_previews_cuts_loops_and_index(world):
    tmp_path, takes, previews, index_path, ids = world

    index = build_previews(takes)

    for take_id in ids.values():
        mp4 = previews / f"{take_id}.mp4"
        jpg = previews / f"{take_id}.jpg"
        assert mp4.is_file(), f"missing preview for {take_id}"
        assert jpg.is_file(), f"missing poster for {take_id}"
        info = video.probe(mp4)
        assert not info.has_audio
        assert info.width == PREVIEW_WIDTH == 384, "the plain copy stays small: the Takes wall's tiles load it"
        assert info.duration_s <= PREVIEW_SECONDS + 0.5

    assert index["version"] == 1
    assert index["seconds"] == PREVIEW_SECONDS
    assert index["moves"]["dolly_in"] == ids["sheet_dolly"]
    assert index["moves"]["static"] == ids["static"]
    assert index["effects"]["rain"] == ids["rain"]

    written = json.loads(index_path.read_text(encoding="utf-8"))
    assert written["takes"][ids["rain"]]["video"] == f"showcase/previews/{ids['rain']}.mp4"


def test_second_build_does_not_re_encode(world):
    _, takes, previews, index_path, ids = world
    first = build_previews(takes)
    mtimes = {
        f"{tid}{suffix}": (previews / f"{tid}{suffix}").stat().st_mtime
        for tid in ids.values()
        for suffix in (".mp4", ".jpg", "-mid.mp4", "-mid.jpg", "-hd.mp4", "-hd.jpg")
    }

    second = build_previews(takes)

    for name, before in mtimes.items():
        assert (previews / name).stat().st_mtime == before, f"{name} was cut again"
    assert second["takes"] == first["takes"], "what the index recorded (the widths too) is kept"
    for tid in ids.values():
        assert json.loads(index_path.read_text(encoding="utf-8"))["takes"][tid]["source_sha256"]


def test_check_previews_reports_stale_sources(world):
    _, takes, previews, index_path, ids = world
    build_previews(takes)
    assert check_previews(takes, previews, index_path) == []

    dolly_mp4 = takes / ids["newer_dolly"] / "take.mp4"
    original = dolly_mp4.read_bytes()
    dolly_mp4.write_bytes(original + b"\x00")

    problems = check_previews(takes, previews, index_path)
    assert any(ids["newer_dolly"] in p and "stale" in p for p in problems)

    dolly_mp4.write_bytes(original)


def test_export_static_ships_only_exported_previews(world):
    tmp_path, takes, previews, index_path, ids = world
    build_previews(takes)

    shutil.rmtree(takes / ids["rain"])

    out = tmp_path / "site"
    result = export_static(_settings(tmp_path), out, takes_root=takes, web_dir=tmp_path / "web")
    assert result["media_bytes"] > 0

    exported_ids = {ids["sheet_dolly"], ids["newer_dolly"], ids["static"]}
    for take_id in exported_ids:
        assert (out / "showcase" / "previews" / f"{take_id}.mp4").is_file()
        assert (out / "showcase" / "previews" / f"{take_id}.jpg").is_file()
    assert not (out / "showcase" / "previews" / f"{ids['rain']}.mp4").exists()

    shipped = json.loads((out / "showcase" / "previews.json").read_text(encoding="utf-8"))
    assert set(shipped["takes"]) == exported_ids
    assert "rain" not in shipped["effects"]
    assert shipped["moves"]["dolly_in"] == ids["sheet_dolly"]


def test_a_moves_tile_never_shows_an_angled_or_speaking_take(tmp_path):
    takes = tmp_path / "showcase" / "takes"
    plain = _make_take(takes, "tk_20261020_120000_aaaa", movement="static", created_at="2026-10-20T12:00:00Z")
    angled = _make_take(takes, "tk_20261022_120000_bbbb", movement="static", created_at="2026-10-22T12:00:00Z")
    take = json.loads((angled / "take.json").read_text(encoding="utf-8"))
    take["recipe"]["rig"]["angle"] = "back/eye/medium"
    write_json(angled / "take.json", take)
    speaking = _make_take(takes, "tk_20261022_130000_cccc", movement="static", created_at="2026-10-22T13:00:00Z")
    take = json.loads((speaking / "take.json").read_text(encoding="utf-8"))
    take["recipe"]["line"] = "Hello there."
    write_json(speaking / "take.json", take)
    index = build_previews(takes, tmp_path / "showcase" / "previews", tmp_path / "showcase" / "previews.json")
    assert index["moves"]["static"] == plain.name
    assert set(index["takes"]) == {plain.name, angled.name, speaking.name}  # every take still gets a preview


def test_a_measured_proof_take_wins_over_the_sheet_take(tmp_path, monkeypatch):
    """Oct 25: the Orbit 90 sheet take held the camera still while the subject turned; the pier take circled."""
    from openfield import previews
    takes = tmp_path / "showcase" / "takes"
    sheet = _make_take(takes, "tk_20261022_120000_aaaa", movement="orbit_90", created_at="2026-10-22T12:00:00Z",
                       showcase_name="sheet-orbit-90")
    pier = _make_take(takes, "tk_20261020_120000_bbbb", movement="orbit_90", created_at="2026-10-20T12:00:00Z",
                      showcase_name="oskar-pier-orbit")
    assert previews.PROOFS["orbit_90"] == "oskar-pier-orbit"
    index = build_previews(takes, tmp_path / "showcase" / "previews", tmp_path / "showcase" / "previews.json")
    assert index["moves"]["orbit_90"] == pier.name
    monkeypatch.setattr(previews, "PROOFS", {})
    index = build_previews(takes, tmp_path / "showcase" / "previews", tmp_path / "showcase" / "previews.json")
    assert index["moves"]["orbit_90"] == sheet.name, "without the table, the sheet take is the default"


def test_every_take_gets_a_sharper_copy_not_only_the_ones_a_gallery_shows(world):
    _, takes, previews, _, ids = world
    index = build_previews(takes)
    shown = set(index["moves"].values()) | set(index["effects"].values())
    assert ids["newer_dolly"] not in shown, "a take no gallery shows"
    for take_id in ids.values():
        hd = previews / f"{take_id}-hd.mp4"
        assert hd.is_file() and (previews / f"{take_id}-hd.jpg").is_file()
        info = video.probe(hd)
        assert not info.has_audio
        assert info.width == 640, "the take's own width (the fixtures are 640 px wide), neither shrunk nor scaled up"
        assert info.width > PREVIEW_WIDTH, "sharper than the plain copy"
        assert index["takes"][take_id]["hd"] == {"video": f"showcase/previews/{take_id}-hd.mp4", "poster": f"showcase/previews/{take_id}-hd.jpg",
                                                 "width": 640}, "the index says how wide the loop really is"


def test_every_take_gets_a_mid_size_copy_between_the_plain_and_the_sharper_one(world):
    _, takes, previews, _, ids = world
    index = build_previews(takes)
    assert PREVIEW_WIDTH_MID == 768 and PREVIEW_WIDTH < PREVIEW_WIDTH_MID < PREVIEW_WIDTH_HD
    for take_id in ids.values():
        mid = previews / f"{take_id}-mid.mp4"
        assert mid.is_file() and (previews / f"{take_id}-mid.jpg").is_file()
        info = video.probe(mid)
        assert not info.has_audio
        assert info.width == 640, "the take's own width (the fixtures are 640 px wide): a take narrower than 768 px is never scaled up"
        assert info.width > PREVIEW_WIDTH, "larger than the plain copy"
        assert index["takes"][take_id]["mid"] == {"video": f"showcase/previews/{take_id}-mid.mp4", "poster": f"showcase/previews/{take_id}-mid.jpg",
                                                  "width": 640}
    assert index["widths"] == {"hd": PREVIEW_WIDTH_HD, "mid": PREVIEW_WIDTH_MID, "thumb": THUMB_WIDTH} == {"hd": 1280, "mid": 768, "thumb": 768}


def test_a_larger_copy_is_never_wider_than_its_take_and_the_index_says_how_wide_it_is(tmp_path):
    """The sharper copy is cut at most 1280 px wide and the mid-size one at most 768, and a narrower take keeps its own width
    in both: nothing is scaled up. The index records the width each really has: the pictures module compares those numbers
    to pick a copy, so a take 896 or 848 px wide must not be claimed 1280."""
    from PIL import Image

    assert PREVIEW_WIDTH_HD == 1280
    takes, previews = tmp_path / "showcase" / "takes", tmp_path / "showcase" / "previews"
    made = {
        size: _make_take(takes, f"tk_20261022_1{n}0000_aaa{n}", movement="static", created_at=f"2026-10-22T1{n}:00:00Z", size=size).name
        for n, size in enumerate(["1600x900", "1280x704", "896x512", "848x480", "320x180"])
    }
    index = build_previews(takes, previews, tmp_path / "showcase" / "previews.json")
    for size, take_id in made.items():
        width, height = (int(n) for n in size.split("x"))
        for name, cap in (("hd", PREVIEW_WIDTH_HD), ("mid", PREVIEW_WIDTH_MID)):
            copy = video.probe(previews / f"{take_id}-{name}.mp4")
            assert copy.width <= width, f"{size}: the {name} copy is wider than its take"
            assert copy.width == min(cap, width), f"{size} {name}"
            assert abs(copy.height - copy.width * height / width) <= 1, f"{size} {name}: the shape is kept"
            with Image.open(previews / f"{take_id}-{name}.jpg") as poster:
                assert poster.width == copy.width, f"{size} {name}: the poster is as wide as the loop"
            assert index["takes"][take_id][name]["width"] == copy.width, f"{size} {name}: the index tells the truth"


def test_a_take_that_leaves_takes_its_sharper_copy_with_it(world):
    _, takes, previews, _, ids = world
    build_previews(takes)
    kept = (previews / f"{ids['static']}-hd.mp4").stat().st_mtime
    kept_mid = (previews / f"{ids['static']}-mid.mp4").stat().st_mtime
    shutil.rmtree(takes / ids["sheet_dolly"])  # the newer dolly becomes the move's take
    index = build_previews(takes)
    assert index["moves"]["dolly_in"] == ids["newer_dolly"]
    for suffix in (".mp4", ".jpg", "-mid.mp4", "-mid.jpg", "-hd.mp4", "-hd.jpg"):
        assert not (previews / f"{ids['sheet_dolly']}{suffix}").exists(), suffix
    assert ids["sheet_dolly"] not in index["takes"]
    assert (previews / f"{ids['newer_dolly']}-hd.mp4").is_file(), "it had its own before it became the move's take"
    assert (previews / f"{ids['newer_dolly']}-mid.mp4").is_file()
    assert (previews / f"{ids['static']}-hd.mp4").stat().st_mtime == kept, "a take that stayed is not cut again"
    assert (previews / f"{ids['static']}-mid.mp4").stat().st_mtime == kept_mid


def test_the_export_ships_the_sharper_copies_and_a_page_per_move(world):
    tmp_path, takes, _, _, ids = world
    build_previews(takes)
    out = tmp_path / "site"
    export_static(_settings(tmp_path), out, takes_root=takes, web_dir=tmp_path / "web", site_url="https://x.example/studio/")
    shipped = json.loads((out / "showcase" / "previews.json").read_text(encoding="utf-8"))
    for take_id in ids.values():  # every take's, not only the ones a gallery shows
        for suffix in ("-mid.mp4", "-mid.jpg", "-hd.mp4", "-hd.jpg"):
            assert (out / "showcase" / "previews" / f"{take_id}{suffix}").is_file(), suffix
        assert shipped["takes"][take_id]["hd"] == {"video": f"showcase/previews/{take_id}-hd.mp4", "poster": f"showcase/previews/{take_id}-hd.jpg", "width": 640}
        assert shipped["takes"][take_id]["mid"] == {"video": f"showcase/previews/{take_id}-mid.mp4", "poster": f"showcase/previews/{take_id}-mid.jpg", "width": 640}
    page = (out / "m" / "dolly_in.html").read_text(encoding="utf-8")
    assert f"https://x.example/studio/showcase/takes/{ids['sheet_dolly']}/take.mp4" in page, "it unfurls with the take that shows the move"
    assert '<link rel="canonical" href="https://x.example/studio/m/dolly_in.html">' in page
    assert "../#/lobby/dolly_in" in page and "Dolly in" in page
    assert (out / "m" / "static.html").is_file()
    assert not (out / "m" / "rain.html").exists(), "an effect is not a move"


def _make_still(path: Path, size: tuple[int, int] = (1344, 768)) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 120, 40)).save(path)


def test_every_still_gets_a_small_copy_cut_once(world):
    from PIL import Image

    _, takes, previews, _, ids = world
    folder = takes / ids["static"]
    _make_still(folder / "runs" / "01_hero" / "image.png")
    _make_still(folder / "inputs" / "hero.png", size=(300, 200))
    (folder / "runs" / "01_hero" / "preview.jpg").write_bytes(b"x")  # the sampler's progress frame is not a still
    index = build_previews(takes)
    small = f"showcase/previews/{ids['static']}"
    assert index["takes"][ids["static"]]["stills"] == {"inputs/hero.png": f"{small}-s1.jpg", "runs/01_hero/image.png": f"{small}-s2.jpg"}
    assert THUMB_WIDTH == 768
    with Image.open(previews / f"{ids['static']}-s2.jpg") as copy:
        assert copy.size == (768, 439)
    with Image.open(previews / f"{ids['static']}-s1.jpg") as copy:
        assert copy.size == (300, 200), "a smaller still keeps its size"
    assert "stills" not in index["takes"][ids["rain"]], "a take with no stills has no list"

    cut = (previews / f"{ids['static']}-s2.jpg").stat().st_mtime_ns
    build_previews(takes)
    assert (previews / f"{ids['static']}-s2.jpg").stat().st_mtime_ns == cut, "an unchanged take is not cut again"

    (folder / "inputs" / "hero.png").unlink()
    index = build_previews(takes)
    assert index["takes"][ids["static"]]["stills"] == {"runs/01_hero/image.png": f"{small}-s1.jpg"}
    assert not (previews / f"{ids['static']}-s2.jpg").exists(), "a copy nothing points at goes"


def test_check_previews_reports_a_missing_still_copy(world):
    _, takes, previews, index_path, ids = world
    _make_still(takes / ids["static"] / "runs" / "01_hero" / "image.png")
    build_previews(takes)
    assert check_previews(takes, previews, index_path) == []
    (previews / f"{ids['static']}-s1.jpg").unlink()
    assert any("still thumbnail" in p and ids["static"] in p for p in check_previews(takes, previews, index_path))


def test_the_export_ships_the_still_copies(world):
    tmp_path, takes, _, _, ids = world
    _make_still(takes / ids["static"] / "runs" / "01_hero" / "image.png")
    build_previews(takes)
    out = tmp_path / "site"
    export_static(_settings(tmp_path), out, takes_root=takes, web_dir=tmp_path / "web")
    assert (out / "showcase" / "previews" / f"{ids['static']}-s1.jpg").is_file()
    shipped = json.loads((out / "showcase" / "previews.json").read_text(encoding="utf-8"))
    # a small copy is keyed by the still it was cut from, and the hosted copy ships that still as WebP
    # (static_export.py), so the key follows it: the page looks the copy up by the name the take now gives it
    assert shipped["takes"][ids["static"]]["stills"] == {"runs/01_hero/image.webp": f"showcase/previews/{ids['static']}-s1.jpg"}


def test_the_export_ships_every_file_the_builder_cuts(world):
    """A copy the builder cuts but the export does not carry would be a 404 on the hosted site: the two lists must agree."""
    tmp_path, takes, previews, _, ids = world
    _make_still(takes / ids["static"] / "runs" / "01_hero" / "image.png")
    build_previews(takes)
    out = tmp_path / "site"
    export_static(_settings(tmp_path), out, takes_root=takes, web_dir=tmp_path / "web")
    assert {p.name for p in (out / "showcase" / "previews").iterdir()} == {p.name for p in previews.iterdir()}
    assert {p.name for p in previews.iterdir()} >= {f"{ids['static']}{suffix}" for suffix in (".mp4", ".jpg", "-mid.mp4", "-mid.jpg", "-hd.mp4", "-hd.jpg", "-s1.jpg")}


def test_a_still_changed_in_place_is_cut_again_and_a_jpg_still_counts(world):
    from PIL import Image

    _, takes, previews, index_path, ids = world
    folder = takes / ids["static"]
    _make_still(folder / "runs" / "01_hero" / "image.png")
    (folder / "runs" / "02_end").mkdir(parents=True)
    Image.new("RGB", (800, 450), (10, 10, 10)).save(folder / "runs" / "02_end" / "image.jpg")
    index = build_previews(takes)
    assert sorted(index["takes"][ids["static"]]["stills"]) == ["runs/01_hero/image.png", "runs/02_end/image.jpg"]
    _make_still(folder / "runs" / "01_hero" / "image.png", size=(1024, 576))  # the same path, a new picture
    assert any("stale" in p for p in check_previews(takes, previews, index_path)), "the check sees the still changed"
    build_previews(takes)
    with Image.open(previews / f"{ids['static']}-s1.jpg") as copy:
        assert copy.size == (768, 432), "the copy follows the new still even though the video did not change"
    assert check_previews(takes, previews, index_path) == []


def test_the_exported_index_leaves_out_the_builders_hashes(world):
    tmp_path, takes, _, _, ids = world
    _make_still(takes / ids["static"] / "runs" / "01_hero" / "image.png")
    build_previews(takes)
    out = tmp_path / "site"
    export_static(_settings(tmp_path), out, takes_root=takes, web_dir=tmp_path / "web")
    shipped = json.loads((out / "showcase" / "previews.json").read_text(encoding="utf-8"))
    entry = shipped["takes"][ids["static"]]
    assert "source_sha256" not in entry and "stills_sha" not in entry
    assert "widths" not in shipped, "the widths are the builder's record too"
    assert entry["stills"] and entry["poster"] and entry["video"] and entry["hd"]["video"] and entry["mid"]["video"]
    assert entry["hd"]["width"] == 640 and entry["mid"]["width"] == 640, "the copies keep the widths they have"


def test_copies_cut_at_an_older_width_are_cut_again_and_the_plain_loops_are_not(world):
    """An index written before the widths were recorded (sharper copies at 768 px, stills at 384) cannot vouch for those
    copies, so they are cut again. The plain loops did not change and are left alone."""
    _, takes, previews, index_path, ids = world
    _make_still(takes / ids["static"] / "runs" / "01_hero" / "image.png")
    build_previews(takes)
    written = json.loads(index_path.read_text(encoding="utf-8"))
    assert written["widths"] == {"hd": PREVIEW_WIDTH_HD, "mid": PREVIEW_WIDTH_MID, "thumb": THUMB_WIDTH}
    del written["widths"]  # the earlier builder wrote none
    index_path.write_text(json.dumps(written), encoding="utf-8")
    long_ago = time.time() - 3600
    for path in [*previews.glob("*.mp4"), *previews.glob("*.jpg")]:
        os.utime(path, (long_ago, long_ago))

    build_previews(takes)

    for take_id in ids.values():
        assert (previews / f"{take_id}.mp4").stat().st_mtime < long_ago + 60, "the plain loop did not change"
        assert (previews / f"{take_id}-hd.mp4").stat().st_mtime > long_ago + 60, "the sharper copy is cut again"
        assert (previews / f"{take_id}-mid.mp4").stat().st_mtime > long_ago + 60, "and the mid-size one"
    assert (previews / f"{ids['static']}-s1.jpg").stat().st_mtime > long_ago + 60, "and so is the still's copy"


def test_check_previews_wants_every_takes_sharper_copy_at_the_widths_cut_now(world):
    _, takes, previews, index_path, ids = world
    build_previews(takes)
    assert check_previews(takes, previews, index_path) == []
    (previews / f"{ids['newer_dolly']}-hd.jpg").unlink()
    assert any("sharper preview poster" in p and ids["newer_dolly"] in p for p in check_previews(takes, previews, index_path))
    build_previews(takes)
    assert check_previews(takes, previews, index_path) == []
    written = json.loads(index_path.read_text(encoding="utf-8"))
    written["widths"]["hd"] = 768  # what the builder cut before
    index_path.write_text(json.dumps(written), encoding="utf-8")
    assert any("another width" in p for p in check_previews(takes, previews, index_path))

    written["widths"]["hd"] = PREVIEW_WIDTH_HD
    written["widths"]["mid"] = 640  # the mid-size copies were cut at another width
    index_path.write_text(json.dumps(written), encoding="utf-8")
    problems = check_previews(takes, previews, index_path)
    assert any("mid-size copies" in p and "another width" in p for p in problems), problems
    assert not any("sharper copies" in p for p in problems), "only the copy that was cut at another width is named"


def test_a_take_whose_source_changed_gets_every_copy_cut_again_at_the_width_it_has_now(world):
    _, takes, previews, index_path, ids = world
    build_previews(takes)
    long_ago = time.time() - 3600
    for path in previews.iterdir():
        os.utime(path, (long_ago, long_ago))
    _make_video(takes / ids["static"] / "take.mp4", "704x396")  # a new render: 704 px wide, another file

    index = build_previews(takes)

    for suffix in (".mp4", "-mid.mp4", "-hd.mp4"):
        assert (previews / f"{ids['static']}{suffix}").stat().st_mtime > long_ago + 60, f"{suffix} was not cut again"
        assert (previews / f"{ids['rain']}{suffix}").stat().st_mtime < long_ago + 60, f"{suffix} of a take that did not change was"
    assert index["takes"][ids["static"]]["mid"]["width"] == 704 == index["takes"][ids["static"]]["hd"]["width"]
    assert index["takes"][ids["rain"]]["mid"]["width"] == 640
    assert check_previews(takes, previews, index_path) == []


def test_a_new_mid_width_cuts_the_mid_copies_again_and_nothing_else(world, monkeypatch):
    from openfield import previews as builder

    _, takes, previews, _, ids = world
    build_previews(takes)
    long_ago = time.time() - 3600
    for path in previews.iterdir():
        os.utime(path, (long_ago, long_ago))
    monkeypatch.setattr(builder, "PREVIEW_WIDTH_MID", 512)

    index = build_previews(takes)

    for take_id in ids.values():
        assert (previews / f"{take_id}-mid.mp4").stat().st_mtime > long_ago + 60
        assert video.probe(previews / f"{take_id}-mid.mp4").width == index["takes"][take_id]["mid"]["width"] == 512
        for suffix in (".mp4", "-hd.mp4"):
            assert (previews / f"{take_id}{suffix}").stat().st_mtime < long_ago + 60, f"{suffix} was cut again"
    assert index["widths"]["mid"] == 512


def test_check_previews_wants_every_takes_mid_size_copy_and_the_width_of_each_larger_copy(world):
    _, takes, previews, index_path, ids = world
    build_previews(takes)
    assert check_previews(takes, previews, index_path) == []

    (previews / f"{ids['static']}-mid.mp4").unlink()
    assert any("mid-size preview video" in p and ids["static"] in p for p in check_previews(takes, previews, index_path))
    (previews / f"{ids['rain']}-mid.jpg").unlink()
    assert any("mid-size preview poster" in p and ids["rain"] in p for p in check_previews(takes, previews, index_path))
    build_previews(takes)
    assert check_previews(takes, previews, index_path) == []

    written = json.loads(index_path.read_text(encoding="utf-8"))
    del written["takes"][ids["static"]]["mid"]["width"]
    written["takes"][ids["rain"]]["hd"]["width"] = 0
    index_path.write_text(json.dumps(written), encoding="utf-8")
    problems = check_previews(takes, previews, index_path)
    assert any("mid-size preview" in p and "records no width" in p and ids["static"] in p for p in problems), problems
    assert any("sharper preview" in p and "records no width" in p and ids["rain"] in p for p in problems), problems


def test_a_build_over_an_index_from_before_the_mid_copy_cuts_only_that_copy(world):
    """The showcase's index was written before the mid-size copy existed and before the sharper copies recorded their width.
    The next build cuts the mid-size copies and measures the sharper ones. The plain loops, the sharper copies and the stills'
    copies are not encoded again: their recorded widths hold."""
    _, takes, previews, index_path, ids = world
    _make_still(takes / ids["static"] / "runs" / "01_hero" / "image.png")
    build_previews(takes)
    written = json.loads(index_path.read_text(encoding="utf-8"))
    del written["widths"]["mid"]  # the index as the builder wrote it before
    for entry in written["takes"].values():
        del entry["mid"]
        del entry["hd"]["width"]
    index_path.write_text(json.dumps(written), encoding="utf-8")
    for take_id in ids.values():
        for suffix in ("-mid.mp4", "-mid.jpg"):
            (previews / f"{take_id}{suffix}").unlink()
    long_ago = time.time() - 3600
    for path in previews.iterdir():
        os.utime(path, (long_ago, long_ago))
    assert any("mid-size" in p for p in check_previews(takes, previews, index_path)), "the check asks for the build"

    index = build_previews(takes)

    for take_id in ids.values():
        for suffix in (".mp4", ".jpg", "-hd.mp4", "-hd.jpg"):
            assert (previews / f"{take_id}{suffix}").stat().st_mtime < long_ago + 60, f"{take_id}{suffix} was cut again"
        for suffix in ("-mid.mp4", "-mid.jpg"):
            assert (previews / f"{take_id}{suffix}").stat().st_mtime > long_ago + 60, f"{take_id}{suffix} was not cut"
        assert index["takes"][take_id]["hd"]["width"] == video.probe(previews / f"{take_id}-hd.mp4").width == 640, "measured, not cut again"
        assert index["takes"][take_id]["mid"]["width"] == 640
    assert (previews / f"{ids['static']}-s1.jpg").stat().st_mtime < long_ago + 60, "the still's copy is left alone too"
    assert check_previews(takes, previews, index_path) == []
