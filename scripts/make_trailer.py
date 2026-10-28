"""Cut the Lobby's trailer from recorded takes: a widescreen clip of hard cuts, each with the take's own sound, for the
Lobby's screen. Every second of it is a recorded take; `art/trailer.json` says which take each second comes from
(the Lobby opens that take on a click) and the hash of every source, and `art/manifest.json` records the cut.

    python scripts/make_trailer.py                       # showcase/trailer.spec.json -> openfield/web/art/trailer*
    python scripts/make_trailer.py --check               # say what would be cut, write nothing

The spec lists segments: {"take": <id or showcase name>, "start": s, "seconds": s, "label": "Dolly in · Tomas"}.
A segment may carry a "title" ("First line / second line"): a headline in the site's own type laid over its first
seconds, the second line in the accent colour, rendered by scripts/trailer_titles.mjs. The spec's "card" is the end
card over the last seconds: {"title", "tagline", "statement" ("first / second"), "mono", "seconds"}.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openfield.engine import video  # noqa: E402

SPEC = ROOT / "showcase" / "trailer.spec.json"
TAKES = ROOT / "openfield" / "web" / "showcase" / "takes"
ART = ROOT / "openfield" / "web" / "art"
SIZES = {"trailer.mp4": (1024, 564, 28), "trailer-640.mp4": (640, 352, 30), "trailer-hd.mp4": (1280, 704, 27)}  # file -> (width, height, crf)
TITLE_IN, TITLE_HOLD, TITLE_FADE = 0.3, 2.6, 0.3  # a title comes 0.3 s into its segment, stays at most 2.6 s, fades 0.3 s
STALE = {"trailer-360.mp4"}  # the square cut of the old feature one-sheet
FADE = 0.08  # seconds of sound fade at each cut, so no cut clicks


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve(take: str, takes: Path) -> Path:
    """A take folder by id, or by the showcase name a recorded take carries."""
    direct = takes / take
    if (direct / "take.mp4").is_file():
        return direct
    for take_json in takes.glob("*/take.json"):
        data = json.loads(take_json.read_text(encoding="utf-8"))
        if data.get("showcase_name") == take and (take_json.parent / "take.mp4").is_file():
            return take_json.parent
    raise SystemExit(f"no recorded take {take!r} in {takes}")


def cut_segment(src: Path, start: float, seconds: float, size: tuple[int, int], out: Path) -> None:
    """One segment: trimmed, scaled to fill the frame (a take of another shape is centre-cropped), 24 fps, with its sound
    faded in and out (or silence)."""
    info = video.probe(src)
    fade_out = max(0.0, seconds - FADE)
    w, h = size
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h},fps=24,setsar=1,format=yuv420p"
    if info.has_audio:
        args = ["-ss", f"{start:.3f}", "-t", f"{seconds:.3f}", "-i", str(src), "-vf", vf,
                "-af", f"aresample=48000,aformat=channel_layouts=stereo,afade=t=in:d={FADE},afade=t=out:st={fade_out:.3f}:d={FADE}"]
    else:  # a silent take gets silence of its own length, so every segment has the same streams
        args = ["-ss", f"{start:.3f}", "-t", f"{seconds:.3f}", "-i", str(src), "-f", "lavfi", "-t", f"{seconds:.3f}",
                "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v", "-map", "1:a", "-vf", vf]
    cmd = [video.ffmpeg_exe(), "-y", "-v", "error", *args, "-c:v", "libx264", "-preset", "medium", "-crf", "16",
           "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)]
    subprocess.run(cmd, check=True)


def render_titles(spec_path: Path, out: Path) -> None:
    """The title cards as transparent PNGs at 1280 by 704 (the takes' frame), set in the site's own type by a browser."""
    subprocess.run(["node", str(ROOT / "scripts" / "trailer_titles.mjs"), "--spec", str(spec_path), "--out", str(out),
                    "--width", "1280", "--height", "704"], check=True)


def finish(level: Path, final: Path, size: tuple[int, int], crf: int, overlays: list[dict]) -> None:
    """The last pass of one size: the levelled cut, the title cards faded over it at their times, encoded for the web."""
    w, h = size
    cmd = [video.ffmpeg_exe(), "-y", "-v", "error", "-i", str(level)]
    chain, last = [], "0:v"
    for i, o in enumerate(overlays, start=1):
        cmd += ["-loop", "1", "-t", f"{o['seconds']:.3f}", "-i", str(o["png"])]
        fade_out = f",fade=t=out:st={o['seconds'] - TITLE_FADE:.3f}:d={TITLE_FADE}:alpha=1" if o.get("fade_out", True) else ""
        chain.append(f"[{i}:v]scale={w}:{h}:flags=lanczos,format=rgba,fade=t=in:st=0:d={TITLE_FADE}:alpha=1{fade_out},"
                     f"setpts=PTS-STARTPTS+{o['at']:.3f}/TB[t{i}]")
        chain.append(f"[{last}][t{i}]overlay=0:0:eof_action=pass:enable='between(t,{o['at']:.3f},{o['at'] + o['seconds']:.3f})'[v{i}]")
        last = f"v{i}"
    if chain:
        cmd += ["-filter_complex", ";".join(chain), "-map", f"[{last}]", "-map", "0:a"]
    cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
            "-movflags", "+faststart", str(final)]
    subprocess.run(cmd, check=True)


def build(spec_path: Path, takes: Path, art: Path, check: bool = False) -> dict:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    segments, titles, t = [], [], 0.0
    for i, item in enumerate(spec["segments"]):
        folder = resolve(item["take"], takes)
        take = json.loads((folder / "take.json").read_text(encoding="utf-8"))
        seconds = float(item["seconds"])
        segments.append({"start": round(t, 3), "end": round(t + seconds, 3), "take": take["id"], "label": item["label"],
                         "from": float(item.get("start", 0.0)), "source": folder / "take.mp4"})
        if item.get("title"):
            hold = min(TITLE_HOLD, max(1.0, seconds - TITLE_IN - 0.3))
            titles.append({"at": round(t + TITLE_IN, 3), "seconds": round(hold, 3), "text": item["title"], "png": f"title-{i:02d}.png"})
        t += seconds
    card = spec.get("card")
    if card:
        hold = float(card.get("seconds", 1.6))
        card_at = round(t - hold, 3)
        for o in titles:  # a title never runs into the card: it ends 0.2 s before
            o["seconds"] = round(min(o["seconds"], card_at - 0.2 - o["at"]), 3)
        titles.append({"at": card_at, "seconds": round(hold, 3), "text": card.get("statement", ""), "png": "card.png",
                       "fade_out": False, "card": True})
    if check:
        for s in segments:
            print(f"{s['start']:6.2f}-{s['end']:6.2f}  {s['take']}  {s['label']}")
        for o in titles:
            print(f"{o['at']:6.2f}-{o['at'] + o['seconds']:6.2f}  {'card ' if o.get('card') else 'title'}  {o['text']}")
        return {"seconds": round(t, 3), "segments": len(segments), "titles": len(titles)}
    made: dict[str, Path] = {}
    with tempfile.TemporaryDirectory(prefix="trailer-") as tmp:
        work = Path(tmp)
        if titles:
            render_titles(spec_path, work / "titles")
            for o in titles:
                o["png"] = work / "titles" / o["png"]
                if not o["png"].is_file():
                    raise SystemExit(f"no title card rendered for {o['text']!r}")
        for name, (width, height, crf) in SIZES.items():
            side = width
            parts = []
            for i, s in enumerate(segments):
                part = work / f"{side}-{i:02d}.mp4"
                cut_segment(s["source"], s["from"], s["end"] - s["start"], (width, height), part)
                parts.append(part)
            listing = work / f"{side}.txt"
            listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
            joined = work / f"{side}-joined.mp4"
            subprocess.run([video.ffmpeg_exe(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                            "-c", "copy", str(joined)], check=True)
            level = work / f"{side}-level.mp4"
            video.loudnorm_two_pass(joined, level, lufs=-16.0)
            final = art / name
            finish(level, final, (width, height), crf, titles)
            made[name] = final
        poster = work / "poster.png"
        first = segments[0]
        video.extract_frame(made["trailer.mp4"], poster, (first["start"] + first["end"]) / 2)
        from PIL import Image  # noqa: PLC0415

        with Image.open(poster) as img:
            img.convert("RGB").save(art / "trailer.webp", "WEBP", quality=82, method=6)
    index = {
        "version": 2,
        "what": "The Lobby's trailer: hard cuts of recorded takes, each with its own sound, levelled to -16 LUFS, with "
                "title cards in the site's type over some cuts. Every segment names its take; the Lobby opens it on a click.",
        "seconds": round(t, 3),
        "files": {"video": "trailer.mp4", "small": "trailer-640.mp4", "hd": "trailer-hd.mp4", "poster": "trailer.webp"},
        "titles": [{"at": o["at"], "seconds": o["seconds"], "text": o["text"], **({"card": True} if o.get("card") else {})}
                   for o in titles],
        "segments": [{k: v for k, v in s.items() if k != "source"} for s in segments],
        "made_from": [{"take": s["take"], "take_mp4_sha256": sha256(s["source"])} for s in segments],
    }
    (art / "trailer.json").write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    manifest_path = art / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = [f for f in manifest["files"] if f.get("file") not in {*SIZES, *STALE, "trailer.webp"}]
    for name in STALE:
        (art / name).unlink(missing_ok=True)
    for name in [*SIZES, "trailer.webp"]:
        path = art / name
        if name.endswith(".mp4"):
            info = video.probe(path)
            width, height = info.width, info.height
        else:
            from PIL import Image  # noqa: PLC0415

            with Image.open(path) as img:
                width, height = img.size
        manifest["files"].append({"file": name, "kind": "cut" if name.endswith(".mp4") else "still", "width": width, "height": height,
                                  "bytes": path.stat().st_size, "sha256": sha256(path), "cropped": "the takes' own frame",
                                  "made_from": {"kind": "cut", "how": "scripts/make_trailer.py from recorded takes (art/trailer.json)",
                                                "takes": [s["take"] for s in segments]}})
    manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return {"seconds": round(t, 3), "segments": len(segments), **{k: v.stat().st_size for k, v in made.items()}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--spec", default=str(SPEC))
    parser.add_argument("--takes", default=str(TAKES))
    parser.add_argument("--art", default=str(ART))
    parser.add_argument("--check", action="store_true", help="say what would be cut, write nothing")
    args = parser.parse_args(argv)
    if not shutil.which(video.ffmpeg_exe()) and not Path(video.ffmpeg_exe()).is_file():
        print("ffmpeg is needed")
        return 2
    print(json.dumps(build(Path(args.spec), Path(args.takes), Path(args.art), check=args.check)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
