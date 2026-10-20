from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import pytest
from PIL import Image

from openfield.engine import video

REAL_FFPROBE = video.ffprobe_exe
MIB = 1024 * 1024
AWKWARD_VALUE = 'He said "hi" \\ back\\\\slash trailing\\ a=b;c#d café 日本語 🎬\nline2\r\nline3'


@pytest.fixture(autouse=True)
def bundled_ffmpeg_without_ffprobe(monkeypatch):
    """Run against the weakest supported toolchain: imageio's ffmpeg and no ffprobe."""
    monkeypatch.setenv("OPENFIELD_FFMPEG", imageio_ffmpeg.get_ffmpeg_exe())
    monkeypatch.setattr(video, "ffprobe_exe", lambda: None)


@pytest.fixture(params=["ffmpeg banner", "ffprobe"])
def probe_tool(request, monkeypatch):
    if request.param == "ffprobe":
        if REAL_FFPROBE() is None:
            pytest.skip("ffprobe is not installed")
        monkeypatch.setattr(video, "ffprobe_exe", REAL_FFPROBE)
    return request.param


def run_ffmpeg(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        [video.ffmpeg_exe(), "-hide_banner", "-y", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return proc


def generate(
    path: Path,
    *sources: str,
    audio: bool = True,
    pix_fmt: str = "yuv420p",
    graph: str | None = None,
) -> Path:
    args = ["-loglevel", "error"]
    for source in sources:
        args += ["-f", "lavfi", "-i", source]
    if graph:
        args += ["-filter_complex", graph]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", pix_fmt]
    args += ["-c:a", "aac"] if audio else []
    run_ffmpeg(*args, str(path))
    return path


def pattern(size: str = "640x360", rate: int | str = 24, seconds: float = 2) -> str:
    return f"testsrc2=size={size}:rate={rate}:duration={seconds}"


def sine(seconds: float = 2) -> str:
    return f"sine=frequency=440:duration={seconds}"


def stream_stat(path: Path, stream: str) -> tuple[int | None, float]:
    """Packet count and duration of one stream, read from ffmpeg's own copy-to-null report."""
    proc = run_ffmpeg("-i", str(path), "-map", f"0:{stream}:0", "-c", "copy", "-f", "null", "-")
    frames = re.findall(r"frame=\s*(\d+)", proc.stderr)
    hours, minutes, seconds = re.findall(r"time=(\d+):(\d+):(\d+\.\d+)", proc.stderr)[-1]
    elapsed = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return (int(frames[-1]) if frames else None), elapsed


def measure_lufs(path: Path) -> float:
    report = run_ffmpeg("-nostats", "-i", str(path), "-vn", "-af", "ebur128", "-f", "null", "-")
    summary = report.stderr.split("Integrated loudness:")[-1]
    return float(re.search(r"I:\s+(-?\d+(?:\.\d+)?) LUFS", summary)[1])


def audio_rate(path: Path) -> int:
    banner = run_ffmpeg("-i", str(path), check=False).stderr
    return int(re.search(r"Audio: .*?, (\d+) Hz", banner)[1])


def transcode(src: Path, out: Path) -> None:
    run_ffmpeg("-loglevel", "error", "-i", str(src), "-c:v", "libx264", "-c:a", "aac", str(out))


def max_volume_db(path: Path, start: float, length: float) -> float:
    proc = run_ffmpeg(
        *("-ss", str(start), "-t", str(length), "-i", str(path)),
        *("-vn", "-af", "volumedetect", "-f", "null", "-"),
    )
    return float(re.search(r"max_volume: (-?\d+(?:\.\d+)?) dB", proc.stderr)[1])


def pixels(png: Path) -> np.ndarray:
    with Image.open(png) as image:
        return np.asarray(image.convert("RGB"), dtype=float)


def gray_at(png: Path, xy: tuple[int, int] = (10, 10)) -> int:
    with Image.open(png) as image:
        return image.convert("L").getpixel(xy)


def is_red(pixel) -> bool:
    return pixel[0] > 200 and pixel[2] < 80


def is_blue(pixel) -> bool:
    return pixel[2] > 200 and pixel[0] < 80


def assert_faststart(path: Path) -> None:
    head = path.read_bytes()
    assert 0 <= head.find(b"moov") < head.find(b"mdat")


@pytest.fixture(scope="module")
def media_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("media dir")


@pytest.fixture(scope="module")
def av_clip(media_dir) -> Path:
    return generate(media_dir / "av clip.mp4", pattern(), sine())


@pytest.fixture(scope="module")
def silent_clip(media_dir) -> Path:
    return generate(media_dir / "silent.mp4", pattern(), audio=False)


@pytest.fixture(scope="module")
def big_clip(media_dir) -> Path:
    return generate(media_dir / "big.mp4", pattern("1280x720", 24, 3), sine(3))


@pytest.fixture(scope="module")
def ramp_clip(media_dir) -> Path:
    """64x48 clip whose luma climbs from black to white, one step per frame (48 frames)."""
    ramp = "color=black:s=64x48:r=24:d=2,format=yuv420p,geq=lum='16+219*N/48':cb=128:cr=128"
    return generate(media_dir / "ramp.mp4", ramp, audio=False)


@pytest.fixture(scope="module")
def halves_clip(media_dir) -> Path:
    """640x360 clip, left half red and right half blue."""
    return generate(
        media_dir / "halves.mp4",
        "color=c=red:s=320x360:r=24:d=1",
        "color=c=blue:s=320x360:r=24:d=1",
        graph="[0][1]hstack",
        audio=False,
    )


def test_ffmpeg_exe_resolution_order(monkeypatch):
    monkeypatch.setenv("OPENFIELD_FFMPEG", "custom-ffmpeg")
    assert video.ffmpeg_exe() == "custom-ffmpeg"
    monkeypatch.delenv("OPENFIELD_FFMPEG")
    monkeypatch.setattr(video.shutil, "which", lambda name: f"/opt/bin/{name}")
    assert video.ffmpeg_exe() == "/opt/bin/ffmpeg"
    monkeypatch.setattr(video.shutil, "which", lambda name: None)
    assert video.ffmpeg_exe() == imageio_ffmpeg.get_ffmpeg_exe()


def test_ffprobe_exe_resolution_order(monkeypatch):
    monkeypatch.setattr(video, "ffprobe_exe", REAL_FFPROBE)
    monkeypatch.setenv("OPENFIELD_FFPROBE", "custom-ffprobe")
    assert video.ffprobe_exe() == "custom-ffprobe"
    monkeypatch.delenv("OPENFIELD_FFPROBE")
    monkeypatch.setattr(video.shutil, "which", lambda name: f"/opt/bin/{name}")
    assert video.ffprobe_exe() == "/opt/bin/ffprobe"
    monkeypatch.setattr(video.shutil, "which", lambda name: None)
    assert video.ffprobe_exe() is None


def test_probe_reports_stream_facts(av_clip, probe_tool):
    info = video.probe(av_clip)
    assert info.duration_s == pytest.approx(2.0, abs=0.05)
    assert info.fps == pytest.approx(24.0, abs=0.01)
    assert (info.width, info.height) == (640, 360)
    assert info.has_audio is True
    assert info.video_codec == "h264"
    assert info.size_bytes == av_clip.stat().st_size


def test_probe_silent_clip_has_no_audio(silent_clip, probe_tool):
    info = video.probe(silent_clip)
    assert info.has_audio is False
    assert (info.width, info.height, info.video_codec) == (640, 360, "h264")


def test_probe_audio_only_file(tmp_path, probe_tool):
    wav = tmp_path / "tone.wav"
    run_ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", sine(1), str(wav))
    info = video.probe(wav)
    assert (info.width, info.height, info.fps, info.video_codec) == (0, 0, 0.0, None)
    assert info.has_audio is True
    assert info.duration_s == pytest.approx(1.0, abs=0.05)


@pytest.fixture
def phone_clip(av_clip, tmp_path) -> Path:
    """The 640x360 clip tagged with a 90 degree display matrix, like portrait phone footage."""
    out = tmp_path / "phone.mp4"
    args = ("-loglevel", "error", "-display_rotation", "90", "-i", str(av_clip), "-c", "copy")
    if run_ffmpeg(*args, str(out), check=False).returncode != 0:
        pytest.skip("this ffmpeg cannot write a display matrix (-display_rotation needs 6.0+)")
    return out


def test_probe_reports_the_display_size_of_rotated_footage(phone_clip, probe_tool):
    info = video.probe(phone_clip)
    assert (info.width, info.height) == (360, 640)


def test_rotated_footage_comes_out_upright(phone_clip, tmp_path):
    prepared = video.prepare_source(phone_clip, tmp_path / "upright.mp4", max_height=480)
    assert (prepared.width, prepared.height) == (270, 480)
    with Image.open(video.extract_frame(phone_clip, tmp_path / "first.png", "first")) as image:
        assert image.size == (360, 640)
    assert video.probe(video.crop_9x16(phone_clip, tmp_path / "crop.mp4")).width == 1080


def test_concat_refuses_clips_with_a_rotation_flag(phone_clip, av_clip, tmp_path):
    for clips in ([phone_clip, av_clip], [av_clip, phone_clip]):
        with pytest.raises(video.VideoError, match="rotation flag"):
            video.concat(clips, tmp_path / "joined.mp4", lufs=None)
    upright = video.prepare_source(phone_clip, tmp_path / "upright.mp4")
    assert (upright.width, upright.height) == (360, 640)
    joined = video.concat([tmp_path / "upright.mp4", av_clip], tmp_path / "ok.mp4", lufs=None)
    assert (joined.width, joined.height) == (360, 640)


def test_probe_handles_fractional_frame_rates(tmp_path, probe_tool):
    clip = generate(tmp_path / "ntsc.mp4", pattern(rate="30000/1001", seconds=1), audio=False)
    assert video.probe(clip).fps == pytest.approx(29.97, abs=0.01)


def test_probe_rejects_missing_and_garbage_files(tmp_path, probe_tool):
    with pytest.raises(video.VideoError, match="not a file"):
        video.probe(tmp_path / "missing.mp4")
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"this is not a video" * 50)
    with pytest.raises(video.VideoError):
        video.probe(junk)


def test_extract_frame_first_mid_and_last(ramp_clip, tmp_path):
    grays = {}
    for at in ("first", "mid", "last"):
        png = video.extract_frame(ramp_clip, tmp_path / f"{at}.png", at)
        with Image.open(png) as image:
            assert (image.format, image.size) == ("PNG", (64, 48))
        grays[at] = gray_at(png)
    assert grays["first"] <= 8
    assert 115 <= grays["mid"] <= 140
    assert grays["last"] >= 246  # frame 47 of 48; one frame earlier would read about 244


def test_extract_frame_defaults_to_mid_and_accepts_seconds(ramp_clip, tmp_path):
    default = video.extract_frame(ramp_clip, tmp_path / "default.png")
    assert 115 <= gray_at(default) <= 140
    quarter = video.extract_frame(ramp_clip, tmp_path / "quarter.png", 0.5)
    assert 55 <= gray_at(quarter) <= 80


@pytest.mark.parametrize("at", ["first", "mid", "last", 0.75])
def test_extract_frame_keeps_the_video_size(av_clip, tmp_path, at):
    png = video.extract_frame(av_clip, tmp_path / "nested" / f"{at}.png", at)
    with Image.open(png) as image:
        assert (image.format, image.size) == ("PNG", (640, 360))


def test_extract_frame_last_of_clip_shorter_than_the_seek_window(tmp_path):
    short = generate(tmp_path / "short.mp4", pattern(seconds=0.25), audio=False)
    png = video.extract_frame(short, tmp_path / "short.png", "last")
    assert png.stat().st_size > 0


def test_extract_frame_rejects_bad_positions(ramp_clip, tmp_path):
    for bad in ("middle", -1):
        with pytest.raises(ValueError, match="at must be"):
            video.extract_frame(ramp_clip, tmp_path / "x.png", bad)


def test_extract_frame_past_the_end_fails_without_leftovers(ramp_clip, tmp_path):
    out = tmp_path / "late.png"
    out.write_bytes(b"previous")
    with pytest.raises(video.VideoError, match="no output"):
        video.extract_frame(ramp_clip, out, 99)
    assert out.read_bytes() == b"previous"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["late.png"]


def test_prepare_source_trims_scales_and_keeps_audio(big_clip, tmp_path):
    out = tmp_path / "prepared.mp4"
    info = video.prepare_source(big_clip, out, max_seconds=1.5, max_height=360)
    assert out.is_file()
    assert (info.width, info.height) == (640, 360)
    assert info.duration_s == pytest.approx(1.5, abs=0.1)
    assert (info.video_codec, info.has_audio) == ("h264", True)
    assert_faststart(out)


def test_prepare_source_never_upscales(av_clip, tmp_path):
    info = video.prepare_source(av_clip, tmp_path / "same.mp4", max_height=1080)
    assert (info.width, info.height) == (640, 360)


def test_prepare_source_has_no_audio_when_the_source_has_none(silent_clip, tmp_path):
    info = video.prepare_source(silent_clip, tmp_path / "quiet.mp4")
    assert info.has_audio is False


def test_prepare_source_forces_even_dimensions(tmp_path):
    odd = generate(
        tmp_path / "odd.mp4",
        "testsrc2=size=853x479:rate=24:duration=1,format=yuv444p",
        audio=False,
        pix_fmt="yuv444p",
    )
    assert (video.probe(odd).width, video.probe(odd).height) == (853, 479)
    info = video.prepare_source(odd, tmp_path / "even.mp4")
    assert info.width % 2 == 0 and info.height % 2 == 0
    assert info.height == 478


def test_prepare_source_drops_source_metadata(av_clip, tmp_path):
    private = {"title": "Holiday", "comment": "shot on my phone", "location": "+51.5-000.1/"}
    tagged = video.embed_metadata(av_clip, tmp_path / "tagged.mp4", private)
    assert set(private) <= set(video.read_metadata(tagged))
    plain = tmp_path / "plain.mp4"
    transcode(tagged, plain)
    assert set(private) <= set(video.read_metadata(plain))  # a bare transcode keeps them
    prepared = tmp_path / "prepared.mp4"
    video.prepare_source(tagged, prepared)
    assert not set(private) & set(video.read_metadata(prepared))


def test_prepare_source_shrinks_to_fit_the_size_limit(big_clip, tmp_path):
    base = video.prepare_source(big_clip, tmp_path / "base.mp4")
    limit_mb = base.size_bytes * 0.4 / MIB
    fitted = video.prepare_source(big_clip, tmp_path / "fitted.mp4", max_mb=limit_mb)
    assert fitted.size_bytes <= limit_mb * MIB
    assert fitted.size_bytes < base.size_bytes
    assert (fitted.video_codec, fitted.has_audio) == ("h264", True)
    assert fitted.duration_s == pytest.approx(base.duration_s, abs=0.1)


def test_prepare_source_rejects_limits_that_cannot_hold_the_audio(av_clip, tmp_path):
    out = tmp_path / "tiny.mp4"
    with pytest.raises(video.VideoError, match="too small"):
        video.prepare_source(av_clip, out, max_mb=0.01)
    assert not out.exists()


def test_prepare_source_cleans_up_when_no_attempt_fits(av_clip, tmp_path, monkeypatch):
    monkeypatch.setattr(video, "_rate_plan", lambda budget: [["-crf", "20"]])
    work = tmp_path / "work"
    with pytest.raises(video.VideoError, match="could not fit"):
        video.prepare_source(av_clip, work / "out.mp4", max_mb=0.06)
    assert list(work.iterdir()) == []


def test_concat_joins_clips_back_to_back(av_clip, tmp_path):
    out = tmp_path / "joined.mp4"
    info = video.concat([av_clip, av_clip], out, lufs=None)
    assert info.duration_s == pytest.approx(4.0, abs=0.1)
    assert (info.width, info.height, info.fps) == (640, 360, 24.0)
    assert (info.video_codec, info.has_audio) == ("h264", True)
    assert audio_rate(out) == 48000
    assert_faststart(out)
    assert stream_stat(out, "v")[0] == 96
    assert stream_stat(out, "a")[1] == pytest.approx(4.0, abs=0.1)


def test_concat_crossfade_overlaps_clips(av_clip, tmp_path):
    out = tmp_path / "faded.mp4"
    info = video.concat([av_clip, av_clip, av_clip], out, crossfade_s=0.5, lufs=None)
    assert info.duration_s == pytest.approx(5.0, abs=0.1)
    assert stream_stat(out, "v")[0] == 120
    assert stream_stat(out, "a")[1] == pytest.approx(5.0, abs=0.1)


def test_concat_crossfade_really_blends_the_two_clips(av_clip, tmp_path):
    out = tmp_path / "blend.mp4"
    video.concat([av_clip, av_clip], out, crossfade_s=1.0, lufs=None)
    # the fade runs from 1.0 s to 2.0 s, so at 1.5 s it is an even mix of A@1.5 and B@0.5
    mixed = pixels(video.extract_frame(out, tmp_path / "mixed.png", 1.5))
    from_a = pixels(video.extract_frame(av_clip, tmp_path / "a.png", 1.5))
    from_b = pixels(video.extract_frame(av_clip, tmp_path / "b.png", 0.5))
    error_blend = np.abs(mixed - (from_a + from_b) / 2).mean()
    assert error_blend < 0.5 * np.abs(mixed - from_a).mean()
    assert error_blend < 0.5 * np.abs(mixed - from_b).mean()


def test_concat_keeps_silent_clips_in_sync(av_clip, silent_clip, tmp_path):
    out = tmp_path / "mixed.mp4"
    info = video.concat([silent_clip, av_clip, silent_clip], out, lufs=None)
    assert info.has_audio is True
    assert stream_stat(out, "v")[0] == 144
    assert stream_stat(out, "a")[1] == pytest.approx(6.0, abs=0.1)
    assert max_volume_db(out, 0.2, 1.6) < -60  # silent clip
    assert max_volume_db(out, 2.2, 1.6) > -30  # the tone sits exactly in the middle clip
    assert max_volume_db(out, 4.2, 1.6) < -60  # silent clip again


def test_concat_pads_video_that_is_shorter_than_its_audio(av_clip, tmp_path):
    uneven = generate(tmp_path / "uneven.mp4", pattern(seconds=1.5), sine(2))
    assert stream_stat(uneven, "v")[0] == 36
    out = tmp_path / "joined.mp4"
    video.concat([uneven, av_clip], out, lufs=None)
    assert stream_stat(out, "v")[0] == 96  # the last frame is held for the missing half second
    assert stream_stat(out, "a")[1] == pytest.approx(4.0, abs=0.1)


def test_concat_pads_audio_that_is_shorter_than_its_video(av_clip, tmp_path):
    uneven = generate(tmp_path / "uneven.mp4", pattern(seconds=2), sine(1))
    out = tmp_path / "joined.mp4"
    video.concat([uneven, av_clip], out, lufs=None)
    assert stream_stat(out, "a")[1] == pytest.approx(4.0, abs=0.1)
    assert max_volume_db(out, 0.2, 0.6) > -30  # the first clip's own audio
    assert max_volume_db(out, 1.2, 0.6) < -60  # silence fills the gap
    assert max_volume_db(out, 2.2, 1.5) > -30  # so the second clip's tone starts at 2.0 s


def test_concat_silent_clips_survive_a_crossfade(av_clip, silent_clip, tmp_path):
    out = tmp_path / "faded.mp4"
    info = video.concat([silent_clip, av_clip], out, crossfade_s=0.5, lufs=None)
    assert info.duration_s == pytest.approx(3.5, abs=0.1)
    assert max_volume_db(out, 0.0, 1.0) < -60
    assert max_volume_db(out, 2.2, 1.0) > -30


def test_concat_conforms_every_clip_to_the_first_clip_and_fps(av_clip, tmp_path):
    other = generate(tmp_path / "other.mp4", pattern("320x180", 30), sine())
    out = tmp_path / "conformed.mp4"
    info = video.concat([av_clip, other], out, lufs=None, fps=25)
    assert (info.width, info.height, info.fps) == (640, 360, 25.0)
    assert stream_stat(out, "v")[0] == 100


def test_concat_letterboxes_instead_of_stretching(av_clip, tmp_path):
    portrait = generate(tmp_path / "portrait.mp4", pattern("360x640"), sine())
    out = tmp_path / "boxed.mp4"
    video.concat([av_clip, portrait], out, lufs=None)
    frame = pixels(video.extract_frame(out, tmp_path / "boxed.png", 3.0))
    assert frame[:, :200].mean() < 8  # black pillar on the left
    assert frame[:, 240:400].mean() > 40  # the portrait picture in the middle


def test_concat_single_clip_with_crossfade_is_just_a_conform(av_clip, tmp_path):
    info = video.concat([av_clip], tmp_path / "one.mp4", crossfade_s=0.5, lufs=None)
    assert info.duration_s == pytest.approx(2.0, abs=0.1)


def test_concat_normalises_loudness_by_default(av_clip, tmp_path):
    video.concat([av_clip], tmp_path / "raw.mp4", lufs=None)
    assert measure_lufs(tmp_path / "raw.mp4") == pytest.approx(-21.8, abs=1.0)
    video.concat([av_clip, av_clip], tmp_path / "loud.mp4")
    assert measure_lufs(tmp_path / "loud.mp4") == pytest.approx(-14.0, abs=1.5)


def test_concat_of_only_silent_clips_still_produces_audio(silent_clip, tmp_path):
    info = video.concat([silent_clip, silent_clip], tmp_path / "quiet.mp4")
    assert info.has_audio is True
    assert max_volume_db(tmp_path / "quiet.mp4", 0.5, 3.0) < -60


def test_concat_validates_its_arguments(av_clip, tmp_path):
    out = tmp_path / "bad.mp4"
    with pytest.raises(ValueError, match="at least one"):
        video.concat([], out)
    with pytest.raises(ValueError, match="half"):
        video.concat([av_clip, av_clip], out, crossfade_s=1.5)
    with pytest.raises(ValueError):
        video.concat([av_clip], out, crossfade_s=-1)
    with pytest.raises(ValueError):
        video.concat([av_clip], out, fps=0)
    wav = tmp_path / "tone.wav"
    run_ffmpeg("-loglevel", "error", "-f", "lavfi", "-i", sine(1), str(wav))
    with pytest.raises(video.VideoError, match="no video stream"):
        video.concat([av_clip, wav], out)
    assert not out.exists()


def test_loudnorm_two_pass_reaches_the_target(av_clip, tmp_path):
    assert measure_lufs(av_clip) < -20
    out = video.loudnorm_two_pass(av_clip, tmp_path / "norm.mp4")
    assert measure_lufs(out) == pytest.approx(-14.0, abs=1.5)
    assert audio_rate(out) == 48000  # loudnorm itself emits 192 kHz
    assert_faststart(out)


def test_loudnorm_two_pass_applies_the_measured_values_linearly(av_clip, tmp_path, monkeypatch):
    commands = []
    real_run = video._run

    def spy(cmd, **kwargs):
        commands.append(cmd)
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(video, "_run", spy)
    video.loudnorm_two_pass(av_clip, tmp_path / "out.mp4", lufs=-16, true_peak=-2, lra=9)
    filters = [cmd[cmd.index("-af") + 1] for cmd in commands if "-af" in cmd]
    assert len(filters) == 2
    measure, apply = filters
    assert "I=-16:TP=-2:LRA=9" in measure and "print_format=json" in measure
    assert "measured" not in measure and "linear" not in measure
    assert "I=-16:TP=-2:LRA=9" in apply and "linear=true" in apply
    assert re.search(r"measured_I=-2\d\.\d+:measured_TP=-1\d\.\d+", apply)
    assert "measured_LRA=" in apply and "measured_thresh=" in apply and "offset=" in apply


def test_loudnorm_two_pass_honours_a_custom_target(av_clip, tmp_path):
    out = video.loudnorm_two_pass(av_clip, tmp_path / "quiet.mp4", lufs=-18.0)
    assert measure_lufs(out) == pytest.approx(-18.0, abs=1.5)


def test_loudnorm_two_pass_copies_the_video_stream(av_clip, tmp_path):
    out = video.loudnorm_two_pass(av_clip, tmp_path / "norm.mp4")
    assert stream_stat(out, "v")[0] == stream_stat(av_clip, "v")[0] == 48
    before = pixels(video.extract_frame(av_clip, tmp_path / "before.png", "last"))
    after = pixels(video.extract_frame(out, tmp_path / "after.png", "last"))
    assert np.array_equal(before, after)


def test_loudnorm_two_pass_remuxes_media_without_audio(silent_clip, tmp_path):
    out = video.loudnorm_two_pass(silent_clip, tmp_path / "same.mp4")
    info = video.probe(out)
    assert info.has_audio is False
    assert stream_stat(out, "v")[0] == 48


def test_loudnorm_two_pass_tolerates_digital_silence(tmp_path):
    silence = generate(tmp_path / "mute.mp4", pattern(), "anullsrc=r=48000:cl=stereo:d=2")
    out = video.loudnorm_two_pass(silence, tmp_path / "mute-out.mp4")
    assert video.probe(out).has_audio is True
    assert max_volume_db(out, 0.2, 1.5) < -60


def test_crop_9x16_scales_to_the_requested_height(av_clip, tmp_path):
    out = video.crop_9x16(av_clip, tmp_path / "portrait.mp4")
    info = video.probe(out)
    assert (info.width, info.height) == (1080, 1920)
    assert (info.video_codec, info.has_audio) == ("h264", True)
    assert info.duration_s == pytest.approx(2.0, abs=0.1)
    small = video.probe(video.crop_9x16(av_clip, tmp_path / "small.mp4", height=640))
    assert (small.width, small.height) == (360, 640)


def test_crop_9x16_follows_the_focus_point(halves_clip, tmp_path):
    def sample(focus: float, x: int) -> np.ndarray:
        out = video.crop_9x16(halves_clip, tmp_path / f"f{focus}.mp4", focus_x=focus, height=640)
        return pixels(video.extract_frame(out, tmp_path / f"f{focus}.png", "first"))[320, x]

    assert is_red(sample(0.0, 180)) and is_red(sample(0.0, 20))
    assert is_blue(sample(1.0, 180)) and is_blue(sample(1.0, 20))
    assert is_red(sample(0.5, 20)) and is_blue(sample(0.5, 340))  # the seam sits in the middle
    assert is_red(sample(-4.0, 180)) and is_blue(sample(9.0, 180))  # out-of-range is clamped


def test_crop_9x16_copes_with_sources_narrower_than_portrait(tmp_path):
    tall = generate(tmp_path / "tall.mp4", pattern("320x640", seconds=1), audio=False)
    info = video.probe(video.crop_9x16(tall, tmp_path / "out.mp4", height=640))
    assert (info.width, info.height, info.has_audio) == (360, 640, False)


def test_embed_metadata_roundtrips_a_long_value(av_clip, tmp_path, probe_tool):
    long_value = "AbC-_" * 1250
    out = video.embed_metadata(
        av_clip, tmp_path / "tagged.mp4", {"openfield_receipt": long_value, "Title": "Take 1"}
    )
    tags = video.read_metadata(out)
    assert tags["openfield_receipt"] == long_value
    assert tags["title"] == "Take 1"
    assert "major_brand" in tags
    assert_faststart(out)


def test_embed_metadata_copies_streams_untouched(av_clip, tmp_path):
    out = video.embed_metadata(av_clip, tmp_path / "tagged.mp4", {"note": "x"})
    info = video.probe(out)
    assert (info.video_codec, info.has_audio, info.width, info.height) == ("h264", True, 640, 360)
    assert stream_stat(out, "v")[0] == 48
    before = pixels(video.extract_frame(av_clip, tmp_path / "before.png", "mid"))
    after = pixels(video.extract_frame(out, tmp_path / "after.png", "mid"))
    assert np.array_equal(before, after)


def test_metadata_survives_awkward_characters(av_clip, tmp_path, probe_tool):
    out = video.embed_metadata(av_clip, tmp_path / "t.mp4", {"note": AWKWARD_VALUE})
    assert video.read_metadata(out)["note"] == AWKWARD_VALUE


def test_embed_metadata_merges_with_existing_tags(av_clip, tmp_path, probe_tool):
    first = video.embed_metadata(av_clip, tmp_path / "one.mp4", {"a": "1", "b": "2"})
    second = video.embed_metadata(first, tmp_path / "two.mp4", {"a": "9", "c": "3"})
    tags = video.read_metadata(second)
    assert (tags["a"], tags["b"], tags["c"]) == ("9", "2", "3")


def test_embed_metadata_empty_value_removes_the_tag(av_clip, tmp_path, probe_tool):
    first = video.embed_metadata(av_clip, tmp_path / "one.mp4", {"gone": "soon", "kept": "yes"})
    second = video.embed_metadata(first, tmp_path / "two.mp4", {"gone": ""})
    tags = video.read_metadata(second)
    assert "gone" not in tags and tags["kept"] == "yes"


def test_embed_metadata_can_overwrite_its_own_input(av_clip, tmp_path):
    work = tmp_path / "work.mp4"
    shutil.copyfile(av_clip, work)
    video.embed_metadata(work, work, {"note": "in place"})
    assert video.read_metadata(work)["note"] == "in place"
    assert video.probe(work).duration_s == pytest.approx(2.0, abs=0.05)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["work.mp4"]


def test_embed_metadata_rejects_invalid_keys(av_clip, tmp_path):
    for key in ("", "a=b"):
        with pytest.raises(ValueError, match="invalid metadata key"):
            video.embed_metadata(av_clip, tmp_path / "x.mp4", {key: "v"})
    assert not (tmp_path / "x.mp4").exists()


def test_read_metadata_of_untagged_media(av_clip, probe_tool):
    tags = video.read_metadata(av_clip)
    assert "openfield_receipt" not in tags
    assert all(key == key.lower() for key in tags)


def test_ffmetadata_parser_unescapes_values_and_stops_at_sections():
    document = (
        ";FFMETADATA1\nplain=v\neq=a\\=b\\;c\\#d\\\\e\nmulti=l1\\\nl2\\\n[bracket\n"
        "[STREAM]\ntitle=stream title\n"
    )
    assert video._parse_ffmetadata(document) == {
        "plain": "v",
        "eq": "a=b;c#d\\e",
        "multi": "l1\nl2\n[bracket",
    }


def test_paths_with_spaces_and_unicode_work_everywhere(av_clip, tmp_path):
    folder = tmp_path / "séance one"
    folder.mkdir()
    source = folder / "prise 1 – é.mp4"
    shutil.copyfile(av_clip, source)
    as_text = str(source)  # plain strings work wherever a Path does
    assert video.probe(as_text).width == 640
    assert video.extract_frame(as_text, str(folder / "frame é.png")).is_file()
    tagged = video.embed_metadata(as_text, folder / "tagged é.mp4", {"k": "v"})
    assert video.read_metadata(str(tagged))["k"] == "v"
    assert video.prepare_source(as_text, folder / "prep é.mp4").width == 640
    assert video.concat([as_text, source], folder / "cat é.mp4", lufs=None).duration_s > 3.9
    assert video.loudnorm_two_pass(as_text, folder / "loud é.mp4").is_file()
    assert video.probe(video.crop_9x16(as_text, folder / "crop é.mp4")).width == 1080


def test_ffmpeg_failures_raise_video_error_with_the_stderr_tail(tmp_path):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"\x00" * 64)
    out = tmp_path / "out.png"
    with pytest.raises(video.VideoError, match="Invalid data found"):
        video.extract_frame(junk, out, "first")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["junk.mp4"]


def test_a_failed_run_never_clobbers_an_existing_output(tmp_path):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"\x00" * 64)
    out = tmp_path / "keep.mp4"
    out.write_bytes(b"precious")
    with pytest.raises(video.VideoError):
        video.crop_9x16(junk, out)
    assert out.read_bytes() == b"precious"


def test_missing_ffmpeg_binary_is_a_video_error(tmp_path, monkeypatch, ramp_clip):
    monkeypatch.setenv("OPENFIELD_FFMPEG", str(tmp_path / "no-such-ffmpeg.exe"))
    with pytest.raises(video.VideoError, match="cannot run"):
        video.extract_frame(ramp_clip, tmp_path / "x.png", "first")
