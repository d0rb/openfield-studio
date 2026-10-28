#!/usr/bin/env python3
"""Cut the twelve-move sheet into a social reel, a 9:16 cut and a contact sheet.

    python scripts/make_sheet_reel.py --out docs/media

The twelve takes are the featured moves in the rig table: each move's tile take (the measured proof
in `openfield/web/showcase/previews.json`), else `sheet-` plus the move id, underscores turned into
dashes, resolved through `showcase/report.json`. Each take is trimmed to its first
`--seconds` and the clips are joined with crossfades; no GPU, no server, no app. A provenance file
next to each reel records the source take ids, their receipt digests and the ffmpeg operations.

The 9:16 cut crops each trimmed clip around a per-move `--focus move=0.x` point before joining. The
contact sheet is the last frame of every take, tiled 4 by 3 tiles of 320x176 (or 640x352 at 2x) on
the app's own near-black background; no captions are burned in, so the move order is printed for a
caption.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openfield.engine import video  # noqa: E402
from openfield.engine.rig import MOVES  # noqa: E402
from openfield.ledger import write_json  # noqa: E402

SHEET_PREFIX = "sheet-"
REEL_NAME = "reel-12-moves"
VERTICAL_NAME = "reel-12-moves-9x16"
CONTACT_NAME = "contact-sheet-12-moves"
COLUMNS, ROWS = 4, 3
TILE = (320, 176)  # 1x tile; 2x is twice this
GUTTER = 8  # between and around tiles at 1x
BACKGROUND = "0x141311"
VERTICAL_HEIGHT = 1280
SAFE_TAKE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
_STDERR_TAIL = 1500


class SheetError(RuntimeError):
    """A take, a receipt or ffmpeg is missing; the message says which."""


# -- the twelve takes -------------------------------------------------------------------------------


def featured_move_ids() -> list[str]:
    """The promoted moves, in the rig table's featured order."""
    return [move.id for move in MOVES.values() if move.featured]


def sheet_name(move_id: str) -> str:
    return SHEET_PREFIX + move_id.replace("_", "-")


def load_report(path: Path) -> dict[str, str]:
    """Showcase name -> take id, from either the report object or a bare list of entries."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SheetError(f"cannot read the showcase report {path}: {exc}") from exc
    entries = data.get("takes", []) if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise SheetError(f"{path} has no take list")
    found: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name, take_id = entry.get("name"), entry.get("take_id")
        if isinstance(name, str) and isinstance(take_id, str):
            found[name] = take_id
    return found


def load_tiles(path: Path | None) -> dict[str, str]:
    """Move id -> the take its tile plays (previews.json `moves`, the measured proof), or {} when there is none."""
    if not path or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    moves = data.get("moves", {}) if isinstance(data, dict) else {}
    return {k: v for k, v in moves.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(moves, dict) else {}


def resolve_takes(takes_dir: Path, report_path: Path, tiles: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """One entry per featured move: the take folder, media and receipt, or a clear failure. A move's tile take (the
    measured proof the app plays) comes first; its sheet- take is the fallback."""
    report = load_report(report_path)
    tiles = tiles or {}
    moves = featured_move_ids()
    if len(moves) < 12:
        raise SheetError(f"the featured order has {len(moves)} moves, expected 12")
    missing: list[str] = []
    problems: list[str] = []
    resolved: list[dict[str, Any]] = []
    for move_id in moves:
        name = sheet_name(move_id)
        tile = tiles.get(move_id)
        take_id = (tile if tile and SAFE_TAKE_ID.match(tile) and (takes_dir / tile).is_dir() else None) or report.get(name)
        if not take_id:
            missing.append(f"{name} (not in {report_path.name})")
            continue
        if not SAFE_TAKE_ID.match(take_id):
            problems.append(f"{name}: unusable take id {take_id!r}")
            continue
        folder = takes_dir / take_id
        media, receipt = folder / "take.mp4", folder / "receipt.json"
        absent = [f.name for f in (folder / "take.json", media, receipt) if not f.is_file()]
        if absent:
            problems.append(f"{name}: {folder} is missing {', '.join(absent)}")
            continue
        resolved.append({"move": move_id, "sheet": name, "take": take_id, "media": media,
                         "receipt": receipt, "folder": folder})
    if missing or problems:
        detail = "; ".join([*missing, *problems])
        raise SheetError(f"cannot build the 12-move sheet: {detail}")
    return resolved


def receipt_digest(path: Path) -> tuple[str, str]:
    """(algorithm, sha256) from a receipt's integrity block: `digest` or a literal `sha256`."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SheetError(f"cannot read the receipt {path}: {exc}") from exc
    integrity = data.get("integrity") if isinstance(data, dict) else None
    if not isinstance(integrity, dict):
        raise SheetError(f"{path} has no integrity block")
    digest = integrity.get("sha256") or integrity.get("digest")
    if not isinstance(digest, str) or not digest:
        raise SheetError(f"{path} has no integrity sha256")
    alg = integrity.get("alg") if isinstance(integrity.get("alg"), str) else "sha256"
    return alg, digest


