"""Build the hosted Replay: the web app plus recorded takes as plain static files.

    <out>/index.html, js/, ...                       the app (openfield/web, minus showcase/)
    <out>/static/manifest.json                       what /api/status and /api/moves answer, the takes, and the ids of
                                                     the recorded ones (the page builds /api/replay/recorded from them)
    <out>/showcase/takes/<id>/take.json              the same ledger folder a local run keeps,
                                                     trimmed to what the viewer needs:
        receipt.json, receipt.view.json, events.jsonl, take.mp4, poster.png, inputs/*,
        runs/*/<stills>, workflows.zip, sdk-snippet.py

Nothing here can render. The app finds `static/manifest.json`, switches to its client-only API, and
plays the recorded events back; any edit is refused with an explanation, exactly as Replay does.
Take folders keep the layout the live server serves under /showcase/takes/<id>/, so media URLs
resolve the same way in both modes.
"""
from __future__ import annotations

import html
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import __version__, share
from .backends.replay import ReplayBackend, hero_reel, hero_take, recorded_gpu
from .config import Settings
from .engine import rig as rigs
from .engine.audit import POLICY

MANIFEST = Path("static") / "manifest.json"
SITE_JSON = Path("static") / "site.json"
MEDIA_BASE = "showcase/takes/{id}"
STILL_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
WEB_IGNORE = ("showcase", "__pycache__", "node_modules", "package.json", "*.map")
CARD_SIZE = (1200, 630)
CARD_QUALITY = 82
FALLBACK_DESCRIPTION = (
    "OpenField Studio: direct shots with a virtual camera, re-shoot a clip with a new character, "
    "and keep every take with a verifiable receipt. Open weights only.")
FALLBACK_MODELS = "LTX 2.5 and Qwen-Image 2.1"
KIND_LABELS = {
    "reshoot": "Re-shoot", "transition": "Transition", "shots": "Shots", "edit": "Edit",
    "extend": "Extend", "upscale": "Upscale", "export": "Export",
}
MODEL_NAMES = {
    "ltx-2.5": "LTX 2.5", "qwen-image-2.1": "Qwen-Image 2.1", "wan-animate-2": "Wan Animate 2",
}
FONT_DIR = Path(__file__).resolve().parent / "web" / "fonts"
# what the page reads of a face-check report (lib/identity.js): the manifest lists the takes with these only; the whole report
# stays in each take's take.json and receipt.json
IDENTITY_KEYS = ("status", "score", "threshold", "retried")
# the loops a take's previews come in (build_previews writes them): the plain one, the mid-size one and the sharper one, each
# with its poster
PREVIEW_SUFFIXES = (".mp4", ".jpg", "-mid.mp4", "-mid.jpg", "-hd.mp4", "-hd.jpg")
CAST_COPY_WIDTH = 768  # a Cast card is at most 480 CSS px wide: this copy of its 1024 px portrait is sharp on a 2x screen and weighs a tenth of the PNG


class StaticExportError(ValueError):
    pass


def slim_identity(identity: Any) -> Any:
    """A take's face-check reports (stage -> report) cut to the keys the page reads. Anything that is not a map is left as it is."""
    if not isinstance(identity, dict):
        return identity
    return {stage: ({key: report[key] for key in IDENTITY_KEYS if key in report} if isinstance(report, dict) else report)
            for stage, report in identity.items()}


