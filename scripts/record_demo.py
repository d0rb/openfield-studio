#!/usr/bin/env python3
"""Record a scripted walk through the real interface as a silent MP4, plus a timed cue sheet for the voice-over.

    python scripts/record_demo.py --url http://127.0.0.1:8080/ --scenario scripts/ui/demo.scenario.json --out data-dev/demo

The url is opened with `#/lobby` if it carries no room of its own: an address that names a room is a link someone was
sent, and the app greets a first visitor only when it has none, so the recording opens on the Lobby rather than on the
welcome card.

The scenario (see scripts/ui/record.mjs for the steps) says what to click, type and wait for, and where the narration
cues fall. A wait marked with a `speed` plays that many times faster with an "N x time-lapse" badge on screen, so a
two-minute render is cut honestly. Needs Node and a Chrome or Edge (OPENFIELD_BROWSER points at one).

The output is `demo.mp4` (1920x1080, 30 fps), `cues.txt` and `captions.txt`. If the app on screen says it is the FAKE dev
stack, the file is named demo.FAKE.mp4 and the script says so loudly: that footage is a test pattern and must never be
published.

`--try-url` and `--repo-url` fill the `{try_url}` and `{repo_url}` placeholders in a card, caption or say text. `--audio
VIDEO_S=PATH` (repeatable) lays each file's audio into the video from that second, with a 0.05 s fade in; without
it the video stays silent. For example `--audio 0=voice.wav --audio 12=music.wav`.

A `film` step marked `sound` lays its own sound (an LTX line, a whisper) in at its cue: a `film { take }` brings the take's
sound, looked up in `--takes-dir`, and a `film { src }` brings the clip's, read from `--clips DIR` (the folder a `film { src }`
step plays from). The sound starts at the second of the file the picture starts at and is cut to the film: its `ms` plus
0.25 s, with a 0.2 s fade out, so it never runs on into the next beat. A file with no audio track is reported and left silent.
A caption's `tag` is printed in `captions.txt` before the line: `0:14  LTX 2.5 | One take flies into the next`.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
LIMIT_SECONDS = 120  # the contest's ceiling for the demo video
SOUND_FADE_IN = 0.05  # seconds; every sound laid in comes in this softly
SOUND_FADE_OUT = 0.2  # a film's sound goes out this softly ...
SOUND_TAIL = 0.25  # ... and runs this long past the end of its film, fade included


class Sound(NamedTuple):
    start: float  # the second of the video it comes in at
    path: Path
    offset: float  # the second of the file it starts from
    keep: float | None  # how many seconds of it play (None: to the end of the file)


def clock(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


def audio_at(value: str) -> tuple[float, Path]:
    """One `--audio` value: the second it starts at in the video, then the file."""
    start, sep, path = value.partition("=")
    if not sep or not path:
        raise argparse.ArgumentTypeError("expected VIDEO_S=PATH, for example 0=voice.wav")
    try:
        return float(start), Path(path)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"the start is not a number of seconds: {start!r}") from error


def film_sounds(cues: list[dict], takes_dir: Path, clips_dir: Path | None) -> list[Sound]:
    """The sound each `film` cue marked `sound` lays in: a take's own (`sound`) or a clip's own (`clip_sound`), cut to the film."""
    sounds = []
    for cue in cues:
        if cue.get("sound"):
            path = takes_dir / cue["sound"] / "take.mp4"
        elif cue.get("clip_sound"):
            path = (clips_dir or Path()) / Path(cue["clip_sound"]).name  # a bare name, as the clip server reads it
        else:
            continue
        ms = cue.get("ms")  # a timeline written before the cue carried `ms` keeps the old cut: to the end of the file
        keep = None if ms is None else float(ms) / 1000 + SOUND_TAIL
        sounds.append(Sound(float(cue["video_s"]), path, float(cue.get("from") or 0), keep))
    return sounds


def has_audio(ffmpeg: str, path: Path) -> bool:
    """Whether the file has an audio track (ffmpeg lists its streams on stderr; there is no ffprobe in imageio-ffmpeg)."""
    listing = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    return "Audio:" in listing.stderr


def cut_sound(ffmpeg: str, sound: Sound, wav: Path) -> subprocess.CompletedProcess[str]:
    """One sound as a plain WAV: from its offset, at most `keep` seconds long, with a short fade in and, when it is cut,
    a fade out at its real end: the end of the film, or the end of the file if that comes first."""
    filters = f"afade=t=in:st=0:d={SOUND_FADE_IN}"
    length: list[str] = []
    if sound.keep is not None:
        # `-t` before `-i` limits what is read, so the filters see only the cut; the fade out is a fade in on the cut played
        # backwards, which lands on the cut's last samples whether or not the file ran as long as the film
        filters = f"areverse,afade=t=in:st=0:d={SOUND_FADE_OUT},areverse," + filters
        length = ["-t", f"{sound.keep:.3f}"]
    return subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{sound.offset:.3f}", *length, "-i", str(sound.path),
         "-vn", "-af", filters, "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(wav)],
        capture_output=True, text=True)


def caption_line(cue: dict) -> str:
    """A caption as `captions.txt` lists it: the time, then `TAG | line` when the caption has a tag."""
    tag = f"{cue['tag']} | " if cue.get("tag") else ""
    return f"{clock(cue['video_s'])}  {tag}{cue['caption']}"


def opening_url(url: str) -> str:
    """The address to record from. An address with no room of its own gets `#/lobby`: the app greets a first visitor
    only when nothing says where to go, and that card belongs in the product, not over the first frame of the demo."""
    return url if "#" in url else url.rstrip("/") + "/#/lobby"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True, help="the running app or hosted Replay to record")
    parser.add_argument("--scenario", default=str(ROOT / "scripts" / "ui" / "demo.scenario.json"))
    parser.add_argument("--out", default=str(ROOT / "data-dev" / "demo"), help="output folder")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--try-url", default="", help="fills {try_url} in card, caption and say text")
    parser.add_argument("--repo-url", default="", help="fills {repo_url} in card, caption and say text")
    parser.add_argument("--audio", type=audio_at, action="append", default=[], metavar="VIDEO_S=PATH",
                        help="lay this file's audio into the video from VIDEO_S seconds (repeatable)")
    parser.add_argument("--keep-frames", action="store_true", help="keep the captured JPEG frames")
    parser.add_argument("--clips", default=str(ROOT / "scripts" / "ui" / "clips"), help="the folder a film { src } step plays from (a live render, a canvas), "
                        "and where its own sound (film { src, sound: true }) is read")
    parser.add_argument("--takes-dir", default=str(ROOT / "openfield" / "web" / "showcase" / "takes"),
                        help="where a film step's take lives, for its own sound (film { sound: true })")
    args = parser.parse_args(argv)

    node = shutil.which("node")
    if node is None:
        print("Node is needed to drive the browser (https://nodejs.org).", file=sys.stderr)
        return 1
    out = Path(args.out)
    captured = subprocess.run(
        [node, str(ROOT / "scripts" / "ui" / "record.mjs"), "--url", args.url, "--scenario", args.scenario,
         "--out", str(out), "--width", str(args.width), "--height", str(args.height),
         "--try-url", args.try_url, "--repo-url", args.repo_url, "--clips", args.clips], cwd=ROOT)
    if captured.returncode != 0:
        print("Recording stopped; see the message above.", file=sys.stderr)
        return captured.returncode

    timeline = json.loads((out / "timeline.json").read_text(encoding="utf-8"))
    fake = "FAKE" in timeline.get("backend", "") or bool(timeline.get("fake_footage"))  # the page, or the receipts of the takes shown
    video = out / ("demo.FAKE.mp4" if fake else "demo.mp4")
    for stale in (out / "demo.mp4", out / "demo.FAKE.mp4"):
        stale.unlink(missing_ok=True)

    import imageio_ffmpeg  # a dependency of the app: the same ffmpeg that cuts takes

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    encode = subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(out / "concat.txt"), "-vf", f"fps={args.fps},format=yuv420p", "-c:v", "libx264", "-preset", "medium",
         "-crf", "18", "-movflags", "+faststart", str(video)], capture_output=True, text=True)
    if encode.returncode != 0:
        print(encode.stderr, file=sys.stderr)
        return 1

    # a film step marked `sound` brings its own sound in at its cue (a take's, or a clip's from --clips), from the second of
    # the file the picture starts at and for as long as the film runs
    sounds = film_sounds(timeline.get("cues", []), Path(args.takes_dir), Path(args.clips) if args.clips else None)
    missing = [str(sound.path) for sound in sounds if not sound.path.is_file()]
    if missing:
        print("No video for a film's sound: " + ", ".join(missing), file=sys.stderr)
        return 1
    heard = []
    for sound in sounds:
        if has_audio(ffmpeg, sound.path):
            heard.append(sound)
        else:  # a mistake in the scenario, not in the cut: the picture is fine, so say so and go on without that sound
            print(f"Warning: {sound.path.name} has no audio track, so its film at {clock(sound.start)} stays silent.", file=sys.stderr)
    tracks = [Sound(start, path, 0.0, None) for start, path in args.audio] + heard
    if tracks:
        # a second pass mixes the voice-over (or music) under the silent cut; the picture is copied, never re-encoded
        total = float(timeline["seconds"])
        inputs = []
        parts = []
        # each sound is cut to a plain WAV first, from its offset and to its length, with a short fade in and out on its own
        # timeline: a trim in the same graph as adelay + amix leaves ffmpeg 7.1 with an empty, backward-stamped track, and a
        # fade-out placed after adelay silenced every sound laid in after the first minute
        cuts = Path(tempfile.mkdtemp(prefix="sounds-", dir=out))
        for index, track in enumerate(tracks, start=1):
            wav = cuts / f"{index:02d}.wav"
            cut = cut_sound(ffmpeg, track, wav)
            if cut.returncode != 0:
                print(cut.stderr, file=sys.stderr)
                shutil.rmtree(cuts, ignore_errors=True)  # a failed cut leaves no WAVs in the output folder
                return 1
            delay = max(0, round(track.start * 1000))
            inputs += ["-i", str(wav)]
            parts.append(f"[{index}:a]adelay={delay}|{delay}[a{index}]")
        mixed = "".join(f"[a{index}]" for index in range(1, len(tracks) + 1))
        graph = ";".join(parts) + f";{mixed}amix=inputs={len(tracks)}:normalize=0,apad=whole_dur={total:.3f}[aout]"  # padded to the picture, so a short sound never cuts it
        temp = video.with_name(f"{video.stem}.mux.mp4")
        mux = subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video), *inputs,
             "-filter_complex", graph, "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac",
             "-ar", "48000", "-b:a", "160k", "-t", f"{total:.3f}", str(temp)], capture_output=True, text=True)
        shutil.rmtree(cuts, ignore_errors=True)
        if mux.returncode != 0:
            temp.unlink(missing_ok=True)
            print(mux.stderr, file=sys.stderr)
            return 1
        temp.replace(video)

    if not args.keep_frames:
        shutil.rmtree(out / "frames", ignore_errors=True)

    cues = timeline.get("cues", [])
    sheet = [f"{timeline.get('title') or 'Demo'}: {clock(timeline['seconds'])} in total", ""]
    sheet += [f"{clock(c['video_s'])}  {c['text']}" for c in cues if c.get("text")]
    if timeline.get("lapses"):
        sheet += ["", "Time-lapse cuts (marked on screen): " + ", ".join(f"{lap['speed']}x over {lap['real_s']} s" for lap in timeline["lapses"])]
    (out / "cues.txt").write_text("\n".join(sheet) + "\n", encoding="utf-8", newline="\n")

    captions = [caption_line(c) for c in cues if c.get("caption")]
    (out / "captions.txt").write_text(("\n".join(captions) + "\n") if captions else "", encoding="utf-8", newline="\n")

    print(f"\nWrote {video} ({clock(timeline['seconds'])}), {out / 'cues.txt'} and {out / 'captions.txt'}")
    if timeline["seconds"] > LIMIT_SECONDS:
        print(f"WARNING: {timeline['seconds']:.0f} s is over the {LIMIT_SECONDS} s limit; shorten the scenario or speed up the waits.")
    if fake:
        print("\nTHIS RECORDING SHOWS THE FAKE DEV STACK: a test pattern, not a render. Do not publish it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