# -- ffmpeg ----------------------------------------------------------------------------------------


def _run(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        proc = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL, check=False)
    except OSError as exc:
        raise SheetError(f"cannot run {args[0]}: {exc}") from exc
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", errors="replace").strip()[-_STDERR_TAIL:]
        raise SheetError(f"{Path(args[0]).name} failed ({proc.returncode}): {tail}")
    return proc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _size(path: Path) -> str:
    size = path.stat().st_size
    return f"{size / 1024 / 1024:.1f} MiB" if size >= 1024 * 1024 else f"{size / 1024:.1f} KiB"


def ffmpeg_version() -> str:
    try:
        shown = _run([video.ffmpeg_exe(), "-version"]).stdout.decode("utf-8", errors="replace")
    except SheetError:
        return "unknown"
    first = shown.splitlines()[0] if shown else ""
    return first.strip() or "unknown"


def trim_clip(src: Path, out: Path, seconds: float) -> float:
    """Re-encode the first `seconds` of a take to H.264/AAC, returning the real duration."""
    args = [
        video.ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src), "-t", f"{seconds:.3f}",
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
        str(out),
    ]
    _run(args)
    return video.probe(out).duration_s


# -- contact sheet ---------------------------------------------------------------------------------


def contact_sheet_size(scale: int = 1) -> tuple[int, int]:
    """Canvas size of the 4x3 sheet: a gutter between every tile and around the edge."""
    tile_w, tile_h = TILE[0] * scale, TILE[1] * scale
    gutter = GUTTER * scale
    return (COLUMNS * tile_w + (COLUMNS + 1) * gutter,
            ROWS * tile_h + (ROWS + 1) * gutter)


def _last_frame(src: Path, out_png: Path) -> None:
    """The last frame of a take, padded to a 2x tile so the sheet only has to tile."""
    width, height = TILE[0] * 2, TILE[1] * 2
    fit = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
           f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={BACKGROUND}")
    _run([video.ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
          "-sseof", "-0.08", "-i", str(src), "-frames:v", "1", "-vf", fit, "-update", "1", str(out_png)])


def make_contact_sheet(takes: list[dict[str, Any]], out_png: Path, scale: int = 1) -> Path:
    """Tile the last frame of every take, in order, 4 columns by 3 rows."""
    gutter = GUTTER * scale
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch:
        frames = Path(scratch)
        for index, take in enumerate(takes):
            _last_frame(take["media"], frames / f"f{index:02d}.png")
        chain = f"tile={COLUMNS}x{ROWS}:padding={gutter}:margin={gutter}:color={BACKGROUND}"
        if scale != 2:
            chain = f"scale={TILE[0] * scale}:{TILE[1] * scale}:flags=lanczos,{chain}"
        _run([video.ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
              "-framerate", "1", "-start_number", "0", "-i", str(frames / "f%02d.png"),
              "-vf", chain, "-frames:v", "1", "-update", "1", str(out_png)])
    return out_png


# -- the build -------------------------------------------------------------------------------------