def recorded_takes(root: Path) -> list[Path]:
    """Folders of finished, really-rendered takes, newest first."""
    folders = []
    for take_json in Path(root).glob("*/take.json"):
        folder = take_json.parent
        try:
            take = json.loads(take_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (take.get("status") == "succeeded" and not take.get("replay")
                and (folder / "receipt.json").is_file() and (folder / "take.mp4").is_file()):
            folders.append((take.get("created_at") or "", folder))
    return [folder for _, folder in sorted(folders, key=lambda pair: pair[0], reverse=True)]


def served_files(folder: Path) -> list[Path]:
    """Files of a take the hosted copy serves, relative to the folder.

    Top-level files and inputs/ are kept; of the per-step run folders only the stills (anchors,
    previews) are kept, because their videos are intermediate and the workflows travel in the zip.
    """
    keep = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.name.endswith(".tmp"):
            continue
        rel = path.relative_to(folder)
        top = rel.parts[0]
        if path.name.startswith("identity_frame"):
            continue  # the check's frames: the video's own first, middle and last, hashed by no receipt
        if len(rel.parts) == 1 or top == "inputs" or (
                top == "runs" and len(rel.parts) == 3 and path.suffix.lower() in STILL_SUFFIXES):
            keep.append(rel)
    return keep


def _write_take(folder: Path, dest: Path) -> int:
    total = 0
    for rel in served_files(folder):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(folder / rel, target)
        total += target.stat().st_size
    view = dest / "receipt.view.json"
    view.write_text(json.dumps(share.read_receipt_view(folder / "receipt.json"), indent=2,
                               ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    archive = dest / "workflows.zip"
    archive.write_bytes(share.workflows_zip(folder, include_inputs=False))  # the stills are served beside it
    total += view.stat().st_size + archive.stat().st_size
    snippet = share.take_snippet(folder)
    if snippet is not None:
        (dest / "sdk-snippet.py").write_text(snippet, encoding="utf-8", newline="\n")
    return total


def _is_our_export(folder: Path) -> bool:
    """True only for a folder this tool wrote: its manifest says so, not merely that a file by that name exists
    (another web app has a static/manifest.json too, and this folder may hold someone's work)."""
    try:
        manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(manifest, dict) and manifest.get("app") == "openfield-studio" and manifest.get("static") is True


def _prepare_out(out_dir: Path, sources: list[Path]) -> None:
    out_dir = out_dir.resolve()
    for source in sources:
        resolved = source.resolve()
        if out_dir == resolved or resolved in out_dir.parents or out_dir in resolved.parents:
            raise StaticExportError(f"the output folder {out_dir} overlaps {resolved}")
    if out_dir.exists():
        if not out_dir.is_dir():
            raise StaticExportError(f"{out_dir} is not a folder")
        if any(out_dir.iterdir()):
            if not _is_our_export(out_dir):
                raise StaticExportError(
                    f"{out_dir} is not empty and is not a previous OpenField static export; "
                    "choose an empty folder")
            shutil.rmtree(out_dir)  # only ever a folder we exported before
    out_dir.mkdir(parents=True, exist_ok=True)


def build_status(count: int, hero: str | None = None, reel: list[str] | None = None,
                 gpu: dict[str, Any] | None = None) -> dict[str, Any]:
    label = "Replay (hosted)"
    return {
        "app": "openfield-studio", "version": __version__, "policy": POLICY, "static": True,
        "backend": {
            "kind": "replay", "label": label, "locked": True, "sdk_configured": False,
            "configured": False, "source": None, "target": None, "comfy_url": False,
            "health": {"ok": True, "kind": "replay", "label": label,
                       "detail": f"{count} recorded take(s). Install OpenField to render new ones."},
        },
        "face_check": {"available": False, "reason": "The hosted copy only plays recorded takes."},
        "recorded_takes": count,
        "hero_take": hero,
        "hero_reel": list(reel or []),
        "gpu": gpu,  # the GPU time the exported takes' receipts list, summed
    }


def shipped_casts(cast_root: Path) -> list[tuple[dict[str, Any], Path]]:
    """The cast members bundled with the showcase: each a (cast.json record, folder) pair, by name."""
    found = []
    for record in sorted(Path(cast_root).glob("*/cast.json")):
        try:
            data = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("id") and data.get("refs"):
            found.append((data, record.parent))
    return sorted(found, key=lambda pair: str(pair[0].get("name", "")))


def _small_cast_copy(source: Path, dest: Path) -> int | None:
    """A JPEG copy of a reference portrait `CAST_COPY_WIDTH` px wide; its width, or None when the portrait is no wider than that
    already or cannot be read as a picture (then the card keeps the original alone)."""
    try:
        with Image.open(source) as opened:
            if opened.width <= CAST_COPY_WIDTH:
                return None
            picture = opened.convert("RGB")
    except (OSError, ValueError):
        return None
    height = max(1, round(picture.height * CAST_COPY_WIDTH / picture.width))
    picture.resize((CAST_COPY_WIDTH, height), Image.Resampling.LANCZOS).save(
        dest, "JPEG", quality=84, optimize=True, progressive=True)
    return CAST_COPY_WIDTH


def _write_cast(data: dict[str, Any], folder: Path, target: Path) -> tuple[int, dict[str, Any]]:
    """Copy a cast member's reference images next to the site (the page reads them from showcase/cast/<id>/<file>), each with a
    smaller JPEG beside it. Returns the bytes written and the member's record, a reference that has a smaller copy naming it
    as `small: {file, width}`."""
    target.mkdir(parents=True, exist_ok=True)
    size, refs = 0, []
    for ref in data.get("refs", []):
        source = folder / "refs" / str(ref.get("file", ""))
        if source.is_file():
            shutil.copy2(source, target / source.name)
            size += source.stat().st_size
            small = target / f"{source.stem}-{CAST_COPY_WIDTH}.jpg"
            width = _small_cast_copy(source, small)
            if width:
                size += small.stat().st_size
                ref = dict(ref, small={"file": small.name, "width": width})
        refs.append(ref)
    return size, dict(data, refs=refs)


def _normalise_url(url: str | None) -> str | None:
    """A site URL that ends with exactly one slash, or None when none was given."""
    if url is None:
        return None
    url = str(url).strip()
    return url.rstrip("/") + "/" if url else None


def _meta(attribute: str, name: str, value: str) -> str:
    return (f'<meta {attribute}="{html.escape(name, quote=True)}" '
            f'content="{html.escape(value, quote=True)}">')


def _page_description(document: str) -> str:
    match = re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']*)', document,
                      re.IGNORECASE)
    return html.unescape(match.group(1)) if match else FALLBACK_DESCRIPTION


def _social_tags(prefix: str, description: str) -> list[str]:
    """Open Graph and Twitter tags for the site's own page, every value escaped."""
    return [
        _meta("property", "og:site_name", "OpenField Studio"),
        _meta("property", "og:type", "website"),
        _meta("property", "og:title", "OpenField Studio"),
        _meta("property", "og:description", description),
        _meta("property", "og:url", prefix),
        _meta("property", "og:image", prefix + "static/card.jpg"),
        _meta("property", "og:image:width", str(CARD_SIZE[0])),
        _meta("property", "og:image:height", str(CARD_SIZE[1])),
        _meta("property", "og:image:alt", "OpenField Studio: a film studio on open weights"),
        _meta("name", "twitter:card", "summary_large_image"),
        _meta("name", "twitter:title", "OpenField Studio"),
        _meta("name", "twitter:description", description),
        _meta("name", "twitter:image", prefix + "static/card.jpg"),
        f'<link rel="canonical" href="{html.escape(prefix, quote=True)}">',
    ]


def _add_index_tags(index: Path, site_url: str) -> None:
    """Insert the social tags into the exported page, never into the source `openfield/web`."""
    document = index.read_text(encoding="utf-8")
    tags = "".join(f"  {tag}\n" for tag in _social_tags(
        site_url, _page_description(document)))
    described = re.compile(r'(<meta\s+name=["\']description["\'][^>]*>)', re.IGNORECASE)
    head = re.compile(r'(<head[^>]*>)', re.IGNORECASE)
    marker = described if described.search(document) else head
    index.write_text(marker.sub(lambda found: f"{found.group(1)}\n{tags.rstrip()}", document, count=1),
                     encoding="utf-8", newline="\n")


def _take_label(take: dict[str, Any]) -> str:
    """A short human label: the camera move for a Direct take, else the kind of take."""
    kind = str(take.get("kind") or "")
    if kind == "direct":
        recipe = take.get("recipe") or {}
        movement = (recipe.get("rig") or {}).get("movement")
        move = next((m for m in rigs.catalog()["moves"] if m["id"] == movement), None)
        label = str(move["label"]) if move else "Direct"
        cast = recipe.get("cast_name")
        if cast:
            label += f" · {cast}"
    else:
        label = KIND_LABELS.get(kind, kind.replace("_", " ").title() or "Take")
    return label[:79].rstrip()


def _models_text(folder: Path) -> str:
    try:
        receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        receipt = {}
    names: list[str] = []
    for model in receipt.get("models") or []:
        if not isinstance(model, dict):
            continue
        role = str(model.get("role") or "").lower()
        key = role.split(":", 1)[1] if ":" in role else ""
        name = MODEL_NAMES.get(key)
        if not name:
            source = " ".join(str(model.get(field) or "") for field in ("file", "repo")).lower()
            if "ltx" in source:
                name = MODEL_NAMES["ltx-2.5"]
            elif "qwen" in source:
                name = MODEL_NAMES["qwen-image-2.1"]
            elif "wan" in source and "animate" in source:
                name = MODEL_NAMES["wan-animate-2"]
        if name and name not in names:
            names.append(name)
    if not names:
        return FALLBACK_MODELS
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _video_size(take: dict[str, Any]) -> tuple[int, int] | None:
    size = take.get("size")
    if isinstance(size, list) and len(size) == 2 and all(isinstance(v, int) and v > 0 for v in size):
        return size[0], size[1]
    width, height = take.get("width"), take.get("height")
    if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
        return width, height
    return None


def _take_description(take: dict[str, Any], label: str) -> str:
    subject = (take.get("recipe") or {}).get("subject")
    if take.get("kind") == "direct" and subject:
        return f"{label}: {subject}"
    return f"{label} · a take made with open weights on OpenField Studio."


def _share_page(*, title: str, description: str, og_title: str, og_description: str, page_path: str, target: str,
                image_path: str, image_alt: str, video_path: str | None, size: tuple[int, int] | None,
                site_url: str | None, link_text: str) -> str:
    """A page a link points at: it unfurls in a feed (with the video where the feed plays one) and opens the app."""
    lines = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{html.escape(title)}</title>",
        _meta("name", "description", description),
    ]
    if site_url:
        page_url = site_url + page_path
        image = site_url + image_path
        lines += [
            _meta("property", "og:type", "video.other"),
            _meta("property", "og:title", og_title),
            _meta("property", "og:description", og_description),
            _meta("property", "og:url", page_url),
            _meta("property", "og:image", image),
            _meta("property", "og:image:width", str(CARD_SIZE[0])),
            _meta("property", "og:image:height", str(CARD_SIZE[1])),
            _meta("property", "og:image:alt", image_alt),
        ]
        if video_path:
            lines += [
                _meta("property", "og:video", site_url + video_path),
                _meta("property", "og:video:secure_url", site_url + video_path),
                _meta("property", "og:video:type", "video/mp4"),
            ]
            if size:
                lines += [
                    _meta("property", "og:video:width", str(size[0])),
                    _meta("property", "og:video:height", str(size[1])),
                ]
        lines += [
            _meta("name", "twitter:card", "summary_large_image"),
            _meta("name", "twitter:image", image),
            f'<link rel="canonical" href="{html.escape(page_url, quote=True)}">',
        ]
    lines += [
        f'<meta http-equiv="refresh" content="0; url={html.escape(target, quote=True)}">',
        "</head>",
        "<body>",
        f'<p><a href="{html.escape(target, quote=True)}">{html.escape(link_text)}</a></p>',
        f'<script>location.replace({json.dumps(target)})</script>',
        "</body>",
        "</html>",
    ]
    return "\n".join(lines) + "\n"


def _take_page(take: dict[str, Any], label: str, site_url: str | None, has_card: bool,
               models: str) -> str:
    take_id = str(take["id"])
    return _share_page(
        title=f"{label} · OpenField Studio", description=_take_description(take, label), og_title=label,
        og_description=f"Made with open weights on OpenField Studio: {models}. Every take carries a sealed receipt.",
        page_path=f"t/{take_id}.html", target=f"../#/takes/{take_id}",
        image_path=f"t/{take_id}.jpg" if has_card else "static/card.jpg", image_alt=label,
        video_path=MEDIA_BASE.format(id=take_id) + "/take.mp4", size=_video_size(take), site_url=site_url,
        link_text="Open the take")


def _move_page(move: dict[str, Any], take: dict[str, Any], site_url: str | None, has_card: bool) -> str:
    """A camera move's own page: it unfurls with the take that shows the move and opens the move in the Lobby."""
    move_id, take_id, label = str(move["id"]), str(take["id"]), str(move["label"])
    # a move made in code (mirrored, played backwards, rolled, reframed) is prompted with its twin's words; its page says
    # what the move is, in its own phrase, and the Lobby's page shows the words the model read beside how it was made
    words = str((move.get("phrase") if move.get("made") else None) or move.get("words") or move.get("phrase") or "")
    words = words if len(words) <= 220 else words[:219].rsplit(" ", 1)[0] + "…"
    return _share_page(
        title=f"{label} · camera move · OpenField Studio", description=words, og_title=f"{label}: a camera move",
        og_description=f"{words} Rendered with open weights on OpenField Studio.",
        page_path=f"m/{move_id}.html", target=f"../#/lobby/{move_id}",
        image_path=f"t/{take_id}.jpg" if has_card else "static/card.jpg", image_alt=f"{label}, the recorded take",
        video_path=MEDIA_BASE.format(id=take_id) + "/take.mp4", size=_video_size(take), site_url=site_url,
        link_text="Open the move")


def _font(name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = FONT_DIR / name
    try:
        return ImageFont.truetype(str(path), size)
    except (OSError, ValueError):
        return ImageFont.load_default(size=size)


def _fitted_font(draw: ImageDraw.ImageDraw, text: str, name: str, max_width: int,
                 sizes: range) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font = _font(name, sizes[-1])
    for size in sizes:
        font = _font(name, size)
        if draw.textlength(text, font=font) <= max_width:
            break
    return font


def _write_card(poster: Path | None, dest: Path, label: str, subtitle: str) -> bool:
    """A 1200x630 JPEG from a poster (a plain dark card when there is no poster)."""
    if poster is None:
        image = Image.new("RGB", CARD_SIZE, (12, 11, 10))
    else:
        try:
            with Image.open(poster) as source:
                image = ImageOps.fit(source.convert("RGB"), CARD_SIZE, method=Image.Resampling.LANCZOS)
        except (OSError, ValueError):
            return False
    overlay = Image.new("RGBA", CARD_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    band = 120
    draw.rectangle((0, CARD_SIZE[1] - band, CARD_SIZE[0], CARD_SIZE[1]), fill=(8, 8, 8, 204))
    label_font = _fitted_font(draw, label, "barlow-condensed-latin-800.woff2",
                              CARD_SIZE[0] - 80, range(64, 25, -2))
    small_font = _font("barlow-latin-600.woff2", 24)
    draw.text((40, CARD_SIZE[1] - 106), label, font=label_font, fill=(245, 242, 236, 255))
    draw.text((40, CARD_SIZE[1] - 38), subtitle, font=small_font, fill=(190, 184, 175, 255))
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, "JPEG", quality=CARD_QUALITY, progressive=True, optimize=True)
    return True


def _site_card(folders: dict[str, Path], hero: str | None, dest: Path) -> None:
    """The site card from the hero take's poster, else the newest usable poster, else a plain card."""
    order = ([hero] if hero in folders else []) + [take_id for take_id in folders if take_id != hero]
    subtitle = "A film studio on open weights in ComfyUI · every take keeps its receipt"
    for take_id in order:
        poster = folders[take_id] / "poster.png"
        if poster.is_file() and _write_card(poster, dest, "OpenField Studio", subtitle):
            return
    _write_card(None, dest, "OpenField Studio", subtitle)


def export_static(settings: Settings, out_dir: Path, *, takes_root: Path | None = None,
                  web_dir: Path | None = None, cast_root: Path | None = None,
                  site_url: str | None = None, repo_url: str | None = None) -> dict[str, Any]:
    """Write the hosted Replay to `out_dir` and return a summary. Raises StaticExportError."""
    takes_root = Path(takes_root) if takes_root else settings.showcase_dir / "takes"
    cast_root = Path(cast_root) if cast_root else settings.showcase_dir / "cast"
    web_dir = Path(web_dir) if web_dir else settings.web_dir
    if not (web_dir / "index.html").is_file():
        raise StaticExportError(f"no web app at {web_dir} (index.html is missing)")
    folders = recorded_takes(takes_root)
    if not folders:
        raise StaticExportError(
            f"no recorded takes under {takes_root}. Render some, then copy their folders there.")
    out_dir = Path(out_dir)
    _prepare_out(out_dir, [web_dir, takes_root])

    shutil.copytree(web_dir, out_dir, dirs_exist_ok=True, ignore=shutil.ignore_patterns(*WEB_IGNORE))
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    takes, size = [], 0
    records: list[tuple[dict[str, Any], Path]] = []
    for folder in folders:
        take = json.loads((folder / "take.json").read_text(encoding="utf-8"))
        size += _write_take(folder, out_dir / "showcase" / "takes" / take["id"])
        listed = dict(take, media_base=MEDIA_BASE.format(id=take["id"]))
        if "identity" in listed:
            listed["identity"] = slim_identity(listed["identity"])
        takes.append(listed)
        records.append((take, folder))

    exported = {t["id"] for t in takes}  # the shelf may only list takes whose media is really in the site
    site_url = _normalise_url(site_url)
    site_json = out_dir / SITE_JSON
    site_json.parent.mkdir(parents=True, exist_ok=True)
    site_json.write_text(
        json.dumps({"site_url": site_url, "repo_url": str(repo_url) if repo_url else None},
                   indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")

    shipped_previews = False  # the page asks for previews.json only when the manifest says it is there
    previews_index_path = takes_root.parent / "previews.json"
    if previews_index_path.is_file():
        try:
            previews_index = json.loads(previews_index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previews_index = None
        if isinstance(previews_index, dict):
            previews_src = takes_root.parent / "previews"  # beside the index, as build_previews writes them
            previews_out = out_dir / "showcase" / "previews"
            preview_takes: dict[str, Any] = {}
            for take_id in exported:
                entry = previews_index.get("takes", {}).get(take_id)
                if not isinstance(entry, dict):
                    continue
                copied = False
                for suffix in PREVIEW_SUFFIXES:
                    src = previews_src / f"{take_id}{suffix}"
                    if src.is_file():
                        previews_out.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, previews_out / f"{take_id}{suffix}")
                        size += (previews_out / f"{take_id}{suffix}").stat().st_size
                        copied = True
                for url in (entry.get("stills") or {}).values():  # the small copies of the take's stills
                    src = previews_src / Path(str(url)).name
                    if src.is_file():
                        previews_out.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, previews_out / src.name)
                        size += (previews_out / src.name).stat().st_size
                if copied:  # the hashes only tell the builder what to cut again: the page never reads them
                    preview_takes[take_id] = {k: v for k, v in entry.items() if k not in ("source_sha256", "stills_sha")}
            if preview_takes:
                filtered_index = {
                    "version": previews_index.get("version", 1),
                    "seconds": previews_index.get("seconds", 2.5),
                    "takes": preview_takes,
                    "moves": {
                        move_id: take_id
                        for move_id, take_id in previews_index.get("moves", {}).items()
                        if take_id in exported
                    },
                    "effects": {
                        effect_id: take_id
                        for effect_id, take_id in previews_index.get("effects", {}).items()
                        if take_id in exported
                    },
                }
                previews_out.mkdir(parents=True, exist_ok=True)
                shipped_previews = True
                (out_dir / "showcase" / "previews.json").write_text(
                    json.dumps(filtered_index, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")
    hero = hero_take(takes_root.parent)
    folders_by_id = {str(take["id"]): folder for take, folder in records}
    _site_card(folders_by_id, hero, out_dir / "static" / "card.jpg")
    for take, folder in records:
        take_id = str(take["id"])
        label = _take_label(take)
        card = out_dir / "t" / f"{take_id}.jpg"
        has_card = (folder / "take.mp4").is_file() and (folder / "poster.png").is_file() and _write_card(
            folder / "poster.png", card, label, "OpenField Studio · open weights")
        page = out_dir / "t" / f"{take_id}.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(_take_page(take, label, site_url, has_card, _models_text(folder)),
                        encoding="utf-8", newline="\n")
    # one page per camera move with a recorded take, so a move can be shared on its own
    takes_by_id = {str(take["id"]): take for take, _ in records}
    catalog = {m["id"]: m for m in rigs.catalog()["moves"] if m.get("validated")}
    previews_file = out_dir / "showcase" / "previews.json"
    shown = json.loads(previews_file.read_text(encoding="utf-8")).get("moves", {}) if previews_file.is_file() else {}
    for move_id, take_id in shown.items():
        if move_id not in catalog or take_id not in takes_by_id:
            continue
        page = out_dir / "m" / f"{move_id}.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        has_card = (out_dir / "t" / f"{take_id}.jpg").is_file()
        page.write_text(_move_page(catalog[move_id], takes_by_id[take_id], site_url, has_card), encoding="utf-8", newline="\n")
    if site_url:
        _add_index_tags(out_dir / "index.html", site_url)
    reel = [t for t in hero_reel(takes_root.parent) if t in exported]
    # the shelf is a list of ids: each recorded take's fields are in `takes` already, and the page joins them (api-static.js)
    recorded = [r["id"] for r in ReplayBackend([takes_root]).recorded({takes_root: MEDIA_BASE}) if r["id"] in exported]
    cast = []
    for data, folder in shipped_casts(cast_root) if cast_root.is_dir() else []:
        written, member = _write_cast(data, folder, out_dir / "showcase" / "cast" / data["id"])
        size += written
        cast.append(dict(member, bundled=True))
    manifest = {
        "schema": 1, "static": True, "app": "openfield-studio", "version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "status": build_status(len(recorded), hero=hero if hero in exported else None, reel=reel,
                               gpu=recorded_gpu(folders_by_id[t] for t in exported if t in folders_by_id)), "moves": rigs.catalog(),
        "takes": takes, "recorded": recorded, "cast": cast, "previews": shipped_previews,
    }
    target = out_dir / MANIFEST
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return {"out": str(out_dir.resolve()), "takes": len(takes), "recorded": len(recorded), "cast": len(cast),
            "media_bytes": size}
