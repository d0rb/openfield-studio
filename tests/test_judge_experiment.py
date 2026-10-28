"""The blind judging sheet: layout, key, and the reveal rule, on two hand-made pairs."""
from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def load(name: str):
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def make_clip(path: Path, source: str) -> Path:
    """A one-second 640x360 H.264 clip, using the bundled ffmpeg like test_video.py."""
    from openfield.engine.video import ffmpeg_exe

    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", source,
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )
    return path


def write_take(run: Path, name: str, move: str, scores: list[float], *, source: str) -> None:
    folder = run / name
    make_clip(folder / "take.mp4", source)
    take = {
        "id": name,
        "kind": "direct",
        "status": "succeeded",
        "showcase_name": name,
        "recipe": {"kind": "direct", "rig": {"movement": move}},
        "identity": {
            f"stage_{index}": {"status": "pass", "score": score}
            for index, score in enumerate(scores)
        },
    }
    (folder / "take.json").write_text(json.dumps(take), encoding="utf-8", newline="\n")
    (folder / "receipt.json").write_text(
        json.dumps({"identity": {"reports": take["identity"]}}), encoding="utf-8", newline="\n"
    )


def test_sheet_is_blind_and_reveal_validates_only_the_winning_move(tmp_path, capsys):
    judge = load("judge_experiment")
    run = tmp_path / "run"
    run.mkdir()

    # dolly_in: the keyframed take also has the better identity score.
    write_take(
        run, "mara-dolly-in-keyframed", "dolly_in", [0.91, 0.82],
        source="testsrc2=size=640x360:rate=24:duration=1",
    )
    write_take(
        run, "mara-dolly-in-prompt", "dolly_in", [0.74],
        source="smptebars=size=640x360:rate=24:duration=1",
    )
    # orbit_90: both twins exist, but the keyframed identity is lower, so rule 3 fails.
    write_take(
        run, "oskar-orbit-90-keyframed", "orbit_90", [0.55],
        source="testsrc2=size=640x360:rate=24:duration=1",
    )
    write_take(
        run, "oskar-orbit-90-prompt", "orbit_90", [0.66],
        source="smptebars=size=640x360:rate=24:duration=1",
    )
    report = {
        "backend": "fake",
        "takes": [
            {"name": "mara-dolly-in-keyframed", "status": "succeeded"},
            {"name": "mara-dolly-in-prompt", "status": "succeeded"},
            {"name": "oskar-orbit-90-keyframed", "status": "succeeded"},
            {"name": "oskar-orbit-90-prompt", "status": "failed"},
        ],
        "summary": {"succeeded": 3, "failed": 1, "skipped": 0},
    }
    (run / "report.json").write_text(json.dumps(report), encoding="utf-8", newline="\n")

    out = tmp_path / "out"
    assert judge.main(["sheet", "--run", str(run), "--out", str(out), "--seed", "11"]) == 0
    printed = capsys.readouterr().out
    assert "Laid out 2 pair(s)" in printed

    with Image.open(out / "sheet.png") as sheet:
        frame_height = round(360 * judge.SHEET_FRAME_WIDTH / 640)
        expected = (
            2 * judge.SHEET_MARGIN
            + judge.SHEET_LEFT
            + 2 * judge.SHEET_FRAME_WIDTH
            + judge.SHEET_GAP,
            2 * judge.SHEET_MARGIN
            + 2 * (judge.SHEET_LABEL_HEIGHT + frame_height)
            + judge.SHEET_GAP,
        )
        assert sheet.size == expected

    key = json.loads((out / "key.json").read_text(encoding="utf-8"))
    assert key["seed"] == 11
    assert len(key["rows"]) == 2
    assert {row["pair"] for row in key["rows"]} == {"mara-dolly-in", "oskar-orbit-90"}
    assert {row["keyframed_side"] for row in key["rows"]} <= {"A", "B"}

    with (out / "verdicts.csv").open(encoding="utf-8", newline="") as handle:
        assert next(csv.reader(handle)) == list(judge.VERDICT_COLUMNS)

    sides = {row["pair"]: row["keyframed_side"] for row in key["rows"]}
    verdicts = tmp_path / "verdicts.csv"
    with verdicts.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(judge.VERDICT_COLUMNS)
        for pair in ("mara-dolly-in", "oskar-orbit-90"):
            for viewer in ("ana", "bo"):
                writer.writerow([pair, viewer, "yes", "yes", sides[pair]])

    assert judge.main(["reveal", "--out", str(out), "--verdicts", str(verdicts)]) == 0
    revealed = capsys.readouterr().out
    assert "dolly_in: validated (" in revealed
    assert "orbit_90: not validated (" in revealed
    assert 'VALIDATED = frozenset({"dolly_in"})' in revealed
