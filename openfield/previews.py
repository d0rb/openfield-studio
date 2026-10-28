"""Cut short muted preview loops from recorded takes and keep their index."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from .engine import receipt as receipts
from .engine import video
from .static_export import recorded_takes

PREVIEW_SECONDS = 2.5
PREVIEW_WIDTH = 384  # the plain copy: the Takes wall's small tiles
PREVIEW_WIDTH_HD = 1280  # every take gets a sharper copy for the cards that show it large: the takes' own size (a recorded take is 1280 px wide), never wider than the take
PREVIEW_WIDTH_MID = 768  # and one between the two: it fills a frame 193 to 384 CSS px wide on a 2x screen (385 to 768 on a 1x one), never wider than the take either
THUMB_WIDTH = 768  # a still is 1 to 5 MB; the strips that show a take's stills as cards load this copy instead, sharp at 2x pixel density

_TAKE_ID = re.compile(r"^tk_\d{8}_\d{6}_[0-9a-f]{4}$")  # only loops named like takes are ever removed
_STILL_THUMB = re.compile(r"^tk_\d{8}_\d{6}_[0-9a-f]{4}-s\d+\.jpg$")  # a still's small copy: <take>-s<n>.jpg
_STILL_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _source_sha256(mp4: Path) -> str:
    return receipts.sha256_file(mp4)


def cut_preview(src_mp4: Path, out_mp4: Path, out_jpg: Path, *, width: int = PREVIEW_WIDTH, crf: int = 30, upscale: bool = True) -> Path:
    """A muted H.264 loop from `src_mp4`, plus a first-frame JPEG poster. A take narrower than `width` is scaled up to it,
    unless `upscale` is False: the loop then keeps the take's own width."""
    info = video.probe(src_mp4)
    if not upscale:
        width = min(width, info.width or width)
    duration = info.duration_s
    start = 0.0 if duration < 3.4 else 0.6
    length = min(PREVIEW_SECONDS, duration - start)

    video._encode(
        [
            "-ss", f"{start:.3f}",
            "-i", str(src_mp4),
            "-t", f"{length:.3f}",
            "-vf", f"scale={width}:-2",
            "-r", "24",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", str(crf),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-an",
        ],
        Path(out_mp4),
    )

    video._encode(
        [
            "-ss", "0",
            "-i", str(out_mp4),
            "-frames:v", "1",
            "-q:v", "4",
        ],
        Path(out_jpg),
    )
    return Path(out_mp4)


def take_stills(folder: Path) -> list[str]:
    """A take's stills, as paths relative to its folder: the stills its runs made and the pictures it was given. A run's
    preview.jpg is the sampler's progress frame, not a still."""
    found = [p for p in folder.glob("runs/*/*") if p.suffix.lower() in _STILL_SUFFIXES and not p.name.startswith("preview")]
    found += [p for p in folder.glob("inputs/*") if p.suffix.lower() in _STILL_SUFFIXES]
    return sorted(p.relative_to(folder).as_posix() for p in found if p.is_file())


def _still_sha(path: Path) -> str:
    return receipts.sha256_file(path)[:16]


def cut_thumb(src: Path, out_jpg: Path, *, width: int = THUMB_WIDTH) -> Path:
    """A small JPEG copy of a still, `width` pixels wide (a smaller still keeps its size)."""
    from PIL import Image

    with Image.open(src) as opened:
        picture = opened.convert("RGB")
    if picture.width > width:
        picture = picture.resize((width, max(1, round(picture.height * width / picture.width))), Image.Resampling.LANCZOS)
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_jpg.with_name(out_jpg.name + ".tmp")
    picture.save(tmp, "JPEG", quality=82, optimize=True, progressive=True)
    tmp.replace(out_jpg)
    return out_jpg


