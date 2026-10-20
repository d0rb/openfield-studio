"""Backend contract: run a patched workflow, stream normalised events, return real files.

Everything above this layer (pipeline, API, UI) sees the same `Event`s and `RunResult`s whether
the work ran on Comfy Cloud, a GPU box behind comfy-api-proxy, or was replayed from a recording.
"""
from __future__ import annotations

import inspect
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..engine.workflows import PatchedWorkflow

EventSink = Callable[[dict[str, Any]], Awaitable[None] | None]
EXTENSIONS = {
    "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
    "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
    "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/flac": ".flac", "audio/ogg": ".ogg",
}


class BackendError(RuntimeError):
    """A failure with a stable machine code and a message that is safe to show a user."""

    def __init__(
        self, code: str, message: str, *, job_id: str | None = None,
        retryable: bool = False, details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.job_id = job_id
        self.retryable = retryable
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code, "message": str(self), "job_id": self.job_id,
            "retryable": self.retryable, "details": self.details,
        }


def media_kind(content_type: str, name: str = "") -> str:
    """video | image | audio | other, from the content type and file name.

    Never from the API's own `type` field: through comfy-api-proxy a SaveVideo result arrives
    as type="image" with content_type="video/mp4".
    """
    head = (content_type or "").split("/")[0]
    if head in {"video", "image", "audio"}:
        return head
    suffix = Path(name).suffix.lower()
    if suffix in {".mp4", ".mov", ".webm", ".mkv"}:
        return "video"
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "image"
    return "audio" if suffix in {".mp3", ".wav", ".flac", ".ogg"} else "other"


def extension_for(content_type: str, name: str) -> str:
    return Path(name).suffix.lower() or EXTENSIONS.get((content_type or "").split(";")[0], ".bin")


@dataclass(frozen=True)
class OutputFile:
    role: str
    node_id: str
    name: str
    content_type: str
    kind: str
    path: Path
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role, "node_id": self.node_id, "name": self.name,
            "content_type": self.content_type, "kind": self.kind, "file": self.path.name,
            "size_bytes": self.size_bytes,
        }


@dataclass
class RunResult:
    job_id: str
    status: str
    backend: str
    files: dict[str, OutputFile] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)


class EventRecorder:
    """Appends every event to events.jsonl (the format Replay plays) and forwards it live."""

    def __init__(self, path: Path, sink: EventSink | None = None) -> None:
        self.t0 = time.monotonic()
        self._fh = path.open("w", encoding="utf-8")
        self._sink = sink

    async def emit(self, kind: str, **data: Any) -> None:
        event = {"t": round(time.monotonic() - self.t0, 3), "kind": kind, **data}
        self._fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._fh.flush()
        if self._sink is not None:
            result = self._sink(event)
            if inspect.isawaitable(result):
                await result

    def close(self) -> None:
        self._fh.close()


class Backend(Protocol):
    kind: str  # "cloud" | "pod" | "deployment" | "replay"
    label: str
    locked: bool  # True for Replay: edits cannot be rendered

    async def health(self) -> dict[str, Any]: ...

    async def run(
        self, patched: PatchedWorkflow, *, out_dir: Path, on_event: EventSink | None = None,
        timeout: float = 1800.0,
    ) -> RunResult: ...
