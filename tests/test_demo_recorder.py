"""The demo recorder: a scripted walk through the real interface becomes a timed MP4 and a cue sheet.

Needs Node and a Chrome or Edge, like tests/test_ui_smoke.py; skips cleanly without them.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import wave
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import pytest

from openfield.engine import video

from .ui_support import NODE, ROOT, browser, export_site, fake_stack, make_quick_take, serve_static


def load_recorder():
    """scripts/record_demo.py as a module, to test its sound and caption helpers without a browser."""
    spec = importlib.util.spec_from_file_location("record_demo", ROOT / "scripts" / "record_demo.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["record_demo"] = module
    spec.loader.exec_module(module)
    return module


def make_tone(path: Path, seconds: int = 6, with_video: bool = True) -> Path:
    """A steady 440 Hz tone, as an H.264 + AAC clip to play as a `film { src }` (or as a bare WAV, or a silent clip)."""
    sound = ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    picture = ["-f", "lavfi", "-i", f"testsrc=size=320x180:rate=30:duration={seconds}"]
    if path.suffix == ".wav":
        command = [*sound, str(path)]
    elif with_video:
        command = [*picture, *sound, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)]
    else:  # a clip with no audio track at all, like a screen capture
        command = [*picture, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    made = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", *command],
                          capture_output=True, text=True, timeout=60)
    assert made.returncode == 0, made.stderr
    return path


def loud_span(media: Path, floor_db: float = -45.0) -> tuple[float, float]:
    """The first and the last second the audio of `media` is louder than `floor_db` (RMS over 20 ms windows)."""
    raw = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(media), "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], capture_output=True, timeout=60).stdout
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768
    window = 320  # 20 ms at 16 kHz
    count = len(samples) // window
    rms = np.sqrt((samples[: count * window].reshape(count, window) ** 2).mean(axis=1))
    loud = np.flatnonzero(rms > 10 ** (floor_db / 20))
    return (float(loud[0]) * 0.02, float(loud[-1] + 1) * 0.02) if len(loud) else (0.0, 0.0)


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


@pytest.mark.skipif(NODE is None, reason="Node is not installed")
def test_captions_a_card_and_audio_are_written_into_the_recording(tmp_path: Path):
    if not browser():
        pytest.skip("no Chrome or Edge found (set OPENFIELD_BROWSER)")
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps({"title": "Captions test", "steps": [
        {"do": "goto", "route": "direct"},
        {"do": "say", "text": "First cue", "caption": "A caption on the first beat"},
        {"do": "hold", "ms": 500},
        {"do": "card", "title": "OpenField Studio", "lines": ["A stage for AI video", "{try_url}", "{repo_url}"],
         "mono": "{repo_url}", "ms": 500},
        {"do": "caption", "text": None},
        {"do": "say", "text": "Second cue"},
        {"do": "hold", "ms": 500},
    ]}), encoding="utf-8")
    tone = tmp_path / "tone.wav"
    made = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
                           "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(tone)],
                          capture_output=True, text=True, timeout=60)
    assert made.returncode == 0, made.stderr
    data, site, out = tmp_path / "data", tmp_path / "site", tmp_path / "demo"
    with fake_stack(data) as live:
        make_quick_take(live)
        export_site(data, site)
    with serve_static(site) as url:
        done = subprocess.run([sys.executable, "scripts/record_demo.py", "--url", f"{url}/", "--scenario", str(scenario),
                               "--out", str(out), "--width", "960", "--height", "540",
                               "--try-url", "https://try.example/", "--repo-url", "https://repo.example/",
                               "--audio", f"0={tone}"],
                              cwd=ROOT, capture_output=True, text=True, timeout=240)
    assert done.returncode == 0, done.stdout + done.stderr
    video_file = out / "demo.FAKE.mp4"
    assert video_file.is_file()
    timeline = json.loads((out / "timeline.json").read_text(encoding="utf-8"))
    assert timeline["cues"][0]["text"] == "First cue"
    assert timeline["cues"][0]["caption"] == "A caption on the first beat"
    assert timeline["cues"][1]["text"] is None and timeline["cues"][1]["caption"] is None
    assert timeline["cues"][2]["text"] == "Second cue" and timeline["cues"][2]["caption"] is None
    captions = (out / "captions.txt").read_text(encoding="utf-8")
    assert captions.startswith("0:") and "A caption on the first beat" in captions
    sheet = (out / "cues.txt").read_text(encoding="utf-8")
    assert "First cue" in sheet and "Second cue" in sheet
    # the silent cut was copied and a mixed AAC track added by the second ffmpeg pass
    info = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(video_file)],
                          capture_output=True, text=True, timeout=60)
    assert "Audio:" in info.stderr, info.stderr
    probed = video.probe(video_file)
    assert (probed.width, probed.height) == (960, 540)


def test_a_captions_tag_is_listed_and_a_films_sound_is_cut_to_the_film_and_fades_out(tmp_path: Path):
    recorder = load_recorder()
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    # captions.txt: the tag first, then the line; no tag, no bar
    tagged = {"video_s": 14.2, "caption": "One take flies into the next", "tag": "LTX 2.5"}
    assert recorder.caption_line(tagged) == "0:14  LTX 2.5 | One take flies into the next"
    assert recorder.caption_line({"video_s": 75.0, "caption": "No tag here", "tag": None}) == "1:15  No tag here"
    assert recorder.caption_line({"video_s": 3, "caption": "From an older timeline"}) == "0:03  From an older timeline"
    # which films carry sound, from where, and for how long: `ms` plus the 0.25 s tail (None: the whole rest of the file)
    cues = [
        {"video_s": 3.0, "film": "tk_a", "from": 0.5, "ms": 3000, "sound": "tk_a", "clip_sound": None},
        {"video_s": 7.5, "film": "clip.mp4", "from": 0, "ms": 2000, "sound": None, "clip_sound": "clip.mp4"},
        {"video_s": 9.0, "film": "mute.mp4", "from": 0, "ms": 2000, "sound": None, "clip_sound": None},
        {"video_s": 11.0, "film": "tk_old", "from": 1.5, "sound": "tk_old"},  # a timeline from before the cues carried `ms`
        {"video_s": 12.0, "text": "a cue that is not a film", "caption": None},
    ]
    sounds = recorder.film_sounds(cues, Path("takes"), Path("clips"))
    assert [(s.start, s.path, s.offset, s.keep) for s in sounds] == [
        (3.0, Path("takes/tk_a/take.mp4"), 0.5, 3.25),
        (7.5, Path("clips/clip.mp4"), 0.0, 2.25),
        (11.0, Path("takes/tk_old/take.mp4"), 1.5, None)]

    tone = make_tone(tmp_path / "tone.wav", seconds=5)

    def cut(sound, name):
        wav_file = tmp_path / name
        done = recorder.cut_sound(ffmpeg, sound, wav_file)
        assert done.returncode == 0, done.stderr
        with wave.open(str(wav_file)) as wav:
            rate = wav.getframerate()
            pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).astype(np.float64) / 32768
        return pcm, rate

    # a film of 1.5 s from second 1 of the file: 1.75 s of sound, in softly, out softly
    pcm, rate = cut(recorder.Sound(0.0, tone, 1.0, 1.5 + recorder.SOUND_TAIL), "film.wav")
    assert abs(len(pcm) / 2 / rate - 1.75) < 0.03, len(pcm) / 2 / rate  # two channels

    def level(a: float, b: float) -> float:
        return float(np.sqrt((pcm[int(a * rate * 2):int(b * rate * 2)] ** 2).mean()))

    steady = level(0.4, 1.0)
    assert steady > 0.05, steady
    assert level(0.0, 0.01) < steady / 4, "fades in"
    assert level(1.73, 1.75) < steady / 5, "fades out over the last 0.2 s"
    # a file that ends before its film does still ends softly, at its own end
    pcm, rate = cut(recorder.Sound(0.0, make_tone(tmp_path / "short.wav", seconds=2), 1.0, 1.75), "short.wav.cut.wav")
    assert abs(len(pcm) / 2 / rate - 1.0) < 0.03, len(pcm) / 2 / rate
    assert level(0.97, 1.0) < level(0.3, 0.7) / 5, "fades out at the end of the file"
    # no length: the old cut, to the end of the file (what `--audio` tracks still get)
    pcm, rate = cut(recorder.Sound(0.0, tone, 1.0, None), "rest.wav")
    assert abs(len(pcm) / 2 / rate - 4.0) < 0.03, len(pcm) / 2 / rate

    # a file with no audio track is told apart, so its film can stay silent instead of stopping the cut
    assert recorder.has_audio(ffmpeg, make_tone(tmp_path / "with-sound.mp4", seconds=1))
    assert not recorder.has_audio(ffmpeg, make_tone(tmp_path / "no-sound.mp4", seconds=1, with_video=False))


@pytest.mark.skipif(NODE is None, reason="Node is not installed")
def test_tags_and_a_clips_own_sound_are_written_into_the_recording_and_cut_to_the_film(tmp_path: Path):
    if not browser():
        pytest.skip("no Chrome or Edge found (set OPENFIELD_BROWSER)")
    clips = tmp_path / "clips"
    clips.mkdir()
    make_tone(clips / "tone.mp4")
    make_tone(clips / "mute.mp4", seconds=2, with_video=False)
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps({"title": "Tags test", "steps": [
        {"do": "goto", "route": "direct"},
        {"do": "say", "text": "First cue", "caption": "A tagged line", "tag": "LTX 2.5"},
        {"do": "hold", "ms": 500},
        {"do": "caption", "text": "A second line", "tag": "COMFY-SDK"},
        {"do": "hold", "ms": 500},
        {"do": "film", "src": "tone.mp4", "from": 1, "ms": 1500, "sound": True,
         "caption": "Over the clip", "captionTag": "QWEN-IMAGE 2.1 + LTX 2.5"},
        {"do": "film", "src": "mute.mp4", "ms": 800, "sound": True, "caption": None},  # no audio track: reported, left silent
        {"do": "caption", "text": None, "tag": "LTX 2.5"},  # no text clears the tag with it
        {"do": "hold", "ms": 1500},
    ]}), encoding="utf-8")
    data, site, out = tmp_path / "data", tmp_path / "site", tmp_path / "demo"
    with fake_stack(data) as live:
        make_quick_take(live)
        export_site(data, site)
    with serve_static(site) as url:
        done = subprocess.run([sys.executable, "scripts/record_demo.py", "--url", f"{url}/", "--scenario", str(scenario),
                               "--out", str(out), "--width", "960", "--height", "540", "--clips", str(clips)],
                              cwd=ROOT, capture_output=True, text=True, timeout=240)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "mute.mp4 has no audio track" in done.stderr, done.stderr

    # the tag is in captions.txt before the line, and in the cue
    captions = (out / "captions.txt").read_text(encoding="utf-8").splitlines()
    assert [re.sub(r"^\d+:\d\d  ", "", line) for line in captions] == [
        "LTX 2.5 | A tagged line", "COMFY-SDK | A second line", "QWEN-IMAGE 2.1 + LTX 2.5 | Over the clip"]
    timeline = json.loads((out / "timeline.json").read_text(encoding="utf-8"))
    cues = timeline["cues"]
    assert [c["tag"] for c in cues if c["caption"]] == ["LTX 2.5", "COMFY-SDK", "QWEN-IMAGE 2.1 + LTX 2.5"]
    assert cues[-1]["caption"] is None and cues[-1]["tag"] is None
    assert all(c["tag"] is None for c in cues if not c["caption"])
    # a film's cue says how long it runs and whose sound goes with it
    film = next(c for c in cues if c.get("film") == "tone.mp4")
    assert (film["from"], film["ms"], film["clip_sound"], film["sound"]) == (1, 1500, "tone.mp4", None)
    assert next(c for c in cues if c.get("film") == "mute.mp4")["ms"] == 800

    # the tone comes in with its film and is cut at the film's end plus the 0.25 s tail; left alone it would play for the
    # 5 s the clip has left, on to the end of the cut
    start, end = loud_span(out / "demo.FAKE.mp4")
    assert film["video_s"] - 0.1 <= start <= film["video_s"] + 0.2, (start, film["video_s"])
    assert film["video_s"] + 1.45 <= end <= film["video_s"] + 1.95, (end, film["video_s"])
    assert timeline["seconds"] - end > 2.0, (end, timeline["seconds"])