def parse_focus(text: str | None) -> dict[str, float]:
    """`move_id=0.45,other_move=0.55` -> a crop focus per move."""
    focus: dict[str, float] = {}
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        move_id, _, raw = part.partition("=")
        move_id = move_id.strip()
        if not move_id or not raw.strip():
            raise SheetError(f"--focus needs move_id=fraction, got {part!r}")
        try:
            value = float(raw)
        except ValueError:
            raise SheetError(f"--focus for {move_id} is not a number: {raw!r}") from None
        if not 0.0 <= value <= 1.0:
            raise SheetError(f"--focus for {move_id} must be between 0 and 1, got {value}")
        focus[move_id] = value
    return focus


def _provenance(kind: str, output: Path, info: video.MediaInfo, takes: list[dict[str, Any]],
                *, seconds: float, crossfade: float, focus: dict[str, float],
                ffmpeg: str) -> dict[str, Any]:
    vertical = kind == "9x16"
    return {
        "schema": "openfield.reel-provenance/1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "output": {
            "file": output.name,
            "format": "9x16" if vertical else "16x9",
            "sha256": _sha256(output),
            "bytes": output.stat().st_size,
            "duration_s": round(info.duration_s, 3),
            "width": info.width,
            "height": info.height,
        },
        "seconds_per_clip": seconds,
        "crossfade_s": crossfade,
        "takes": [
            {
                "index": index,
                "move": take["move"],
                "sheet": take["sheet"],
                "take": take["take"],
                "receipt_alg": take["receipt_alg"],
                "receipt_sha256": take["receipt_sha256"],
                "source_seconds": round(take["source_seconds"], 3),
                "seconds": round(take["clip_seconds"], 3),
                "focus_x": focus.get(take["move"], 0.5) if vertical else None,
            }
            for index, take in enumerate(takes)
        ],
        "operation": {
            "ffmpeg": ffmpeg,
            "trim": {
                "t": seconds,
                "video": "libx264 -preset medium -crf 18 -pix_fmt yuv420p",
                "audio": "aac 192k 48000 Hz",
                "argv": ["-i", "<take.mp4>", "-t", f"{seconds:.3f}", "-map", "0:v:0", "-map", "0:a:0?",
                         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
                         "<clip.mp4>"],
            },
            "vertical": (
                {"function": "openfield.engine.video.crop_9x16", "height": VERTICAL_HEIGHT,
                 "focus_x": {take["move"]: focus.get(take["move"], 0.5) for take in takes}}
                if vertical else None
            ),
            "concat": {
                "function": "openfield.engine.video.concat",
                "crossfade_s": crossfade,
                "lufs": -14.0,
                "fps": 24,
                "transition": "xfade=fade / acrossfade=qsin",
            },
        },
    }


def _print_output(path: Path, info: video.MediaInfo) -> None:
    print(f"  {path}  {info.duration_s:.2f} s  {info.width}x{info.height}  {_size(path)}")


