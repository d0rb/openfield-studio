"""Comfy SDK backend: Comfy Cloud, a GPU box behind comfy-api-proxy, or a Comfy API deployment.

The SDK reads its base URL only from COMFY_BASE_URL, so the target is chosen by briefly setting
that variable while a client is constructed (under a lock); each run owns its own client.
"""
from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from comfy_sdk import (
    AsyncComfy,
    ComfyError,
    Forbidden,
    IdempotencyKeyReuse,
    InsufficientCredits,
    InvalidWorkflow,
    JobFailed,
    MissingApiKey,
    MissingAsset,
    NotFound,
    OutputReady,
    Preview,
    Progress,
    QueueFull,
    StatusChange,
    Unauthorized,
    WorkflowFormatUi,
)

from ..engine.workflows import PatchedWorkflow
from ..fsutil import replace_file
from .base import (
    BackendError,
    EventRecorder,
    EventSink,
    OutputFile,
    RunResult,
    extension_for,
    media_kind,
)

CLOUD_HOST = "cloud.comfy.org"
TERMINAL_STATES = frozenset({"succeeded", "failed", "canceled", "expired"})
_ENV_LOCK = threading.Lock()


@contextlib.contextmanager
def _base_url_env(base_url: str | None) -> Iterator[None]:
    with _ENV_LOCK:
        previous = os.environ.get("COMFY_BASE_URL")
        if base_url:
            os.environ["COMFY_BASE_URL"] = base_url
        else:
            os.environ.pop("COMFY_BASE_URL", None)
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("COMFY_BASE_URL", None)
            else:
                os.environ["COMFY_BASE_URL"] = previous


def classify(base_url: str | None) -> tuple[str, str]:
    """(kind, label) for a base URL: Comfy Cloud, a deployment, or a self-hosted box."""
    if not base_url or urlsplit(base_url).hostname == CLOUD_HOST:
        return "cloud", "Comfy Cloud"
    host = urlsplit(base_url).hostname or ""
    if host.endswith(".run.comfy.app"):
        return "deployment", "Comfy API deployment"
    return "pod", "GPU box"


def map_error(exc: BaseException, job_id: str | None = None) -> BackendError:
    """Translate SDK/transport failures into stable codes with messages a person can act on."""
    if isinstance(exc, BackendError):
        return exc
    pairs: list[tuple[type[BaseException], str, str, bool]] = [
        (MissingApiKey, "missing_api_key", "No API key. Set COMFY_API_KEY (Comfy Cloud needs one).", False),
        (Unauthorized, "unauthorized", "The API key or token was rejected.", False),
        (Forbidden, "forbidden", "This key is not allowed to do that.", False),
        (InsufficientCredits, "insufficient_credits", "Out of Comfy credits.", False),
        (WorkflowFormatUi, "workflow_format_ui", "The workflow is UI-format; API format is required.", False),
        (InvalidWorkflow, "invalid_workflow", "ComfyUI rejected the workflow.", False),
        (MissingAsset, "missing_asset", "An uploaded file could not be found by the server.", True),
        (NotFound, "not_found", "The server does not know that job or file.", False),
        (IdempotencyKeyReuse, "idempotency_key_reuse",
         "That submission was already accepted; recover it from its job id instead of resending.", False),
    ]
    for klass, code, message, retryable in pairs:
        if isinstance(exc, klass):
            return BackendError(code, message, job_id=job_id, retryable=retryable,
                                details={"detail": _clip(str(exc))})
    if isinstance(exc, QueueFull):
        return BackendError("queue_full", "The queue is full; try again shortly.", job_id=job_id,
                            retryable=True, details={"retry_after": getattr(exc, "retry_after", None)})
    if isinstance(exc, JobFailed):
        err = exc.error
        info = (err.model_dump() if hasattr(err, "model_dump")
                else {"message": str(err) if err else str(exc)})
        where = f" at node {info['node_id']} ({info.get('class_type')})" if info.get("node_id") else ""
        return BackendError("job_failed", f"The job failed{where}: {_clip(info.get('message', ''))}",
                            job_id=job_id, details=_clip_dict(info))
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return BackendError("unreachable", "Could not reach the server. Is the tunnel up?",
                            job_id=job_id, retryable=True)
    if isinstance(exc, (httpx.TimeoutException, TimeoutError, asyncio.TimeoutError)):
        return BackendError("timeout", "The server did not answer in time.", job_id=job_id, retryable=True)
    if isinstance(exc, ComfyError):
        return BackendError("sdk_error", _clip(str(exc)), job_id=job_id)
    return BackendError("unexpected", f"{type(exc).__name__}: {_clip(str(exc))}", job_id=job_id)