def _read_take(folder: Path) -> dict[str, Any] | None:
    try:
        return json.loads((folder / "take.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# The take a move's tile plays when the newest sheet take is not the best proof of the move, chosen by measuring the
# camera rather than by eye (optical flow, Oct 25). The orbit sheet takes held the camera still while the subject turned
# round (they left the bundle); the pier take circles Oskar (9.8 px/s) and r11-orb-180 swings to his back (12.8 px/s).
# The dolly-in and crane-up sheet takes barely moved or jumped; the samurai draw pushes in (the picture grows 5.8%/s)
# and the rooftop take rises over Mara. The one-still push in, pull out and in-code zoom in (Oct 25) move clearly where
# the earlier takes of those moves barely did.
PROOFS: dict[str, str] = {
    "aerial_pullback": "v2-aerial-pullback",
    "bullet_time": "r13-b3-bt-from44ee-1167",
    "crane_down": "r11-mv-crane-down",
    "crane_up": "mara-rooftop-crane-up",
    "crash_zoom_in": "v1b-cat-dj-zoom",
    "crash_zoom_out": "v8-crash-zoom-out",
    "dolly_in": "r13-a4-draw-up-624",
    "dolly_out": "sheet-dolly-out",
    "dutch_angle": "v9b-dutch-angle-noir",
    "eyes_in": "sig-eyes-in",
    "fisheye": "v2-fisheye",
    "fpv_drone": "r11-mv-fpv-drone",
    "handheld": "v8-handheld",
    "helicopter": "r11-mv-helicopter",
    "hyperlapse": "desert-highway-hyperlapse",
    "lazy_susan": "v3-spin-sneaker",
    "loop": "v3-loop-neon-rain",
    "low_angle": "v8-low-angle",
    "optical_zoom_in": "r11-qk-optical-zoom-in",
    "optical_zoom_out": "r11-mv-optical-zoom-out",
    "orbit_180": "r11-orb-180",
    "orbit_90": "oskar-pier-orbit",
    "over_shoulder": "v8-over-shoulder",
    "pan_left": "v8b-pan-left",
    "pan_right": "v8b-pan-right",
    "pedestal_up": "v8-pedestal-up",
    "pull_out": "r11-qk-pull-out",
    "push_in": "r11-qk-push-in",
    "reveal": "r11-mv-reveal",
    "robot_arm": "r11-mv-robot-arm",
    "snorricam": "sig-snorricam",
    "static": "sheet-static",
    "super_dolly_in": "v8-super-dolly-in",
    "through_object": "r13-c-through-hut-1341",
    "tilt_down": "v8b-tilt-down",
    "tilt_up": "r11-mv-tilt-up",
    "top_down": "r11-mv-top-down",
    "track_left": "r11-mv-track-left",
    "track_right": "sheet-track-right",
    "truck_left": "r11-mv-truck-left",
    "truck_right": "v8-truck-right",
    "vertigo": "r13-c-vertigo-corridor-1361",
    "whip_pan": "v8-whip-pan",
    "yoyo_zoom": "v2-yoyo-zoom",
}


def _pick_mappings(folders: list[Path]) -> tuple[dict[str, str], dict[str, str]]:
    move_candidates: dict[str, list[dict[str, Any]]] = {}
    effect_candidates: dict[str, list[dict[str, Any]]] = {}

    for folder in folders:
        take = _read_take(folder)
        if not take or take.get("kind") != "direct":
            continue
        recipe = take.get("recipe", {})
        rig = recipe.get("rig", {})
        movement = rig.get("movement")
        effect = rig.get("effect")
        # a move's tile shows the plain move: not a take that starts from another angle or speaks a line
        plain = not rig.get("angle") and not recipe.get("line")

        if movement and plain and (not effect or effect == "none"):
            move_candidates.setdefault(movement, []).append(take)
        if effect and effect != "none":
            effect_candidates.setdefault(effect, []).append(take)

    def newest(takes: list[dict[str, Any]]) -> dict[str, Any]:
        return sorted(takes, key=lambda t: t.get("created_at", ""), reverse=True)[0]

    # a tile or a poster plays a move's or an effect's loop only once a real render of it held (the server's flags):
    # a take of a move that has not held yet never plays as that move's proof
    from .engine.rig import VALIDATED, VALIDATED_EFFECTS
    move_candidates = {k: v for k, v in move_candidates.items() if k in VALIDATED}
    effect_candidates = {k: v for k, v in effect_candidates.items() if k in VALIDATED_EFFECTS}

    moves = {}
    for move_id, takes in move_candidates.items():
        chosen = [t for t in takes if move_id in PROOFS and t.get("showcase_name") == PROOFS[move_id]]
        if chosen:
            moves[move_id] = newest(chosen)["id"]
            continue
        sheet = [
            t for t in takes
            if isinstance(t.get("showcase_name"), str)
            and t["showcase_name"].startswith("sheet-")
        ]
        moves[move_id] = newest(sheet if sheet else takes)["id"]

    effects = {
        effect_id: newest(takes)["id"]
        for effect_id, takes in effect_candidates.items()
    }
    return moves, effects


def _is_width(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _larger_copy(
    src: Path,
    out_dir: Path,
    take_id: str,
    name: str,
    width: int,
    crf: int,
    *,
    entry: dict[str, Any],
    before: dict[str, Any],
    cut_at: dict[str, Any],
) -> dict[str, Any]:
    """One of a take's larger loops (`hd` or `mid`) and its poster, as its index record. It is cut again only when the take
    changed or the width it is cut at did. The record says how wide the loop really is: a take narrower than `width` keeps
    its own width, and the cards compare these numbers to pick a copy, so a copy is never claimed wider than it is."""
    mp4, jpg = out_dir / f"{take_id}-{name}.mp4", out_dir / f"{take_id}-{name}.jpg"
    held = before.get(name) if isinstance(before.get(name), dict) else {}
    fresh = (cut_at.get(name) == width and before.get("source_sha256") == entry.get("source_sha256")
             and bool(held) and mp4.is_file() and jpg.is_file())
    if not fresh:
        cut_preview(src, mp4, jpg, width=width, crf=crf, upscale=False)
    recorded = held.get("width") if fresh else None
    # a copy kept from an index that recorded no width is measured, not cut again
    real = recorded if _is_width(recorded) else video.probe(mp4).width
    return {"video": f"showcase/previews/{take_id}-{name}.mp4", "poster": f"showcase/previews/{take_id}-{name}.jpg", "width": real}


def build_previews(
    takes_root: Path | str,
    out_dir: Path | str | None = None,
    index_path: Path | str | None = None,
) -> dict[str, Any]:
    """Cut a plain, a mid-size and a sharper preview loop for every recorded take, a copy of each of its stills, and write `previews.json`."""
    takes_root = Path(takes_root)
    out_dir = Path(out_dir) if out_dir else takes_root.parent / "previews"
    index_path = Path(index_path) if index_path else takes_root.parent / "previews.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)

    previous: dict[str, Any] = {}
    if index_path.is_file():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                previous = data
        except (OSError, ValueError):
            previous = {}
    prev_takes = previous.get("takes") or {}
    if not isinstance(prev_takes, dict):
        prev_takes = {}
    # the widths the larger copies and the still copies were cut at. A width the index does not record counts as another size, so
    # that copy is cut again: an index with no widths at all (written before they were kept) cuts the sharper and the still copies
    # again, one that lacks only `mid` (written before that copy) cuts the mid-size ones and nothing else. The plain loops never
    # depend on a width.
    cut_at = previous.get("widths") if isinstance(previous.get("widths"), dict) else {}

    folders = recorded_takes(takes_root)
    live_ids = {folder.name for folder in folders}
    takes_index: dict[str, Any] = {}

    for folder in folders:
        take = _read_take(folder)
        if not take:
            continue
        take_id = take["id"]
        src = folder / "take.mp4"
        sha = _source_sha256(src)
        existing = prev_takes.get(take_id)
        if (
            isinstance(existing, dict)
            and existing.get("source_sha256") == sha
            and (out_dir / f"{take_id}.mp4").is_file()
            and (out_dir / f"{take_id}.jpg").is_file()
        ):
            takes_index[take_id] = existing
        else:
            cut_preview(src, out_dir / f"{take_id}.mp4", out_dir / f"{take_id}.jpg")
            takes_index[take_id] = {
                "video": f"showcase/previews/{take_id}.mp4",
                "poster": f"showcase/previews/{take_id}.jpg",
                "source_sha256": sha,
            }

    for path in list(out_dir.iterdir()):
        if path.is_file() and path.suffix in {".mp4", ".jpg"} and _TAKE_ID.match(path.stem) and path.stem not in live_ids:
            path.unlink()

    moves, effects = _pick_mappings(folders)
    # every take gets a mid-size and a sharper copy of its loop (the sharper one at the takes' real size), each cut again only
    # when the take changes (or the width it is cut at does), and each recorded with the width it really has
    for folder in folders:
        take_id = folder.name
        entry = takes_index.get(take_id)
        if not isinstance(entry, dict):
            continue
        before = prev_takes.get(take_id) if isinstance(prev_takes.get(take_id), dict) else {}
        larger = {
            name: _larger_copy(folder / "take.mp4", out_dir, take_id, name, width, crf, entry=entry, before=before, cut_at=cut_at)
            for name, width, crf in (("hd", PREVIEW_WIDTH_HD, 26), ("mid", PREVIEW_WIDTH_MID, 28))
        }
        takes_index[take_id] = {**entry, **larger}
    for name in ("hd", "mid"):  # the larger copies of a take that left go with it
        kept = {take_id for take_id, entry in takes_index.items() if isinstance(entry, dict) and name in entry}
        tail = f"-{name}"
        for path in list(out_dir.iterdir()):
            stem = path.stem[: -len(tail)] if path.stem.endswith(tail) else ""
            if path.is_file() and path.suffix in {".mp4", ".jpg"} and _TAKE_ID.match(stem) and stem not in kept:
                path.unlink()
    # every take's stills get a small copy for the cards that show them, cut again only when that still changes
    for folder in folders:
        take_id = folder.name
        entry = takes_index.get(take_id)
        if not isinstance(entry, dict):
            continue
        before = prev_takes.get(take_id) if isinstance(prev_takes.get(take_id), dict) else {}
        had, had_sha = before.get("stills") or {}, before.get("stills_sha") or {}
        stills: dict[str, str] = {}
        shas: dict[str, str] = {}
        for n, rel in enumerate(take_stills(folder), 1):
            name = f"{take_id}-s{n}.jpg"
            url = f"showcase/previews/{name}"
            sha = _still_sha(folder / rel)
            if not (cut_at.get("thumb") == THUMB_WIDTH and had.get(rel) == url and had_sha.get(rel) == sha and (out_dir / name).is_file()):
                cut_thumb(folder / rel, out_dir / name)
            stills[rel], shas[rel] = url, sha
        entry = {k: v for k, v in entry.items() if k not in ("stills", "stills_sha")}
        takes_index[take_id] = {**entry, "stills": stills, "stills_sha": shas} if stills else entry
    wanted = {Path(url).name for entry in takes_index.values() if isinstance(entry, dict) for url in (entry.get("stills") or {}).values()}
    for path in list(out_dir.iterdir()):
        if path.is_file() and _STILL_THUMB.match(path.name) and path.name not in wanted:
            path.unlink()
    index = {
        "version": 1,
        "seconds": PREVIEW_SECONDS,
        "widths": {"hd": PREVIEW_WIDTH_HD, "mid": PREVIEW_WIDTH_MID, "thumb": THUMB_WIDTH},  # for the builder only: the export writes an index of its own
        "takes": takes_index,
        "moves": moves,
        "effects": effects,
    }
    index_path.write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return index


def check_previews(
    takes_root: Path | str,
    out_dir: Path | str,
    index_path: Path | str,
) -> list[str]:
    """Return human-readable problems; empty when previews are up to date."""
    takes_root, out_dir, index_path = Path(takes_root), Path(out_dir), Path(index_path)
    problems: list[str] = []

    index: dict[str, Any] = {}
    if index_path.is_file():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                index = data
        except (OSError, ValueError):
            index = {}
    indexed_takes = index.get("takes") or {}
    if not isinstance(indexed_takes, dict):
        indexed_takes = {}

    folders = recorded_takes(takes_root)
    for folder in folders:
        take = _read_take(folder)
        if not take:
            continue
        take_id = take["id"]
        src = folder / "take.mp4"
        sha = _source_sha256(src)
        entry = indexed_takes.get(take_id)

        if entry is None:
            problems.append(f"take {take_id} is missing from the preview index")
            continue
        if not isinstance(entry, dict) or entry.get("source_sha256") != sha:
            problems.append(f"preview for {take_id} is stale (source changed)")
        if not (out_dir / f"{take_id}.mp4").is_file():
            problems.append(f"preview video for {take_id} is missing")
        if not (out_dir / f"{take_id}.jpg").is_file():
            problems.append(f"preview poster for {take_id} is missing")
        for name, label in (("hd", "sharper"), ("mid", "mid-size")):  # every take has both larger copies too, with the width each has
            held = entry.get(name) if isinstance(entry, dict) else None
            for kind in ("video", "poster"):
                named = held.get(kind) if isinstance(held, dict) else None
                if not named or not (out_dir / Path(str(named)).name).is_file():
                    problems.append(f"{label} preview {kind} for {take_id} is missing")
            if isinstance(held, dict) and not _is_width(held.get("width")):
                problems.append(f"{label} preview for {take_id} records no width")
        mapped = (entry.get("stills") or {}) if isinstance(entry, dict) else {}
        shas = (entry.get("stills_sha") or {}) if isinstance(entry, dict) else {}
        stills = take_stills(folder)
        missing = [rel for rel in stills if rel not in mapped or not (out_dir / Path(mapped[rel]).name).is_file()]
        if missing:
            problems.append(f"{len(missing)} still thumbnail(s) for {take_id} are missing")
        changed = [rel for rel in stills if rel in mapped and shas.get(rel) != _still_sha(folder / rel)]
        if changed:
            problems.append(f"{len(changed)} still thumbnail(s) for {take_id} are stale (the still changed)")

    widths = index.get("widths") if isinstance(index.get("widths"), dict) else {}
    if folders:
        for name, label, now in (("hd", "sharper copies", PREVIEW_WIDTH_HD), ("mid", "mid-size copies", PREVIEW_WIDTH_MID),
                                 ("thumb", "stills' copies", THUMB_WIDTH)):
            if widths.get(name) != now:
                problems.append(f"the {label} were cut at another width than the builder cuts now")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build preview loops for recorded takes.")
    parser.add_argument("--takes", default="openfield/web/showcase/takes",
                        help="folder of recorded takes (default: openfield/web/showcase/takes)")
    parser.add_argument("--out", default=None,
                        help="folder for preview mp4/jpg files (default: <takes>/../previews)")
    parser.add_argument("--index", default=None,
                        help="path to previews.json (default: <takes>/../previews.json)")
    parser.add_argument("--check", action="store_true",
                        help="report problems without writing anything")
    args = parser.parse_args(argv)

    takes_root = Path(args.takes)
    out_dir = Path(args.out) if args.out else takes_root.parent / "previews"
    index_path = Path(args.index) if args.index else takes_root.parent / "previews.json"

    if args.check:
        problems = check_previews(takes_root, out_dir, index_path)
        if problems:
            for problem in problems:
                print(problem, file=sys.stderr)
            return 1
        return 0

    build_previews(takes_root, out_dir, index_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
