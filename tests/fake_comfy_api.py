"""A small fake of the Comfy API v2 (assets, jobs, SSE) for tests and UI development.

It speaks the real wire protocol, so the real `comfy-sdk` runs against it unchanged. It can mimic
the self-hosted proxy's quirks (videos reported as `type="image"`, `size_bytes=0`, no hash) and
inject failures. Outputs are synthetic test patterns: this is NEVER a substitute for a real render.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import imageio_ffmpeg
import uvicorn
from blake3 import blake3
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from PIL import Image, ImageDraw

OUTPUT_CLASSES = {"SaveVideo", "SaveImage", "SaveImageAdvanced"}
TERMINAL = {"succeeded", "failed", "canceled", "expired"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _png_bytes(label: str) -> bytes:
    img = Image.new("RGB", (320, 180), (24, 28, 36))
    ImageDraw.Draw(img).text((12, 12), f"FAKE {label}", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 36), (90, 120, 200)).save(buf, "JPEG")
    return buf.getvalue()


def _mp4_bytes(tmp: Path) -> bytes:
    out = tmp / "fake.mp4"
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out),
        ],
        check=True,
    )
    return out.read_bytes()


class FakeJob:
    def __init__(self, workflow: dict[str, Any], key: str | None, assets_used: list[str]) -> None:
        self.id = str(uuid.uuid4())
        self.workflow = workflow
        self.key = key
        self.assets_used = assets_used
        self.status = "queued"
        self.created_at = _now()
        self.started_at: datetime | None = None
        self.completed_at: datetime | None = None
        self.progress: dict[str, Any] | None = None
        self.outputs: list[dict[str, Any]] = []
        self.error: dict[str, Any] | None = None
        self.frames: list[tuple[str, dict[str, Any]]] = []
        self.cancel_requested = False

    def to_json(self) -> dict[str, Any]:
        base = f"/api/v2/jobs/{self.id}"
        return {
            "id": self.id, "status": self.status, "created_at": _iso(self.created_at),
            "started_at": _iso(self.started_at) if self.started_at else None,
            "completed_at": _iso(self.completed_at) if self.completed_at else None,
            "expires_at": _iso(self.created_at + timedelta(hours=1)),
            "queue_position": 1 if self.status == "queued" else None,
            "progress": self.progress, "outputs": self.outputs, "error": self.error,
            "metrics": {"queue_ms": 5, "execution_ms": 40 if self.completed_at else None},
            "urls": {"self": base, "events": f"{base}/events", "cancel": f"{base}/cancel"},
        }


class FakeComfyApi:
    """In-process Comfy API v2. Use `start()` / `stop()` or the pytest fixture in conftest."""

    def __init__(self, *, token: str | None = None, delay: float = 0.15, previews: bool = True,
                 proxy_quirks: bool = True, tmp: Path | None = None) -> None:
        self.token = token
        self.delay = delay
        self.previews = previews
        self.proxy_quirks = proxy_quirks
        self.fail_with: dict[str, Any] | None = None
        self.end_with: str | None = None  # "expired" or "canceled": end the job in that terminal state
        self.reject_next_submit: tuple[int, str, str] | None = None
        self.assets: dict[str, dict[str, Any]] = {}
        self.blobs: dict[str, bytes] = {}
        self.by_hash: dict[str, str] = {}
        self.jobs: dict[str, FakeJob] = {}
        self.idempotency: set[str] = set()
        self.uploads: list[str] = []
        self._tmp = tmp or Path(".")
        self._mp4: bytes | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.port = 0
        self.app = self._build()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    # -- lifecycle ----------------------------------------------------------------------
    def start(self) -> str:
        config = uvicorn.Config(self.app, host="127.0.0.1", port=0, log_level="error")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self._server.started and self._server.servers:
                self.port = self._server.servers[0].sockets[0].getsockname()[1]
                return self.base_url
            time.sleep(0.02)
        raise RuntimeError("fake Comfy API did not start")

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)

    # -- helpers --------------------------------------------------------------------------
    def _asset_json(self, asset_id: str, created_new: bool) -> dict[str, Any]:
        rec = self.assets[asset_id]
        return {
            "id": asset_id, "hash": rec.get("hash"), "size_bytes": rec["size_bytes"],
            "content_type": rec["content_type"], "file_path": rec.get("file_path"),
            "created_new": created_new, "created_at": _iso(_now()),
            "url": f"{self.base_url}/api/v2/assets/{asset_id}/content",
            "url_expires_at": _iso(_now() + timedelta(hours=1)),
        }

    def _store(self, data: bytes, content_type: str, file_path: str, with_hash: bool = True) -> str:
        digest = f"blake3:{blake3(data).hexdigest()}"
        if with_hash and digest in self.by_hash:
            return self.by_hash[digest]
        asset_id = str(uuid.uuid4())
        self.blobs[asset_id] = data
        self.assets[asset_id] = {
            "hash": digest if with_hash else None, "size_bytes": len(data),
            "content_type": content_type, "file_path": file_path,
        }
        if with_hash:
            self.by_hash[digest] = asset_id
        return asset_id

    def _output_bytes(self, cls: str, label: str) -> tuple[bytes, str, str]:
        if cls == "SaveVideo":
            if self._mp4 is None:
                self._mp4 = _mp4_bytes(self._tmp)
            return self._mp4, "video/mp4", "fake_00001_.mp4"
        return _png_bytes(label), "image/png", "fake_00001_.png"

    @staticmethod
    def _asset_refs(node: Any) -> list[str]:
        found: list[str] = []
        if isinstance(node, dict):
            if node.get("__type") == "core/ASSET":
                found.append((node.get("info") or {}).get("id", ""))
            for value in node.values():
                found.extend(FakeComfyApi._asset_refs(value))
        elif isinstance(node, list):
            for value in node:
                found.extend(FakeComfyApi._asset_refs(value))
        return found

    async def _simulate(self, job: FakeJob) -> None:
        def frame(event: str, data: dict[str, Any]) -> None:
            job.frames.append((event, data))

        frame("status", {"status": "queued", "queue_position": 1})
        await asyncio.sleep(self.delay)
        job.status, job.started_at = "running", _now()
        frame("status", {"status": "running"})
        total = max(1, len(job.workflow))
        for step in range(1, 5):
            if job.cancel_requested:
                job.status, job.completed_at = "canceled", _now()
                frame("status", {"status": "canceled"})
                return
            await asyncio.sleep(self.delay)
            job.progress = {
                "value": step / 4, "nodes_done": step * total // 4, "nodes_total": total,
                "current_node": next(iter(job.workflow), None), "step": step, "steps": 4,
                "message": f"step {step}/4",
            }
            frame("progress", job.progress)
            if self.previews and step == 2:
                frame("preview", {
                    "node_id": next(iter(job.workflow), ""), "content_type": "image/jpeg",
                    "data_base64": base64.b64encode(_jpeg_bytes()).decode(),
                })
        if self.end_with:
            job.status, job.completed_at = self.end_with, _now()
            frame("status", {"status": self.end_with})
            return
        if self.fail_with:
            job.error = dict(self.fail_with)
            job.status, job.completed_at = "failed", _now()
            frame("status", {"status": "failed"})
            return
        for node_id, node in job.workflow.items():
            cls = node.get("class_type")
            if cls not in OUTPUT_CLASSES:
                continue
            data, ctype, name = self._output_bytes(cls, node_id)
            asset_id = self._store(data, ctype, name, with_hash=not self.proxy_quirks)
            kind = "image" if (self.proxy_quirks or cls != "SaveVideo") else "video"
            if cls == "SaveImage" or cls == "SaveImageAdvanced":
                kind = "image"
            out = {
                "node_id": node_id, "name": name, "type": kind, "content_type": ctype,
                "size_bytes": 0 if self.proxy_quirks else len(data), "id": asset_id,
                "hash": None if self.proxy_quirks else self.assets[asset_id]["hash"],
                "url": f"{self.base_url}/api/v2/assets/{asset_id}/content",
                "url_expires_at": _iso(_now() + timedelta(hours=1)), "job_id": job.id,
            }
            job.outputs.append(out)
            frame("output", out)
        job.status, job.completed_at = "succeeded", _now()
        frame("status", {"status": "succeeded"})

    def _error(self, status: int, code: str, message: str, **headers: str) -> JSONResponse:
        return JSONResponse({"error": {"code": code, "message": message}}, status, headers=headers)

    # -- routes ---------------------------------------------------------------------------
    def _build(self) -> FastAPI:
        app = FastAPI()
        api = "/api/v2"

        @app.middleware("http")
        async def auth(request: Request, call_next):
            if self.token and request.url.path != f"{api}/health":
                if request.headers.get("authorization") != f"Bearer {self.token}":
                    return self._error(401, "unauthorized", "missing or wrong bearer token")
            return await call_next(request)

        @app.get(f"{api}/health")
        async def health():
            return {"status": "ok"}

        @app.api_route(f"{api}/assets/by-hash/{{digest:path}}", methods=["HEAD"])
        async def head_hash(digest: str):
            return Response(status_code=200 if digest in self.by_hash else 404)

        @app.post(f"{api}/assets")
        async def post_asset(
            file: UploadFile = File(...), content_type: str = Form(...),
            file_path: str = Form(...), expected_hash: str | None = Form(None),
        ):
            data = await file.read()
            self.uploads.append(file_path)
            asset_id = self._store(data, content_type, file_path)
            return JSONResponse(self._asset_json(asset_id, True), 201)

        @app.post(f"{api}/assets/from-hash")
        async def from_hash(request: Request):
            body = await request.json()
            asset_id = self.by_hash.get(body.get("hash", ""))
            if asset_id is None:
                return self._error(404, "blob_not_found", "no such blob")
            return JSONResponse(self._asset_json(asset_id, False), 200)

        @app.get(f"{api}/assets/{{asset_id}}")
        async def get_asset(asset_id: str):
            if asset_id not in self.assets:
                return self._error(404, "not_found", "no such asset")
            return self._asset_json(asset_id, False)

        @app.get(f"{api}/assets/{{asset_id}}/content")
        async def asset_content(asset_id: str):
            if asset_id not in self.blobs:
                return self._error(404, "not_found", "no such asset")
            return Response(self.blobs[asset_id], media_type=self.assets[asset_id]["content_type"])

        @app.post(f"{api}/jobs")
        async def post_job(request: Request):
            if self.reject_next_submit:
                status, code, message = self.reject_next_submit
                self.reject_next_submit = None
                return self._error(status, code, message)
            body = await request.json()
            workflow = body.get("workflow") or {}
            if "nodes" in workflow and "links" in workflow:
                return self._error(422, "workflow_format_ui", "UI-format workflow")
            key = request.headers.get("idempotency-key")
            if key and key in self.idempotency:
                return self._error(422, "idempotency_key_reuse", "key already used")
            refs = self._asset_refs(workflow)
            missing = [r for r in refs if r not in self.assets]
            if missing:
                return self._error(422, "missing_asset", f"unknown asset {missing[0]}")
            if key:
                self.idempotency.add(key)
            job = FakeJob(workflow, key, refs)
            self.jobs[job.id] = job
            asyncio.create_task(self._simulate(job))
            return JSONResponse(job.to_json(), 201)

        @app.get(f"{api}/jobs/{{job_id}}")
        async def get_job(job_id: str):
            job = self.jobs.get(job_id)
            return job.to_json() if job else self._error(404, "not_found", "no such job")

        @app.post(f"{api}/jobs/{{job_id}}/cancel")
        async def cancel(job_id: str):
            job = self.jobs.get(job_id)
            if not job:
                return self._error(404, "not_found", "no such job")
            job.cancel_requested = True
            if job.status not in TERMINAL:
                job.status = "canceling"
            return job.to_json()

        @app.get(f"{api}/jobs/{{job_id}}/workflow")
        async def job_workflow(job_id: str):
            job = self.jobs.get(job_id)
            if not job:
                return self._error(404, "not_found", "no such job")
            return {"workflow": job.workflow, "format": "api"}

        @app.get(f"{api}/jobs/{{job_id}}/events")
        async def events(job_id: str):
            job = self.jobs.get(job_id)
            if not job:
                return self._error(404, "not_found", "no such job")

            async def stream():
                index = 0
                while True:
                    while index < len(job.frames):
                        name, data = job.frames[index]
                        index += 1
                        yield f"event: {name}\ndata: {json.dumps(data)}\n\n"
                    if job.status in TERMINAL and index >= len(job.frames):
                        return
                    await asyncio.sleep(0.02)

            return StreamingResponse(stream(), media_type="text/event-stream")

        return app
