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
from .base import BackendError, EventSink, RunResult


class ReplayBackend:
    kind = "replay"
    label = "Replay"
    locked = True

    def __init__(self, roots: Iterable[Path]) -> None:
        self.roots = [Path(r) for r in roots]

    def index(self) -> dict[str, Path]:
        """Recipe fingerprint -> recorded take folder, for every complete take under the roots."""
        found: dict[str, Path] = {}
        for root in self.roots:
            if not root.is_dir():
                continue
            for take_json in sorted(root.glob("*/take.json")):
                folder = take_json.parent
                try:
                    take = json.loads(take_json.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                digest = take.get("recipe_hash")
                if (digest and take.get("status") == "succeeded" and not take.get("replay")
                        and (folder / "receipt.json").is_file()):
                    found.setdefault(digest, folder)
        return found

    def find(self, recipe_hash: str) -> Path | None:
        return self.index().get(recipe_hash)

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
