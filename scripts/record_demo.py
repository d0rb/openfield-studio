#!/usr/bin/env python3
"""Record a scripted walk through the real interface as a silent MP4, plus a timed cue sheet for the voice-over.

    python scripts/record_demo.py --url http://127.0.0.1:8080/ --scenario scripts/ui/demo.scenario.json --out data-dev/demo

The scenario (see scripts/ui/record.mjs for the steps) says what to click, type and wait for, and where the narration
cues fall. A wait marked with a `speed` plays that many times faster with an "N x time-lapse" badge on screen, so a
two-minute render is cut honestly. Needs Node and a Chrome or Edge (OPENFIELD_BROWSER points at one).

The output is `demo.mp4` (1920x1080, 30 fps) and `cues.txt`. If the app on screen says it is the FAKE dev stack, the
file is named demo.FAKE.mp4 and the script says so loudly: that footage is a test pattern and must never be published.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIMIT_SECONDS = 120  # the contest's ceiling for the demo video


def clock(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True, help="the running app or hosted Replay to record")
    parser.add_argument("--scenario", default=str(ROOT / "scripts" / "ui" / "demo.scenario.json"))
    parser.add_argument("--out", default=str(ROOT / "data-dev" / "demo"), help="output folder")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--keep-frames", action="store_true", help="keep the captured JPEG frames")
    args = parser.parse_args(argv)

    node = shutil.which("node")
    if node is None:
        print("Node is needed to drive the browser (https://nodejs.org).", file=sys.stderr)
        return 1
    out = Path(args.out)
    captured = subprocess.run(
        [node, str(ROOT / "scripts" / "ui" / "record.mjs"), "--url", args.url, "--scenario", args.scenario,
         "--out", str(out), "--width", str(args.width), "--height", str(args.height)], cwd=ROOT)
    if captured.returncode != 0:
        print("Recording stopped; see the message above.", file=sys.stderr)
        return captured.returncode

    timeline = json.loads((out / "timeline.json").read_text(encoding="utf-8"))
    fake = "FAKE" in timeline.get("backend", "") or bool(timeline.get("fake_footage"))  # the page, or the receipts of the takes shown
    video = out / ("demo.FAKE.mp4" if fake else "demo.mp4")
    for stale in (out / "demo.mp4", out / "demo.FAKE.mp4"):
        stale.unlink(missing_ok=True)

    import imageio_ffmpeg  # a dependency of the app: the same ffmpeg that cuts takes

    encode = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(out / "concat.txt"), "-vf", f"fps={args.fps},format=yuv420p", "-c:v", "libx264", "-preset", "medium",
         "-crf", "18", "-movflags", "+faststart", str(video)], capture_output=True, text=True)
    if encode.returncode != 0:
        print(encode.stderr, file=sys.stderr)
        return 1
    if not args.keep_frames:
        shutil.rmtree(out / "frames", ignore_errors=True)

    cues = timeline.get("cues", [])
    sheet = [f"{timeline.get('title') or 'Demo'}: {clock(timeline['seconds'])} in total", ""]
    sheet += [f"{clock(c['video_s'])}  {c['text']}" for c in cues]
    if timeline.get("lapses"):
        sheet += ["", "Time-lapse cuts (marked on screen): " + ", ".join(f"{lap['speed']}x over {lap['real_s']} s" for lap in timeline["lapses"])]
    (out / "cues.txt").write_text("\n".join(sheet) + "\n", encoding="utf-8", newline="\n")

    print(f"\nWrote {video} ({clock(timeline['seconds'])}) and {out / 'cues.txt'}")
    if timeline["seconds"] > LIMIT_SECONDS:
        print(f"WARNING: {timeline['seconds']:.0f} s is over the {LIMIT_SECONDS} s limit; shorten the scenario or speed up the waits.")
    if fake:
        print("\nTHIS RECORDING SHOWS THE FAKE DEV STACK: a test pattern, not a render. Do not publish it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
