#!/usr/bin/env python3
"""Blind judging sheet for the keyframing experiment, and the reveal that applies the rule.

    python scripts/judge_experiment.py sheet --run data-showcase/experiment --out data-judge
    python scripts/judge_experiment.py reveal --out data-judge --verdicts data-judge/verdicts.csv

`showcase/experiment-keyframing.json` renders five camera moves with two characters, each twice:
a `X-keyframed` take (approved anchor stills) and its `X-prompt` twin (one still plus a camera
instruction). `sheet` lays the middle frame of both videos side by side, labelled only A and B,
and shuffles which side is keyframed. `key.json` remembers the mapping; `verdicts.csv` is the
empty sheet two people fill in. `reveal` joins their verdicts with the key and the identity
scores, applies the validation rule, and prints the `rig.VALIDATED` literal.

A take is placed in the run folder either under its take id (the real showcase layout) or under
its spec name, so hand-made run folders work too. Its video is `<folder>/take.mp4`; identity
stages live in `<folder>/take.json` under `identity` (receipts keep them under
`identity.reports` as a fallback).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

KEYFRAMED_SUFFIX = "-keyframed"
PROMPT_SUFFIX = "-prompt"
VERDICT_COLUMNS = ("pair", "viewer", "reads_as_move", "no_seam", "better_side")

# The sheet is one row per pair: a left label column, then two equally wide frames. Frames keep
# their aspect ratio and are letterboxed into a cell of this width.
SHEET_MARGIN = 16
SHEET_LEFT = 280
SHEET_FRAME_WIDTH = 480
SHEET_GAP = 16
SHEET_LABEL_HEIGHT = 26

SIDE_A = "A"
SIDE_B = "B"


# -- small file helpers -------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )


def _take_dir(run: Path, name: str, take_id: str | None = None) -> Path | None:
    """Find a take's folder by id, by spec name, or by the showcase_name inside take.json."""
    if take_id:
        candidate = run / take_id
        if candidate.is_dir():
            return candidate
    candidate = run / name
    if candidate.is_dir():
        return candidate
    for folder in sorted(run.iterdir()):
        if not folder.is_dir():
            continue
        take = _read_json(folder / "take.json")
        if take and take.get("showcase_name") == name:
            return folder
    return None


