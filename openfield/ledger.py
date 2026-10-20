"""Take ledger: one folder per take, no database.

    <root>/<take_id>/take.json        summary shown in the UI (status, recipe, outputs, error)
    <root>/<take_id>/receipt.json     sealed provenance receipt
    <root>/<take_id>/events.jsonl     every pipeline event, replayable by the UI
    <root>/<take_id>/runs/<n>_<stage>/  one folder per ComfyUI run: run.json, events.jsonl, media
    <root>/<take_id>/<final media>

The same folders are what Replay plays back, so a recorded showcase is just a ledger on disk.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .fsutil import read_text, replace_file

TAKE_ID = re.compile(r"^tk_\d{8}_\d{6}_[0-9a-f]{4}$")
SAFE_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
TERMINAL = {"succeeded", "failed", "canceled"}


class LedgerError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_json(path: Path, data: Any) -> None:
    """Atomic write so a crash never leaves half a file for the UI to choke on.

    The temporary name is unique per process and thread, and the replace retries: on Windows a reader
    (the interface polling a take, an antivirus scan) briefly holding the file would otherwise fail it.
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    try:
        replace_file(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


class Ledger:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()  # take.json is read, changed and rewritten: one writer at a time

    # -- identity and paths --------------------------------------------------------------
    def take_dir(self, take_id: str) -> Path:
        if not TAKE_ID.match(take_id):
            raise LedgerError(f"not a take id: {take_id!r}")
        return self.root / take_id

    def run_dir(self, take_id: str, number: int, stage: str) -> Path:
        if not SAFE_PART.match(stage):
            raise LedgerError(f"bad stage name: {stage!r}")
        path = self.take_dir(take_id) / "runs" / f"{number:02d}_{stage}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def media_path(self, take_id: str, relative: str) -> Path:
        """A file inside a take folder, at most two levels deep, never outside it."""
        base = self.take_dir(take_id).resolve()
        parts = [p for p in relative.replace("\\", "/").split("/") if p]
        if not parts or len(parts) > 3 or not all(SAFE_PART.match(p) for p in parts):
            raise LedgerError("bad media path")
        target = base.joinpath(*parts).resolve()
        if base not in target.parents or not target.is_file():
            raise LedgerError("no such file")
        return target

    # -- lifecycle -----------------------------------------------------------------------
    def create(
        self, kind: str, label: str, recipe: dict[str, Any], *, parent: str | None = None,
        backend: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        take_id = f"tk_{stamp}_{secrets.token_hex(2)}"
        directory = self.take_dir(take_id)
        directory.mkdir(parents=True)
        take = {
            "id": take_id, "kind": kind, "label": label, "status": "queued", "stage": None,
            "progress": 0.0, "created_at": now_iso(), "updated_at": now_iso(), "recipe": recipe,
            "parent": parent, "backend": backend or {}, "outputs": [], "error": None,
            "notes": [], "replay": False,
        }
        write_json(directory / "take.json", take)
        return take

    def read(self, take_id: str) -> dict[str, Any]:
        path = self.take_dir(take_id) / "take.json"
        try:
            return json.loads(read_text(path))
        except FileNotFoundError:
            raise LedgerError(f"no such take: {take_id}") from None

    def update(self, take_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            take = self.read(take_id)
            take.update(changes)
            take["updated_at"] = now_iso()
            write_json(self.take_dir(take_id) / "take.json", take)
            return take

    def list(self, *, kind: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        takes: list[dict[str, Any]] = []
        for entry in self.root.iterdir():
            if not (entry.is_dir() and TAKE_ID.match(entry.name)):
                continue
            try:
                take = json.loads(read_text(entry / "take.json"))
            except (OSError, ValueError):
                continue
            if kind is None or take.get("kind") == kind:
                takes.append(take)
        takes.sort(key=lambda t: t["created_at"], reverse=True)
        return takes[:limit]

    def delete(self, take_id: str) -> None:
        shutil.rmtree(self.take_dir(take_id), ignore_errors=True)

    def recover_interrupted(self) -> list[str]:
        """Mark takes left unfinished by a stopped process as failed so the UI never waits on them.

        That includes takes waiting for approval: the process that would have rendered the video is gone,
        so an approval could never be acted on.
        """
        fixed = []
        for take in self.list():
            if take["status"] not in TERMINAL:
                waiting = take["status"] == "awaiting_approval"
                self.update(take["id"], status="failed", error={
                    "code": "interrupted",
                    "message": ("The app stopped while this take was waiting for your approval. "
                                "Start it again; the stills it made are kept." if waiting
                                else "The app stopped while this take was running."),
                    "retryable": True})
                fixed.append(take["id"])
        return fixed
