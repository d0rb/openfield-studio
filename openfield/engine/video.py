"""ffmpeg helpers for Takes: probing, frame grabs, source prep, joins, loudness, crops, tags.

Every call is a plain argv list (never a shell), so paths with spaces are safe. Outputs are
written to a sibling temp file and moved into place, so a failed run never leaves a partial
file and an output may safely overwrite its own input.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ..fsutil import replace_file

PathLike = str | os.PathLike[str]

_TAIL_CHARS = 1500
_MIB = 1024 * 1024
_AUDIO_KBPS = 128
_MIN_VIDEO_KBPS = 50
_X264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
_AAC = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
_PCM = ["-c:a", "pcm_s16le"]
_FASTSTART = ["-movflags", "+faststart"]
_LAST_FRAME_WINDOW_S = 0.5
_LOUDNORM_KEYS = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")


class VideoError(RuntimeError):
    """ffmpeg/ffprobe could not run or failed; the message ends with the stderr tail."""


@dataclass(frozen=True)
class MediaInfo:
    duration_s: float
    fps: float
    width: int
    height: int
    has_audio: bool
    video_codec: str | None
    size_bytes: int


_Probed = tuple[MediaInfo, float]  # MediaInfo plus the display-matrix rotation in degrees


def ffmpeg_exe() -> str:
    """Resolve ffmpeg: $OPENFIELD_FFMPEG, then PATH, then the imageio-ffmpeg bundled binary."""
    exe = os.environ.get("OPENFIELD_FFMPEG") or shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as exc:
        raise VideoError("ffmpeg not found: set OPENFIELD_FFMPEG or add it to PATH") from exc


def ffprobe_exe() -> str | None:
    """Resolve ffprobe: $OPENFIELD_FFPROBE, then PATH, else None (callers fall back to ffmpeg)."""
    return os.environ.get("OPENFIELD_FFPROBE") or shutil.which("ffprobe")


def _text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    try:
        proc = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, check=False)
    except OSError as exc:
        raise VideoError(f"cannot run {cmd[0]}: {exc}") from exc
    if check and proc.returncode != 0:
        tail = _text(proc.stderr).strip()[-_TAIL_CHARS:]
        raise VideoError(f"{Path(cmd[0]).name} failed ({proc.returncode}): {tail}")
    return proc


def _ffmpeg(args: list[str]) -> None:
    _run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args])


def _stage(out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    return out.with_name(f"{out.stem}.{uuid.uuid4().hex[:8]}.part{out.suffix}")


def _commit(staged: Path, out: Path) -> Path:
    if not staged.is_file() or staged.stat().st_size == 0:
        raise VideoError(f"ffmpeg produced no output for {out.name}")
    replace_file(staged, out)
    return out


def _encode(args: list[str], out: Path) -> Path:
    staged = _stage(out)
    try:
        _ffmpeg([*args, str(staged)])
        return _commit(staged, out)
    finally:
        staged.unlink(missing_ok=True)


def _num(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _ratio(value: Any) -> float:
    try:
        numerator, denominator = str(value).split("/")
        return int(numerator) / int(denominator)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _upright(width: int, height: int, rotation: float) -> tuple[int, int]:
    """Display size: a quarter-turn display matrix (phone footage) swaps the coded size."""
    return (height, width) if round(rotation) % 180 == 90 else (width, height)


def _main_video(streams: list[dict[str, Any]]) -> dict[str, Any]:
    for stream in streams:
        is_cover = stream.get("disposition", {}).get("attached_pic")
        if stream.get("codec_type") == "video" and not is_cover:
            return stream
    return {}


def _probe_ffprobe(exe: str, media: Path, size: int) -> _Probed:
    """MediaInfo with the coded size, and the display-matrix rotation in degrees."""
    cmd = [exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(media)]
    data = json.loads(_text(_run(cmd).stdout))
    streams = data.get("streams", [])
    video = _main_video(streams)
    turns = [_num(s["rotation"]) for s in video.get("side_data_list", []) if "rotation" in s]
    info = MediaInfo(
        duration_s=_num(data.get("format", {}).get("duration")) or _num(video.get("duration")),
        fps=_ratio(video.get("avg_frame_rate")) or _ratio(video.get("r_frame_rate")),
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        video_codec=video.get("codec_name"),
        size_bytes=size,
    )
    return info, turns[0] if turns else 0.0


_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_STREAM = re.compile(r"^\s*Stream #\d+:\d+[^\n]*?: (Video|Audio): ([^\n]*)", re.MULTILINE)
_SIZE = re.compile(r",\s*(\d{2,5})x(\d{2,5})\b")
_RATE = re.compile(r"(\d+(?:\.\d+)?) (?:fps|tbr)\b")
_TURN = re.compile(r"displaymatrix: rotation of (-?\d+(?:\.\d+)?) degrees")


def _probe_ffmpeg(media: Path, size: int) -> _Probed:
    """Same as `_probe_ffprobe`, parsed from the `ffmpeg -i` banner when ffprobe is missing."""
    cmd = [ffmpeg_exe(), "-hide_banner", "-i", str(media)]
    report = _text(_run(cmd, check=False).stderr)
    if "Input #0" not in report:
        raise VideoError(f"ffmpeg could not open {media.name}: {report.strip()[-_TAIL_CHARS:]}")
    streams = _STREAM.findall(report)
    lines = [rest for kind, rest in streams if kind == "Video" and "attached pic" not in rest]
    video = lines[0] if lines else ""
    clock, codec = _DURATION.search(report), re.match(r"[\w-]+", video)
    dims, rate, turn = _SIZE.search(video), _RATE.search(video), _TURN.search(report)
    info = MediaInfo(
        duration_s=int(clock[1]) * 3600 + int(clock[2]) * 60 + float(clock[3]) if clock else 0.0,
        fps=float(rate[1]) if rate else 0.0,
        width=int(dims[1]) if dims else 0,
        height=int(dims[2]) if dims else 0,
        has_audio=any(kind == "Audio" for kind, _ in streams),
        video_codec=codec.group() if codec else None,
        size_bytes=size,
    )
    return info, float(turn[1]) if turn else 0.0


def _probe_with_rotation(path: PathLike) -> _Probed:
    media = Path(path)
    if not media.is_file():
        raise VideoError(f"not a file: {media}")
    size = media.stat().st_size
    exe = ffprobe_exe()
    coded, turn = _probe_ffprobe(exe, media, size) if exe else _probe_ffmpeg(media, size)
    width, height = _upright(coded.width, coded.height, turn)
    return replace(coded, width=width, height=height), turn


def probe(path: PathLike) -> MediaInfo:
    """Container duration, first video stream display size/fps/codec and audio presence."""
    return _probe_with_rotation(path)[0]


def _seek_seconds(video: Path, at: float | str) -> float:
    if at == "first":
        return 0.0
    if at == "mid":
        return probe(video).duration_s / 2
    if isinstance(at, str) or at < 0:
        raise ValueError(f"at must be seconds >= 0, 'first', 'mid' or 'last', got {at!r}")
    return float(at)


def extract_frame(video: PathLike, out_png: PathLike, at: float | str = "mid") -> Path:
    """Save one frame as PNG. `at` is seconds or "first" | "mid" | "last".

    "last" decodes the final half second and keeps the last frame, so it is the true last frame
    rather than a frame near the end.
    """
    src = Path(video)
    if at == "last":
        seek = ["-sseof", f"-{_LAST_FRAME_WINDOW_S}", "-i", str(src), "-an", "-update", "1"]
    else:
        seek = ["-ss", f"{_seek_seconds(src, at):.3f}", "-i", str(src), "-an", "-frames:v", "1"]
    return _encode(seek, Path(out_png))


def _video_budget_kbps(limit_bytes: int, seconds: float) -> float:
    """Video bitrate that keeps audio + video (+ ~8% container slack) under the size limit."""
    return (limit_bytes * 8 / 1000 / seconds - _AUDIO_KBPS) * 0.92


def _rate_plan(budget_kbps: float) -> list[list[str]]:
    """Quality first, then capped-CRF attempts with a shrinking bitrate ceiling."""
    plan = [["-crf", "20"]]
    for crf, share in ((24, 1.0), (28, 0.75), (32, 0.5)):
        cap = int(budget_kbps * share)
        plan.append(["-crf", str(crf), "-maxrate", f"{cap}k", "-bufsize", f"{2 * cap}k"])
    return plan


def prepare_source(
    video: PathLike,
    out_mp4: PathLike,
    *,
    max_seconds: float = 30.0,
    max_height: int = 720,
    max_mb: float = 95.0,
) -> MediaInfo:
    """Normalise an uploaded clip: trimmed, never upscaled, H.264/AAC, faststart, <= max_mb MiB.

    Global metadata (GPS, device tags) is dropped. If the first encode is too large it is
    retried with higher CRF and a bitrate ceiling; VideoError if it cannot be made to fit.
    """
    src, out = Path(video), Path(out_mp4)
    limit = int(max_mb * _MIB)
    duration = probe(src).duration_s
    seconds = min(duration, max_seconds) if duration > 0 else max_seconds
    budget = _video_budget_kbps(limit, seconds)
    if budget < _MIN_VIDEO_KBPS:
        raise VideoError(f"{max_mb:g} MiB is too small for {seconds:.0f}s of video")
    base = [
        *("-i", str(src), "-t", f"{max_seconds:.3f}"),
        *("-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "-1", "-map_chapters", "-1"),
        *("-vf", f"scale=-2:'trunc(min({max_height},ih)/2)*2'"),
        *("-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p"),
        *("-c:a", "aac", "-b:a", f"{_AUDIO_KBPS}k", *_FASTSTART),
    ]
    staged = _stage(out)
    try:
        for rate in _rate_plan(budget):
            _ffmpeg([*base, *rate, str(staged)])
            if staged.stat().st_size <= limit:
                _commit(staged, out)
                return probe(out)
    finally:
        staged.unlink(missing_ok=True)
    raise VideoError(f"could not fit {src.name} under {max_mb:g} MiB")


def _video_chain(index: int, seconds: float, width: int, height: int, fps: float) -> str:
    return (
        f"[{index}:v:0]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}:start_time=0,"
        f"tpad=stop_mode=clone:stop_duration={seconds:.3f},trim=duration={seconds:.3f},"
        f"format=yuv420p[v{index}]"
    )


def _audio_chain(index: int, seconds: float, has_audio: bool) -> str:
    if not has_audio:
        return f"anullsrc=r=48000:cl=stereo:d={seconds:.3f},aformat=sample_fmts=fltp[a{index}]"
    return (
        f"[{index}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"apad=whole_dur={seconds:.3f},atrim=duration={seconds:.3f},asetpts=PTS-STARTPTS[a{index}]"
    )


def _crossfade_chains(durations: list[float], fade: float) -> list[str]:
    parts: list[str] = []
    video, audio, elapsed = "v0", "a0", durations[0]
    for index, length in enumerate(durations[1:], start=1):
        parts.append(
            f"[{video}][v{index}]xfade=transition=fade:duration={fade:.3f}"
            f":offset={elapsed - fade:.3f}[xv{index}]"
        )
        parts.append(f"[{audio}][a{index}]acrossfade=d={fade:.3f}:c1=qsin:c2=qsin[xa{index}]")
        video, audio, elapsed = f"xv{index}", f"xa{index}", elapsed + length - fade
    return [*parts, f"[{video}]null[v]", f"[{audio}]anull[a]"]


def _join_graph(infos: list[MediaInfo], size: tuple[int, int], fps: float, fade: float) -> str:
    parts: list[str] = []
    for index, info in enumerate(infos):
        parts.append(_video_chain(index, info.duration_s, *size, fps))
        parts.append(_audio_chain(index, info.duration_s, info.has_audio))
    if fade > 0 and len(infos) > 1:
        return ";".join([*parts, *_crossfade_chains([i.duration_s for i in infos], fade)])
    labels = "".join(f"[v{i}][a{i}]" for i in range(len(infos)))
    return ";".join([*parts, f"{labels}concat=n={len(infos)}:v=1:a=1[v][a]"])


def _require_joinable(paths: list[Path], probed: list[_Probed], fade: float) -> None:
    for path, (info, turn) in zip(paths, probed, strict=True):
        if info.width == 0 or info.duration_s <= 0:
            raise VideoError(f"{path.name} has no video stream or an unknown duration")
        if round(turn) % 360:
            raise VideoError(f"{path.name} carries a rotation flag; run prepare_source on it first")
    if fade > 0 and len(probed) > 1 and 2 * fade > min(info.duration_s for info, _ in probed):
        raise ValueError("crossfade_s must be at most half of the shortest clip")


def concat(
    clips: Iterable[PathLike],
    out: PathLike,
    *,
    crossfade_s: float = 0.0,
    lufs: float | None = -14.0,
    fps: float = 24,
) -> MediaInfo:
    """Join clips into one MP4 (H.264/AAC).

    Every clip is letterboxed to the first clip's size, resampled to `fps`, and padded or cut to
    its container duration, with silence standing in for missing audio, so audio and video stay
    in sync across joins. `crossfade_s` > 0 dissolves between clips (the total shortens by
    crossfade_s per join); `lufs` not None loudness-normalises the result. Clips with a
    rotation flag (raw phone footage) are refused: normalise them with `prepare_source` first.
    """
    paths = [Path(c) for c in clips]
    if not paths:
        raise ValueError("concat needs at least one clip")
    if crossfade_s < 0 or fps <= 0:
        raise ValueError("crossfade_s must be >= 0 and fps > 0")
    probed = [_probe_with_rotation(p) for p in paths]
    _require_joinable(paths, probed, crossfade_s)
    infos = [info for info, _ in probed]
    size = (infos[0].width // 2 * 2, infos[0].height // 2 * 2)
    graph = _join_graph(infos, size, fps, crossfade_s)
    args = [arg for p in paths for arg in ("-i", str(p))]
    args += ["-filter_complex", graph, "-map", "[v]", "-map", "[a]"]
    target = Path(out)
    if lufs is None:
        _encode([*args, *_X264, *_AAC, *_FASTSTART], target)
    else:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch:
            joined = _encode([*args, *_X264, *_PCM], Path(scratch) / "joined.mov")
            loudnorm_two_pass(joined, target, lufs=lufs)
    return probe(target)


_LOUDNORM_JSON = re.compile(r'\{[^{}]*"input_i"[^{}]*\}')


def _measure_loudness(src: Path, goal: str) -> dict[str, str] | None:
    """First loudnorm pass; None when there is nothing measurable (no audio or pure silence)."""
    if not probe(src).has_audio:
        return None
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostats", "-loglevel", "info", "-i", str(src)]
    cmd += ["-vn", "-af", f"loudnorm={goal}:print_format=json", "-f", "null", "-"]
    found = _LOUDNORM_JSON.search(_text(_run(cmd).stderr))
    stats = json.loads(found.group()) if found else {}
    if not all(key in stats for key in _LOUDNORM_KEYS):
        raise VideoError(f"loudnorm reported no measurements for {src.name}")
    return stats if all(math.isfinite(float(stats[k])) for k in _LOUDNORM_KEYS) else None


def loudnorm_two_pass(
    src: PathLike,
    out: PathLike,
    *,
    lufs: float = -14.0,
    true_peak: float = -1.5,
    lra: float = 11.0,
) -> Path:
    """EBU R128 normalisation: measure, then apply a linear gain; video is stream-copied.

    Media without audio or with pure digital silence has nothing to measure and gets no gain
    change. If the measured peaks leave no headroom, ffmpeg itself falls back to dynamic mode,
    so the result can land below the target.
    """
    source, target = Path(src), Path(out)
    goal = f"I={lufs:g}:TP={true_peak:g}:LRA={lra:g}"
    stats = _measure_loudness(source, goal)
    gain: list[str] = []
    if stats is not None:
        measured = (
            f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}"
            f":measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}"
            f":offset={stats['target_offset']}"
        )
        gain = ["-af", f"loudnorm={goal}:{measured}:linear=true"]
    args = ["-i", str(source), "-map", "0:v:0?", "-map", "0:a:0?", "-c:v", "copy"]
    return _encode([*args, *gain, *_AAC, *_FASTSTART], target)


def crop_9x16(src: PathLike, out: PathLike, *, focus_x: float = 0.5, height: int = 1920) -> Path:
    """Crop to portrait 9:16 around `focus_x` (0 = left edge, 1 = right edge), scale to `height`."""
    width = round(height * 9 / 16 / 2) * 2
    focus = min(max(focus_x, 0.0), 1.0)
    crop = (
        "crop=w='min(iw,ih*9/16)':h='min(ih,iw*16/9)'"
        f":x='clip({focus:.4f}*iw-ow/2,0,iw-ow)':y='(ih-oh)/2'"
    )
    args = ["-i", str(src), "-vf", f"{crop},scale={width}:{height},setsar=1"]
    return _encode([*args, *_X264, *_AAC, *_FASTSTART], Path(out))


def embed_metadata(src: PathLike, out: PathLike, tags: dict[str, str]) -> Path:
    """Copy streams untouched and add format-level tags (an empty value removes the tag).

    MP4 stores custom keys in the mdta atom, which `+use_metadata_tags` enables. Read keys back
    lower-cased, so write them lower-case.
    """
    args = ["-i", str(src), "-c", "copy", "-map_metadata", "0"]
    for key, value in tags.items():
        if not key or "=" in key:
            raise ValueError(f"invalid metadata key: {key!r}")
        args += ["-metadata", f"{key}={value}"]
    return _encode([*args, "-movflags", "+use_metadata_tags+faststart"], Path(out))


_FFMETADATA = re.compile(
    r"^(?:\[(?:STREAM|CHAPTER)\]|((?:[^=\\\n]|\\.)+)=((?:[^\\\n]|\\.)*))$", re.MULTILINE | re.DOTALL
)
_ESCAPED = re.compile(r"\\(.)", re.DOTALL)


def _parse_ffmetadata(text: str) -> dict[str, str]:
    """Global tags of an FFMETADATA1 document (stops at the first [STREAM]/[CHAPTER])."""
    tags: dict[str, str] = {}
    for found in _FFMETADATA.finditer(text):
        if found[1] is None:
            break
        tags[_ESCAPED.sub(r"\1", found[1])] = _ESCAPED.sub(r"\1", found[2])
    return tags


def read_metadata(path: PathLike) -> dict[str, str]:
    """Format-level tags with lower-cased keys.

    Without ffprobe this exports `-f ffmetadata` instead of reading the `ffmpeg -i` banner,
    because the banner truncates every value to 255 characters.
    """
    media = str(Path(path))
    exe = ffprobe_exe()
    if exe:
        cmd = [exe, "-v", "error", "-print_format", "json", "-show_entries", "format_tags", media]
        tags = json.loads(_text(_run(cmd).stdout)).get("format", {}).get("tags", {})
    else:
        cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", media]
        tags = _parse_ffmetadata(_text(_run([*cmd, "-f", "ffmetadata", "-"]).stdout))
    return {key.lower(): str(value) for key, value in tags.items()}
