"""Replay: the backend you get with no key and no GPU.

It never renders. It knows which recipes were really rendered (a recorded take is just a ledger
folder with `take.json`, `receipt.json`, `events.jsonl` and media) and the pipeline replays those
by recipe fingerprint. Any other recipe is refused with an explanation: no silent canned output.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ..engine.workflows import PatchedWorkflow
from ..ledger import TAKE_ID
from .base import BackendError, EventSink, RunResult


class ReplayBackend:
    kind = "replay"
    label = "Replay"
    locked = True

    def __init__(self, roots: Iterable[Path]) -> None:
        self.roots = [Path(r) for r in roots]

    def index(self) -> dict[str, Path]:
        """Recipe fingerprint -> recorded take folder, for every complete take under the roots. An earlier root wins; within
        a root the newest take does, so a superseded take kept because others point at it never shadows its re-record."""
        found: dict[str, Path] = {}
        for root in self.roots:
            if not root.is_dir():
                continue
            newest: dict[str, tuple[str, Path]] = {}
            for take_json in sorted(root.glob("*/take.json")):
                folder = take_json.parent
                try:
                    take = json.loads(take_json.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                digest = take.get("recipe_hash")
                if (digest and take.get("status") == "succeeded" and not take.get("replay")
                        and (folder / "receipt.json").is_file()):
                    created = str(take.get("created_at") or "")
                    if digest not in newest or created > newest[digest][0]:
                        newest[digest] = (created, folder)
            for digest, (_, folder) in newest.items():
                found.setdefault(digest, folder)
        return found

    def find(self, recipe_hash: str) -> Path | None:
        return self.index().get(recipe_hash)

    def folder(self, take_id: str) -> Path | None:
        """The recorded folder of a take id, if one of the roots holds a complete take by that id."""
        if not TAKE_ID.match(take_id):
            return None
        for root in self.roots:
            folder = root / take_id
            if (folder / "take.json").is_file() and (folder / "receipt.json").is_file():
                return folder
        return None

    def recorded(self, bases: Mapping[Path, str] | None = None) -> list[dict[str, Any]]:
        """Summaries of replayable takes, for the 'Recreate' shelf in the UI.

        `bases` maps a root folder to the URL template its takes' media is served from
        (for example `{showcase_root: "/showcase/takes/{id}"}`); each summary gets a `media_base`.
        """
        bases = {Path(root).resolve(): template for root, template in (bases or {}).items()}
        out = []
        for digest, folder in self.index().items():
            take = json.loads((folder / "take.json").read_text(encoding="utf-8"))
            entry = {"id": take["id"], "kind": take["kind"], "label": take["label"],
                     "recipe_hash": digest, "recipe": take["recipe"], "outputs": take["outputs"],
                     "created_at": take.get("created_at")}
            for key in ("identity", "audit", "notes", "seconds", "shots", "board", "edit"):  # what the dock, the wall and a board show, without a second request
                if take.get(key) is not None:
                    entry[key] = take[key]
            template = bases.get(folder.parent.resolve())
            if template:
                entry["media_base"] = template.format(id=take["id"])
            out.append(entry)
        out.sort(key=lambda e: e.get("created_at") or "", reverse=True)
        return out

    async def health(self) -> dict[str, Any]:
        count = len(self.index())
        return {"ok": True, "kind": self.kind, "label": self.label,
                "detail": f"{count} recorded take(s). Connect a backend to render new ones."}

    async def run(
        self, patched: PatchedWorkflow, *, out_dir: Path, on_event: EventSink | None = None,
        timeout: float = 1800.0,
    ) -> RunResult:
        raise BackendError(
            "replay_unavailable",
            "Replay never renders. Connect a backend (Comfy Cloud or a GPU box) to make new takes.",
        )

def hero_take(showcase_dir: Path) -> str | None:
    """The take the demo and the hosted copy open on: `<showcase>/hero.json` names it; otherwise the newest wins."""
    try:
        data = json.loads((Path(showcase_dir) / "hero.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    take = data.get("take") if isinstance(data, dict) else None
    return take if isinstance(take, str) and take else None


def recorded_gpu(take_folders: Iterable[Path]) -> dict[str, Any] | None:
    """The GPU time the takes' receipts list, summed: {"takes": n, "seconds": s}, or None when none lists any. Only what
    each kept take recorded: failed tries and the time a GPU sat idle are not in it."""
    takes, seconds = 0, 0.0
    for folder in take_folders:
        try:
            receipt = json.loads((Path(folder) / "receipt.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        timings = (receipt.get("backend") or {}).get("timings") if isinstance(receipt, dict) else None
        total = timings.get("total_s") if isinstance(timings, dict) else None
        if isinstance(total, (int, float)) and not isinstance(total, bool) and total > 0:
            takes += 1
            seconds += float(total)
    return {"takes": takes, "seconds": round(seconds, 1)} if takes else None


_GPU_SEEN: dict[str, tuple[int, dict[str, Any] | None]] = {}


def showcase_gpu(showcase_dir: Path) -> dict[str, Any] | None:
    """`recorded_gpu` over the showcase's takes, read again only when the takes folder changes (the status is polled)."""
    root = Path(showcase_dir) / "takes"
    try:
        stamp = root.stat().st_mtime_ns
    except OSError:
        return None
    seen = _GPU_SEEN.get(str(root))
    if seen and seen[0] == stamp:
        return seen[1]
    total = recorded_gpu(sorted(p for p in root.iterdir() if p.is_dir() and TAKE_ID.match(p.name)))
    _GPU_SEEN[str(root)] = (stamp, total)
    return total


def hero_reel(showcase_dir: Path) -> list[str]:
    """The order the filmstrip shows recorded takes in: `<showcase>/hero.json` `reel`, a curated mix of people and places
    (recordings are listed newest first everywhere else); empty when the showcase names none."""
    try:
        data = json.loads((Path(showcase_dir) / "hero.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    reel = data.get("reel") if isinstance(data, dict) else None
    return [t for t in reel if isinstance(t, str) and t] if isinstance(reel, list) else []