def build(args: argparse.Namespace) -> list[Path]:
    takes_dir, out_dir = Path(args.takes), Path(args.out)
    if not takes_dir.is_dir():
        raise SheetError(f"no takes folder at {takes_dir}")
    if args.seconds <= 0:
        raise SheetError("--seconds must be greater than 0")
    if args.crossfade < 0 or 2 * args.crossfade > args.seconds:
        raise SheetError("--crossfade must be at least 0 and at most half of --seconds")
    if not (2 <= len(featured_move_ids()) <= 24):
        raise SheetError("the featured move order does not look like the twelve-move sheet")

    takes = resolve_takes(takes_dir, Path(args.report), load_tiles(Path(args.previews)) if args.previews else None)
    moves = [take["move"] for take in takes]
    focus = parse_focus(args.focus)
    unknown = sorted(set(focus) - set(moves))
    if unknown:
        raise SheetError(f"--focus names moves that are not on the sheet: {', '.join(unknown)}")

    out_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = ffmpeg_version()
    written: list[Path] = []

    print(f"Twelve moves, in order ({args.seconds:g} s each, {args.crossfade:g} s crossfade):")
    for index, take in enumerate(takes, start=1):
        label = MOVES[take["move"]].label if take["move"] in MOVES else take["move"]
        print(f"  {index:2d}. {take['move']} - {label}  ({take['take']})")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch:
        work = Path(scratch)
        for index, take in enumerate(takes):
            clip = work / f"clip{index:02d}.mp4"
            take["clip_seconds"] = trim_clip(take["media"], clip, args.seconds)
            take["source_seconds"] = video.probe(take["media"]).duration_s
            take["clip"] = clip
            take["receipt_alg"], take["receipt_sha256"] = receipt_digest(take["receipt"])

        reel = out_dir / f"{REEL_NAME}.mp4"
        info = video.concat([take["clip"] for take in takes], reel,
                            crossfade_s=args.crossfade, lufs=-14.0)
        provenance = _provenance("16x9", reel, info, takes, seconds=args.seconds,
                                 crossfade=args.crossfade, focus=focus, ffmpeg=ffmpeg)
        write_json(reel.with_name(f"{REEL_NAME}.provenance.json"), provenance)
        written += [reel, reel.with_name(f"{REEL_NAME}.provenance.json")]

        vertical_info = None
        if not args.no_vertical:
            portraits: list[Path] = []
            for index, take in enumerate(takes):
                portrait = work / f"vertical{index:02d}.mp4"
                video.crop_9x16(take["clip"], portrait, focus_x=focus.get(take["move"], 0.5),
                                height=VERTICAL_HEIGHT)
                portraits.append(portrait)
            vertical = out_dir / f"{VERTICAL_NAME}.mp4"
            vertical_info = video.concat(portraits, vertical, crossfade_s=args.crossfade, lufs=-14.0)
            vertical_provenance = _provenance("9x16", vertical, vertical_info, takes,
                                              seconds=args.seconds, crossfade=args.crossfade,
                                              focus=focus, ffmpeg=ffmpeg)
            write_json(vertical.with_name(f"{VERTICAL_NAME}.provenance.json"), vertical_provenance)
            written += [vertical, vertical.with_name(f"{VERTICAL_NAME}.provenance.json")]

        sheet = out_dir / f"{CONTACT_NAME}.png"
        make_contact_sheet(takes, sheet, scale=1)
        sheet_2x = out_dir / f"{CONTACT_NAME}-2x.png"
        make_contact_sheet(takes, sheet_2x, scale=2)
        written += [sheet, sheet_2x]

    print("\nWrote:")
    _print_output(reel, info)
    if vertical_info is not None:
        _print_output(out_dir / f"{VERTICAL_NAME}.mp4", vertical_info)
    for image in (out_dir / f"{CONTACT_NAME}.png", out_dir / f"{CONTACT_NAME}-2x.png"):
        image_info = video.probe(image)
        print(f"  {image}  {image_info.width}x{image_info.height}  {_size(image)}")
    for provenance_file in sorted(out_dir.glob(f"{REEL_NAME}*.provenance.json")):
        print(f"  {provenance_file}  {_size(provenance_file)}")
    print(f"\nContact sheet: {COLUMNS} columns x {ROWS} rows, {TILE[0]}x{TILE[1]} tiles, "
          f"{GUTTER} px gutters, background #{BACKGROUND[2:]}.")
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--takes", default=str(ROOT / "openfield" / "web" / "showcase" / "takes"),
                        help="folder of finished takes, one folder per take id")
    parser.add_argument("--report", default=str(ROOT / "showcase" / "report.json"),
                        help="showcase report mapping showcase names to take ids")
    parser.add_argument("--previews", default=str(ROOT / "openfield" / "web" / "showcase" / "previews.json"),
                        help="previews index whose move tiles name each move's measured take ('' to use sheet- names only)")
    parser.add_argument("--out", default=str(ROOT / "docs" / "media"), help="output folder")
    parser.add_argument("--seconds", type=float, default=2.5, help="seconds kept from each take")
    parser.add_argument("--crossfade", type=float, default=0.3, help="crossfade between moves, seconds")
    parser.add_argument("--focus", default="",
                        help='per-move 9:16 crop focus, e.g. "dolly_in=0.45,track_left=0.55"')
    parser.add_argument("--no-vertical", action="store_true", help="skip the 9:16 cut")
    args = parser.parse_args(argv)
    try:
        build(args)
    except SheetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
