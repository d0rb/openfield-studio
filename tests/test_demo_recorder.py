"""The demo recorder: a scripted walk through the real interface becomes a timed MP4 and a cue sheet.

Needs Node and a Chrome or Edge, like tests/test_ui_smoke.py; skips cleanly without them.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from openfield.engine import video

from .ui_support import NODE, ROOT, browser, export_site, fake_stack, make_quick_take, serve_static


@pytest.mark.skipif(NODE is None, reason="Node is not installed")
def test_a_scripted_walk_becomes_a_timed_video_and_cue_sheet_and_fake_footage_is_flagged(tmp_path: Path):
    if not browser():
        pytest.skip("no Chrome or Edge found (set OPENFIELD_BROWSER)")
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps({"title": "Recorder test", "steps": [
        {"do": "goto", "route": "direct"},
        {"do": "say", "text": "First cue"},
        {"do": "hold", "ms": 700},
        {"do": "click", "selector": ".move-tile", "text": "Orbit 180"},
        {"do": "say", "text": "Second cue"},
        {"do": "until", "expr": "document.querySelector('.move-info')", "speed": 4, "label": "a wait"},
        {"do": "hold", "ms": 600},
    ]}), encoding="utf-8")
    data, site, out = tmp_path / "data", tmp_path / "site", tmp_path / "demo"
    with fake_stack(data) as live:
        make_quick_take(live)
        export_site(data, site)
    with serve_static(site) as url:
        done = subprocess.run([sys.executable, "scripts/record_demo.py", "--url", f"{url}/", "--scenario", str(scenario),
                               "--out", str(out), "--width", "960", "--height", "540"],
                              cwd=ROOT, capture_output=True, text=True, timeout=240)
    assert done.returncode == 0, done.stdout + done.stderr
    # the takes came from the offline fake: the file says so and the script says so, so it cannot be mistaken for a render
    assert (out / "demo.FAKE.mp4").is_file() and not (out / "demo.mp4").exists()
    assert "Do not publish" in done.stdout
    info = video.probe(out / "demo.FAKE.mp4")
    assert (info.width, info.height) == (960, 540)
    assert 1.5 < info.duration_s < 20
    timeline = json.loads((out / "timeline.json").read_text(encoding="utf-8"))
    assert timeline["fake_footage"] is True and [c["text"] for c in timeline["cues"]] == ["First cue", "Second cue"]
    assert timeline["cues"][0]["video_s"] < timeline["cues"][1]["video_s"] <= timeline["seconds"]
    sheet = (out / "cues.txt").read_text(encoding="utf-8")
    assert "First cue" in sheet and "Second cue" in sheet and "Recorder test" in sheet
    assert not (out / "frames").exists(), "the frames are cleared once the video is made"