def load_takes(run: Path) -> dict[str, dict[str, Any]]:
    """Map spec take name -> folder/status, reading report.json and then any stray folders."""
    takes: dict[str, dict[str, Any]] = {}
    report = _read_json(run / "report.json") or {}
    for item in report.get("takes", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        takes[name] = {
            "name": name,
            "folder": _take_dir(run, name, item.get("take_id")),
            "status": item.get("status"),
        }
    for folder in sorted(run.iterdir()):
        if not folder.is_dir():
            continue
        take = _read_json(folder / "take.json") or {}
        name = take.get("showcase_name")
        if not name or name in takes:
            continue
        if (folder / "take.mp4").is_file():
            takes[name] = {"name": name, "folder": folder, "status": take.get("status")}
    return takes


def _video_of(record: dict[str, Any]) -> tuple[Path | None, str]:
    folder = record.get("folder")
    if folder is None:
        return None, "no take folder"
    video_path = folder / "take.mp4"
    if not video_path.is_file():
        return None, f"no take.mp4 in {folder.name}"
    return video_path, ""


def _move_name(base: str, key_folder: Path | None, prompt_folder: Path | None) -> str:
    """The rig move id from a take recipe, with a suffix match against the 49-move table."""
    for folder in (key_folder, prompt_folder):
        take = _read_json(folder / "take.json") if folder is not None else None
        recipe = (take or {}).get("recipe") or {}
        rig = recipe.get("rig") or {}
        move = rig.get("movement") or recipe.get("move")
        if move:
            return str(move)
    from openfield.engine.rig import MOVES

    dashed = base.replace("-", "_")
    for move_id in sorted(MOVES, key=len, reverse=True):
        if dashed.endswith(move_id):
            return move_id
    return base.rsplit("-", 1)[-1]


# -- sheet --------------------------------------------------------------------------------------


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        try:
            return ImageFont.load_default(size=size)
        except TypeError:  # Pillow before 10.1 has only one default size
            return ImageFont.load_default()


def _fit(image: Image.Image, width: int, height: int) -> Image.Image:
    """Scale to fit without cropping, then centre on a dark cell."""
    scaled = image.copy()
    scaled.thumbnail((width, height), Image.Resampling.LANCZOS)
    cell = Image.new("RGB", (width, height), (32, 32, 32))
    cell.paste(scaled, ((width - scaled.width) // 2, (height - scaled.height) // 2))
    return cell


def _draw_sheet(rows: list[dict[str, Any]], path: Path) -> None:
    heights = [
        max(round(image.height * SHEET_FRAME_WIDTH / image.width) for image in row["images"])
        for row in rows
    ]
    width = 2 * SHEET_MARGIN + SHEET_LEFT + 2 * SHEET_FRAME_WIDTH + SHEET_GAP
    height = (
        2 * SHEET_MARGIN
        + sum(SHEET_LABEL_HEIGHT + row_height + SHEET_GAP for row_height in heights)
        - SHEET_GAP
    )
    sheet = Image.new("RGB", (width, height), (246, 246, 244))
    draw = ImageDraw.Draw(sheet)
    pair_font = _font(18, bold=True)
    move_font = _font(14)
    side_font = _font(17, bold=True)

    y = SHEET_MARGIN
    for row, row_height in zip(rows, heights, strict=True):
        draw.text((SHEET_MARGIN, y + 3), row["base"], fill=(20, 20, 20), font=pair_font)
        draw.text((SHEET_MARGIN, y + 25), row["move"], fill=(88, 88, 88), font=move_font)
        for index, (label, image) in enumerate(zip((SIDE_A, SIDE_B), row["images"], strict=True)):
            x = SHEET_MARGIN + SHEET_LEFT + index * (SHEET_FRAME_WIDTH + SHEET_GAP)
            draw.rectangle(
                [x, y, x + SHEET_FRAME_WIDTH, y + SHEET_LABEL_HEIGHT - 2], fill=(228, 228, 224)
            )
            bounds = draw.textbbox((0, 0), label, font=side_font)
            draw.text(
                (x + (SHEET_FRAME_WIDTH - (bounds[2] - bounds[0])) / 2, y + 2),
                label,
                fill=(20, 20, 20),
                font=side_font,
            )
            sheet.paste(_fit(image, SHEET_FRAME_WIDTH, row_height), (x, y + SHEET_LABEL_HEIGHT))
            draw.rectangle(
                [x, y + SHEET_LABEL_HEIGHT, x + SHEET_FRAME_WIDTH, y + SHEET_LABEL_HEIGHT + row_height],
                outline=(80, 80, 80),
            )
        y += SHEET_LABEL_HEIGHT + row_height + SHEET_GAP

    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path, format="PNG")


def make_sheet(run: Path, out: Path, seed: int) -> int:
    """Extract each pair's middle frames, lay them out blind, and write key.json + verdicts.csv."""
    from openfield.engine import video

    if not run.is_dir():
        print(f"No such run folder: {run}", file=sys.stderr)
        return 1
    takes = load_takes(run)
    pairs: list[dict[str, Any]] = []
    skipped: list[tuple[str, str]] = []

    for name in sorted(takes):
        if not name.endswith(KEYFRAMED_SUFFIX):
            continue
        base = name[: -len(KEYFRAMED_SUFFIX)]
        twin = base + PROMPT_SUFFIX
        if twin not in takes:
            skipped.append((base, f"missing prompt twin {twin!r}"))
            continue
        key_video, key_why = _video_of(takes[name])
        prompt_video, prompt_why = _video_of(takes[twin])
        if key_video is None:
            skipped.append((base, f"{name}: {key_why}"))
            continue
        if prompt_video is None:
            skipped.append((base, f"{twin}: {prompt_why}"))
            continue
        pairs.append(
            {
                "base": base,
                "key_name": name,
                "prompt_name": twin,
                "key_folder": takes[name]["folder"],
                "prompt_folder": takes[twin]["folder"],
                "key_video": key_video,
                "prompt_video": prompt_video,
            }
        )

    for name in sorted(takes):
        if not name.endswith(PROMPT_SUFFIX):
            continue
        base = name[: -len(PROMPT_SUFFIX)]
        if base + KEYFRAMED_SUFFIX not in takes:
            skipped.append((base, f"missing keyframed twin {base + KEYFRAMED_SUFFIX!r}"))

    rows: list[dict[str, Any]] = []
    key_rows: list[dict[str, Any]] = []
    rng = random.Random(seed)
    with tempfile.TemporaryDirectory(prefix="judge-frames-") as scratch:
        for pair in pairs:
            base = pair["base"]
            frames: dict[str, Image.Image] = {}
            try:
                for side, source in (("key", pair["key_video"]), ("prompt", pair["prompt_video"])):
                    png = Path(scratch) / f"{len(rows):02d}-{side}.png"
                    video.extract_frame(source, png, "mid")
                    with Image.open(png) as image:
                        image.load()
                        frames[side] = image.convert("RGB")
            except (OSError, ValueError, video.VideoError) as exc:
                skipped.append((base, f"cannot extract a middle frame: {exc}"))
                continue

            key_on_the_left = rng.random() < 0.5
            key_side = SIDE_A if key_on_the_left else SIDE_B
            images = (
                [frames["key"], frames["prompt"]]
                if key_on_the_left
                else [frames["prompt"], frames["key"]]
            )
            rows.append(
                {
                    "base": base,
                    "move": _move_name(base, pair["key_folder"], pair["prompt_folder"]),
                    "images": images,
                }
            )
            key_rows.append(
                {
                    "row": len(key_rows),
                    "pair": base,
                    "move": rows[-1]["move"],
                    "keyframed_side": key_side,
                    "keyframed_take": pair["key_name"],
                    "prompt_take": pair["prompt_name"],
                    "keyframed_dir": pair["key_folder"].relative_to(run).as_posix(),
                    "prompt_dir": pair["prompt_folder"].relative_to(run).as_posix(),
                }
            )

    if not rows:
        print(f"No complete keyframed/prompt pairs in {run}.", file=sys.stderr)
        for base, reason in skipped:
            print(f"  skipped {base}: {reason}", file=sys.stderr)
        return 1

    _draw_sheet(rows, out / "sheet.png")
    _write_json(out / "key.json", {"seed": seed, "run": str(run.resolve()), "rows": key_rows})
    verdicts = out / "verdicts.csv"
    with verdicts.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerow(VERDICT_COLUMNS)

    print(f"Laid out {len(rows)} pair(s) in {out / 'sheet.png'} (seed {seed}).")
    print(f"Blind key: {out / 'key.json'}; fill in: {verdicts}")
    for base, reason in skipped:
        print(f"Skipped {base}: {reason}")
    return 0


# -- reveal -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    pair: str
    viewer: str
    reads_as_move: str
    no_seam: str
    better_side: str


def _read_verdicts(path: Path) -> list[Verdict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in VERDICT_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path.name} is missing column(s): {', '.join(missing)}")
        verdicts = []
        for row in reader:
            values = tuple(str(row.get(column) or "").strip() for column in VERDICT_COLUMNS)
            if any(values):
                verdicts.append(Verdict(*values))
    return verdicts


def _lowest_score(identity: Any) -> float | None:
    """Lowest numeric score among per-stage identity reports; None when nothing was measured."""
    if not isinstance(identity, dict):
        return None
    reports = identity.get("reports")
    stages = reports if isinstance(reports, dict) else identity
    scores = []
    for value in stages.values():
        if not isinstance(value, dict):
            continue
        score = value.get("score")
        if isinstance(score, (int, float)) and not isinstance(score, bool) and score == score:
            scores.append(float(score))
    return min(scores) if scores else None


def take_identity_score(folder: Path | None) -> float | None:
    """The take's lowest identity stage score, from take.json or the receipt's nested reports."""
    if folder is None:
        return None
    take = _read_json(folder / "take.json") or {}
    score = _lowest_score(take.get("identity"))
    if score is not None:
        return score
    receipt = _read_json(folder / "receipt.json") or {}
    return _lowest_score(receipt.get("identity"))


def _yes_for_side(value: str, keyframed_side: str) -> bool:
    """A yes, or a side letter naming the keyframed side (both/AB also counts)."""
    answer = value.strip().lower()
    if answer in {"yes", "y", "true", "1", "both", "ab", "ba"}:
        return True
    if answer in {"a", "b"}:
        return answer.upper() == keyframed_side
    return False


def _chose_side(value: str, keyframed_side: str) -> bool:
    answer = value.strip().upper()
    return answer == keyframed_side


def _show_score(score: float | None) -> str:
    return "n/a" if score is None else f"{score:.3f}"


def reveal(out: Path, verdicts_path: Path, identity_tolerance: float = 0.05) -> int:
    """Join verdicts, the blind key and identity scores; print the rule's result per move."""
    key = _read_json(out / "key.json")
    if key is None:
        print(f"No key.json in {out}; run the sheet step first.", file=sys.stderr)
        return 1
    try:
        verdicts = _read_verdicts(verdicts_path)
    except (OSError, ValueError) as exc:
        print(f"Cannot read verdicts: {exc}", file=sys.stderr)
        return 1

    run = Path(key.get("run") or out)
    key_rows = [row for row in key.get("rows", []) if isinstance(row, dict)]
    by_pair = {row.get("pair"): row for row in key_rows}
    unmatched = {verdict.pair for verdict in verdicts} - set(by_pair)
    if unmatched:
        print(
            f"Warning: ignoring {len(unmatched)} pair(s) not in key.json: "
            + ", ".join(sorted(str(pair) for pair in unmatched)),
            file=sys.stderr,
        )

    moves: dict[str, list[tuple[dict[str, Any], list[Verdict]]]] = {}
    for row in key_rows:
        pair = str(row.get("pair") or "")
        move = str(row.get("move") or pair)
        matches = [verdict for verdict in verdicts if verdict.pair == pair]
        moves.setdefault(move, []).append((row, matches))

    winners: list[str] = []
    for move in sorted(moves):
        pairs = moves[move]
        judgements: list[tuple[dict[str, Any], Verdict]] = []
        identity_notes: list[str] = []
        identity_ok = True
        for row, matches in pairs:
            judgements.extend((row, verdict) for verdict in matches)
            key_folder = run / str(row.get("keyframed_dir") or row.get("keyframed_take") or "")
            prompt_folder = run / str(row.get("prompt_dir") or row.get("prompt_take") or "")
            key_score = take_identity_score(key_folder)
            prompt_score = take_identity_score(prompt_folder)
            ok = (key_score is None and prompt_score is None) or (
                key_score is not None
                and prompt_score is not None
                and key_score + identity_tolerance >= prompt_score  # a gap inside the face check's noise is not a loss
            )
            identity_ok = identity_ok and ok
            identity_notes.append(
                f"{row.get('pair')} {_show_score(key_score)} vs {_show_score(prompt_score)}"
            )

        total = len(judgements)
        reads_ok = total > 0 and all(
            _yes_for_side(verdict.reads_as_move, str(row.get("keyframed_side")))
            for row, verdict in judgements
        )
        seam_ok = total > 0 and all(
            _yes_for_side(verdict.no_seam, str(row.get("keyframed_side")))
            for row, verdict in judgements
        )
        chosen = sum(
            _chose_side(verdict.better_side, str(row.get("keyframed_side")))
            for row, verdict in judgements
        )
        majority_ok = total > 0 and chosen * 2 > total
        validated = reads_ok and seam_ok and identity_ok and majority_ok

        if validated:
            winners.append(move)
            print(
                f"{move}: validated ({chosen}/{total} chose the keyframed side; "
                f"identity {', '.join(identity_notes)})"
            )
            continue

        problems = []
        if total == 0:
            problems.append("no viewer verdicts")
        if total and not reads_ok:
            problems.append("reads_as_move not yes for the keyframed side")
        if total and not seam_ok:
            problems.append("no_seam not yes for the keyframed side")
        if not identity_ok:
            problems.append(f"identity below the prompt twin ({', '.join(identity_notes)})")
        if total and not majority_ok:
            problems.append(f"only {chosen}/{total} chose the keyframed side")
        print(f"{move}: not validated ({'; '.join(problems)})")

    if winners:
        literal = "frozenset({" + ", ".join(json.dumps(name) for name in winners) + "})"
    else:
        literal = "frozenset()"
    print(f"VALIDATED = {literal}")
    return 0


# -- command line -------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="judge_experiment.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True)

    sheet_parser = commands.add_parser("sheet", help="lay out the blind A/B judging sheet")
    sheet_parser.add_argument("--run", required=True, type=Path, help="showcase run folder")
    sheet_parser.add_argument("--out", required=True, type=Path, help="where the sheet goes")
    sheet_parser.add_argument("--seed", type=int, default=0, help="shuffle seed (default: 0)")

    reveal_parser = commands.add_parser("reveal", help="apply the written rule to filled-in verdicts")
    reveal_parser.add_argument("--out", required=True, type=Path, help="folder holding key.json")
    reveal_parser.add_argument("--verdicts", required=True, type=Path, help="filled-in verdicts CSV")
    reveal_parser.add_argument("--identity-tolerance", type=float, default=0.05, help="how far below its prompt-only twin a keyframed take's identity score may fall and still count as kept (default 0.05: the scores vary by about that much between runs)")

    args = parser.parse_args(argv)
    if args.command == "sheet":
        return make_sheet(args.run, args.out, args.seed)
    return reveal(args.out, args.verdicts, args.identity_tolerance)


if __name__ == "__main__":
    sys.exit(main())