def _clip(text: str, limit: int = 400) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _clip_dict(info: dict[str, Any]) -> dict[str, Any]:
    return {k: (_clip(v, 1200) if isinstance(v, str) else v) for k, v in info.items()}


class SdkBackend:
    locked = False

    def __init__(self, *, base_url: str | None = None, api_key: str | None = None,
                 request_timeout: float = 180.0) -> None:
        self.base_url = base_url or None
        self._api_key = api_key or None
        self._request_timeout = request_timeout
        self.kind, self.label = classify(self.base_url)
        # the offline dev stack names itself, so what it makes can never pass for a real render
        self.label = os.environ.get("OPENFIELD_BACKEND_LABEL") or self.label

    @classmethod
    def from_env(cls) -> SdkBackend:
        return cls(base_url=os.environ.get("COMFY_BASE_URL"), api_key=os.environ.get("COMFY_API_KEY"))

    def _client(self) -> AsyncComfy:
        with _base_url_env(self.base_url):
            return AsyncComfy(api_key=self._api_key, timeout=self._request_timeout)

    async def health(self) -> dict[str, Any]:
        base = self.base_url or f"https://{CLOUD_HOST}"
        headers = {"Authorization": f"Bearer {self._api_key}", "X-API-Key": self._api_key} \
            if self._api_key else {}
        url = f"{base.rstrip('/')}/api/v2/health" if self.kind == "pod" else f"{base.rstrip('/')}/api/user"
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                response = await http.get(url, headers=headers)
        except httpx.HTTPError as exc:
            return {"ok": False, "kind": self.kind, "label": self.label, "detail": map_error(exc).args[0]}
        ok = response.status_code == 200
        detail = "ready" if ok else f"HTTP {response.status_code}"
        if response.status_code in {401, 403}:
            detail = "key rejected" if self._api_key else "needs an API key"
        return {"ok": ok, "kind": self.kind, "label": self.label, "detail": detail,
                "authenticated": bool(self._api_key)}

    async def run(
        self, patched: PatchedWorkflow, *, out_dir: Path, on_event: EventSink | None = None,
        timeout: float = 1800.0,
    ) -> RunResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        recorder = EventRecorder(out_dir / "events.jsonl", on_event)
        started = time.monotonic()
        job = None
        try:
            async with self._client() as client:
                # the SDK mutates the graph it is given (asset handles go into it): hand it a copy
                wf = client.workflows.from_json(copy.deepcopy(patched.graph))
                total = 0
                for binding in patched.assets:
                    wf.set_input(binding.node, binding.input, client.assets.from_file(binding.path))
                    total += binding.path.stat().st_size
                deadline = started + timeout
                try:
                    await recorder.emit("uploading", files=len(patched.assets), bytes=total)
                    job = await client.submit(wf)
                    submitted = time.monotonic() - started
                    (out_dir / "job.json").write_text(
                        json.dumps({"job_id": job.id, "backend": self.kind}), encoding="utf-8")
                    await recorder.emit("submitted", job_id=job.id)

                    async def consume() -> None:
                        async for event in job.events():
                            await self._forward(event, recorder, out_dir)

                    # one budget for the whole render: if the event stream ends early (a target without
                    # SSE), the wait that follows gets what is left, not a fixed minute
                    await asyncio.wait_for(consume(), timeout=max(1.0, deadline - time.monotonic()))
                    await job.wait(timeout=max(1.0, deadline - time.monotonic()))
                    if job.status == "expired" and not job.error:
                        raise BackendError(
                            "job_expired", "The render target no longer has this job (it restarted, or the result "
                            "expired before it was collected). Run it again.", job_id=job.id, retryable=True)
                    if job.status != "succeeded":
                        raise JobFailed(f"job {job.id} ended {job.status}", error=job.error)
                    files = await self._download(job, patched, out_dir)
                except (asyncio.TimeoutError, TimeoutError):  # distinct classes before Python 3.11
                    await self._cancel_quietly(job)
                    raise BackendError(
                        "timeout", f"The render took longer than {timeout:.0f}s and was cancelled.",
                        job_id=getattr(job, "id", None), retryable=True) from None
                except BaseException:
                    # Cancelled, a dropped connection, a full disk while recording events, Ctrl+C: whatever
                    # stops us, a job still running on the target must not be left to finish unseen and
                    # billed. A job that already reached a terminal state is left alone.
                    await self._cancel_quietly(job)
                    raise
                return RunResult(
                    job_id=job.id, status=job.status, backend=self.kind, files=files,
                    timings={"submit_s": round(submitted, 2),
                             "total_s": round(time.monotonic() - started, 2)},
                )
        except Exception as exc:
            raise map_error(exc, getattr(job, "id", None)) from exc
        finally:
            recorder.close()

    @staticmethod
    async def _cancel_quietly(job: Any) -> None:
        """Ask the target to stop a job that is still going; never raises, never touches a finished job."""
        if job is None or getattr(job, "status", None) in TERMINAL_STATES:
            return
        with contextlib.suppress(Exception):
            await asyncio.shield(job.cancel())

    @staticmethod
    async def _forward(event: Any, recorder: EventRecorder, out_dir: Path) -> None:
        if isinstance(event, Progress):
            await recorder.emit(
                "progress", value=round(event.value, 4), step=event.step, steps=event.steps,
                node=event.current_node, nodes_done=event.nodes_done, nodes_total=event.nodes_total)
        elif isinstance(event, Preview):
            if event.data:
                tmp = out_dir / "preview.jpg.tmp"
                tmp.write_bytes(event.data)
                replace_file(tmp, out_dir / "preview.jpg")
            await recorder.emit("preview", node=event.node_id, bytes=len(event.data))
        elif isinstance(event, OutputReady):
            o = event.output
            await recorder.emit("output", node=o.node_id, name=o.name, content_type=o.content_type,
                                media=media_kind(o.content_type, o.name))
        elif isinstance(event, StatusChange):
            await recorder.emit("status", status=event.status, queue_position=event.queue_position)

    @staticmethod
    async def _download(job: Any, patched: PatchedWorkflow, out_dir: Path) -> dict[str, OutputFile]:
        files: dict[str, OutputFile] = {}
        for role, node_id in patched.outputs.items():
            candidates = job.get_outputs(node_id)
            if not candidates:
                seen = [(o.node_id, o.name, o.content_type) for o in job.outputs]
                raise BackendError(
                    "no_output", f"Node {node_id} ('{role}') produced no output.", job_id=job.id,
                    details={"returned": seen})
            wanted = role if role in {"video", "image", "audio"} else None
            chosen = next((o for o in candidates if wanted and media_kind(o.content_type, o.name) == wanted),
                          candidates[0])
            path = out_dir / f"{role}{extension_for(chosen.content_type, chosen.name)}"
            await chosen.to_file(path)
            size = path.stat().st_size
            if size == 0:
                raise BackendError("empty_output", f"The '{role}' output downloaded as an empty file.",
                                   job_id=job.id)
            files[role] = OutputFile(
                role=role, node_id=node_id, name=chosen.name, content_type=chosen.content_type,
                kind=media_kind(chosen.content_type, chosen.name), path=path, size_bytes=size)
        return files
