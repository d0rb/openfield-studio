"""The twelve-move social reel: built from fake takes, no GPU and no server."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
import pytest

from openfield.engine import video

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = SCRIPTS / "make_sheet_reel.py"


def load_script():
    spec = importlib.util.spec_from_file_location("make_sheet_reel", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_sheet_reel"] = module
    spec.loader.exec_module(module)
    return module


def fake_clip(path: Path) -> Path:
    """1 s of 64x36 testsrc with a silent AAC track, the shape of a finished take."""
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=64x36:rate=24:duration=1",
         "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-ar", "48000", "-shortest", str(path)],
        check=True)
    return path


def fake_world(root: Path, moves: list[str]) -> tuple[Path, Path]:
    takes, entries = root / "takes", []
    takes.mkdir()
    for index, move in enumerate(moves):
        take_id = f"tk_20260101_000000_{index:04x}"
        folder = takes / take_id
        folder.mkdir()
        fake_clip(folder / "take.mp4")
        (folder / "take.json").write_text(json.dumps({
            "id": take_id, "kind": "direct", "status": "succeeded",
            "recipe": {"rig": {"movement": move}},
        }), encoding="utf-8")
        (folder / "receipt.json").write_text(json.dumps({
            "integrity": {"sha256": hashlib.sha256(take_id.encode()).hexdigest()},
        }), encoding="utf-8")
        entries.append({"name": f"sheet-{move.replace('_', '-')}", "take_id": take_id})
    report = root / "report.json"
    report.write_text(json.dumps({"takes": entries}), encoding="utf-8")
    return takes, report


def test_the_script_cuts_the_16x9_and_9x16_reels_and_both_contact_sheets(tmp_path):
    module = load_script()
    moves = module.featured_move_ids()
    assert len(moves) == 12
    takes, report = fake_world(tmp_path, moves)
    out = tmp_path / "out"

    subprocess.run(
        [sys.executable, str(SCRIPT), "--takes", str(takes), "--report", str(report),
         "--out", str(out), "--seconds", "0.5", "--crossfade", "0.1"],
        check=True, capture_output=True, text=True)

    expected = 12 * 0.5 - 11 * 0.1  # a crossfade shortens each join
    reel = out / "reel-12-moves.mp4"
    vertical = out / "reel-12-moves-9x16.mp4"
    sheet = out / "contact-sheet-12-moves.png"
    sheet_2x = out / "contact-sheet-12-moves-2x.png"
    for path in (reel, vertical, sheet, sheet_2x,
                 out / "reel-12-moves.provenance.json",
                 out / "reel-12-moves-9x16.provenance.json"):
        assert path.is_file(), path.name

    assert video.probe(reel).duration_s == pytest.approx(expected, abs=0.3)
    assert video.probe(vertical).duration_s == pytest.approx(expected, abs=0.3)
    assert (video.probe(vertical).width, video.probe(vertical).height) == (720, 1280)

    width, height = module.contact_sheet_size(1)
    assert (video.probe(sheet).width, video.probe(sheet).height) == (width, height)
    width_2x, height_2x = module.contact_sheet_size(2)
    assert (video.probe(sheet_2x).width, video.probe(sheet_2x).height) == (width_2x, height_2x)
    assert width == 4 * 320 + 5 * 8

    provenance = json.loads((out / "reel-12-moves.provenance.json").read_text(encoding="utf-8"))
    assert [t["move"] for t in provenance["takes"]] == moves
    assert [t["take"] for t in provenance["takes"]] == [
        json.loads((takes / f"tk_20260101_000000_{i:04x}" / "take.json").read_text())["id"]
        for i in range(12)
    ]
    assert all(t["receipt_sha256"] and t["seconds"] for t in provenance["takes"])
    assert provenance["operation"]["concat"]["crossfade_s"] == 0.1


def test_a_missing_sheet_take_fails_with_a_message_that_names_it(tmp_path):
    module = load_script()
    takes, report = fake_world(tmp_path, module.featured_move_ids())
    data = json.loads(report.read_text(encoding="utf-8"))
    data["takes"] = [entry for entry in data["takes"] if entry["name"] != "sheet-dolly-in"]
    report.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(module.SheetError, match="sheet-dolly-in"):
        module.resolve_takes(takes, report)
