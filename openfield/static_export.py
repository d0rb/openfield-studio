"""Build the hosted Replay: the web app plus recorded takes as plain static files.

    <out>/index.html, js/, ...                       the app (openfield/web, minus showcase/)
    <out>/static/manifest.json                       what /api/status, /api/moves and /api/replay/recorded answer
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

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__, share
from .backends.replay import ReplayBackend
from .config import Settings
from .engine import rig as rigs
from .engine.audit import POLICY

MANIFEST = Path("static") / "manifest.json"
MEDIA_BASE = "showcase/takes/{id}"
STILL_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
WEB_IGNORE = ("showcase", "__pycache__", "node_modules", "package.json", "*.map")


class StaticExportError(ValueError):
    pass


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
    archive.write_bytes(share.workflows_zip(folder))
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


def build_status(count: int) -> dict[str, Any]:
    label = "Replay (hosted)"
    return {
        "app": "openfield-studio", "version": __version__, "policy": POLICY, "static": True,
        "backend": {
            "kind": "replay", "label": label, "locked": True, "sdk_configured": False,
            "health": {"ok": True, "kind": "replay", "label": label,
                       "detail": f"{count} recorded take(s). Install OpenField to render new ones."},
        },
        "face_check": {"available": False, "reason": "The hosted copy only plays recorded takes."},
        "recorded_takes": count,
    }


def export_static(settings: Settings, out_dir: Path, *, takes_root: Path | None = None,
                  web_dir: Path | None = None) -> dict[str, Any]:
    """Write the hosted Replay to `out_dir` and return a summary. Raises StaticExportError."""
    takes_root = Path(takes_root) if takes_root else settings.showcase_dir / "takes"
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
    for folder in folders:
        take = json.loads((folder / "take.json").read_text(encoding="utf-8"))
        size += _write_take(folder, out_dir / "showcase" / "takes" / take["id"])
        takes.append(dict(take, media_base=MEDIA_BASE.format(id=take["id"])))

    exported = {t["id"] for t in takes}  # the shelf may only list takes whose media is really in the site
    recorded = [r for r in ReplayBackend([takes_root]).recorded({takes_root: MEDIA_BASE}) if r["id"] in exported]
    manifest = {
        "schema": 1, "static": True, "app": "openfield-studio", "version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "status": build_status(len(recorded)), "moves": rigs.catalog(),
        "takes": takes, "recorded": recorded, "cast": [],
    }
    target = out_dir / MANIFEST
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return {"out": str(out_dir.resolve()), "takes": len(takes), "recorded": len(recorded),
            "media_bytes": size}
