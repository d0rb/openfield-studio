"""HTTP API and static UI.

Everything the browser does goes through here. Long work (Direct, Re-shoot) runs in the pipeline
and is observed over Server-Sent Events; nothing here blocks on a render.
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import secrets
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__, share
from .backends.base import Backend, BackendError
from .backends.replay import ReplayBackend
from .backends.sdk import SdkBackend
from .cast import MAX_BYTES as CAST_MAX_BYTES
from .cast import MAX_REFS, CastError, CastStore, generated_origin
from .config import Settings, get_settings
from .engine import receipt as receipts
from .engine import rig as rigs
from .engine.audit import POLICY
from .engine.identity import FaceGate, default_model_dir, download_models
from .engine.workflows import WorkflowError
from .exports import export_reel, export_vertical
from .ledger import Ledger, LedgerError
from .logging_config import configure_logging
from .pipeline import PORTRAIT_MAX, DirectRequest, Pipeline, PortraitRequest, ReshootRequest
from .security import SameOriginOnly

log = configure_logging()
VIDEO_SUFFIXES = (".mp4", ".mov", ".webm", ".mkv")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
ERROR_STATUS = {
    "replay_unavailable": 409, "unauthorized": 401, "forbidden": 403, "missing_api_key": 401,
    "insufficient_credits": 402, "queue_full": 429, "unreachable": 502, "timeout": 504,
}


class DirectBody(BaseModel):
    subject: str = Field(min_length=3, max_length=800)
    rig: dict[str, Any] = Field(default_factory=dict)
    cast_id: str | None = None
    audio: str | None = Field(default=None, max_length=400)
    seed: int | None = Field(default=None, ge=0, lt=2**31)
    orientation: Literal["landscape", "portrait"] = "landscape"
    auto_approve: bool = False
    prompt_only: bool = False


class PortraitBody(BaseModel):
    description: str = Field(min_length=3, max_length=400)
    count: int = Field(default=3, ge=1, le=PORTRAIT_MAX)
    seed: int | None = Field(default=None, ge=0, lt=2**31)


class CastFromTakeBody(BaseModel):
    take_id: str
    candidate: int = Field(ge=1, le=PORTRAIT_MAX)
    name: str = Field(min_length=1, max_length=40)


class ApproveBody(BaseModel):
    reroll: list[int] = Field(default_factory=list)


class VerticalBody(BaseModel):
    focus_x: float = Field(default=0.5, ge=0.0, le=1.0)


class ReelBody(BaseModel):
    take_ids: list[str] = Field(min_length=2, max_length=8)
    crossfade_s: float = Field(default=0.5, ge=0.0, le=2.0)


class AppState:
    def __init__(self, settings: Settings, backend: Backend | None = None) -> None:
        self.settings = settings
        self.ledger = Ledger(settings.takes_dir)
        self.ledger.recover_interrupted()
        clear_stale_uploads(settings.uploads_dir)
        self._gate: FaceGate | None = None
        self.cast = CastStore(settings.cast_dir, self.gate)
        self.replay = ReplayBackend([settings.takes_dir, settings.showcase_dir / "takes"])
        self._override = backend
        self._mode = settings.effective_backend
        self._sdk: SdkBackend | None = None
        self._health: tuple[float, str, dict[str, Any]] | None = None
        self.pipeline = Pipeline(self.ledger, self.backend, settings.workflow_dir, gate=self.gate)

    def gate(self) -> FaceGate:
        if self._gate is None or not self._gate.available:
            self._gate = FaceGate()
        return self._gate

    def backend(self) -> Backend:
        if self._override is not None:
            return self._override
        if self._mode == "sdk":
            self._sdk = self._sdk or SdkBackend.from_env()
            return self._sdk
        return self.replay

    async def health(self) -> dict[str, Any]:
        """Backend health, cached for a few seconds so a polling UI cannot hammer the target."""
        backend = self.backend()
        now = time.monotonic()
        if self._health and self._health[1] == backend.kind and now - self._health[0] < 8:
            return self._health[2]
        result = await backend.health()
        self._health = (now, backend.kind, result)
        return result

    def set_mode(self, mode: str) -> None:
        if mode not in {"sdk", "replay"}:
            raise ValueError("mode must be sdk or replay")
        if mode == "sdk" and not self.settings.sdk_configured:
            raise BackendError(
                "not_configured",
                "No Comfy target is configured. Set COMFY_BASE_URL (a GPU box) or COMFY_API_KEY "
                "(Comfy Cloud) in the environment or a .env file, then restart.")
        self._mode = mode
        self._sdk = None


def create_app(settings: Settings | None = None, *, backend: Backend | None = None) -> FastAPI:
    settings = settings or get_settings()
    state = AppState(settings, backend)
    app = FastAPI(title="OpenField Studio", version=__version__)
    app.state.openfield = state
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver", *_extra_hosts()],
    )
    app.add_middleware(SameOriginOnly, allowed_origins=_extra_origins())
    ledger, pipeline = state.ledger, state.pipeline

    # -- errors ------------------------------------------------------------------------------
    def error(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
        return JSONResponse({"error": {"code": code, "message": message, **extra}}, status)

    @app.exception_handler(BackendError)
    async def _backend_error(_: Request, exc: BackendError) -> JSONResponse:
        return JSONResponse({"error": exc.to_dict()}, ERROR_STATUS.get(exc.code, 502))

    @app.exception_handler(WorkflowError)
    async def _workflow_error(_: Request, exc: WorkflowError) -> JSONResponse:
        return error(503, "workflow_unavailable", str(exc))

    @app.exception_handler(LedgerError)
    async def _ledger_error(_: Request, exc: LedgerError) -> JSONResponse:
        return error(404, "not_found", str(exc))

    @app.exception_handler(CastError)
    async def _cast_error(_: Request, exc: CastError) -> JSONResponse:
        return error(422, "invalid_cast", str(exc))

    @app.exception_handler(ValueError)
    async def _value_error(_: Request, exc: ValueError) -> JSONResponse:
        return error(422, "invalid_request", str(exc))

    @app.exception_handler(TypeError)
    async def _type_error(_: Request, exc: TypeError) -> JSONResponse:
        return error(422, "invalid_request", str(exc))

    # -- status ------------------------------------------------------------------------------
    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        backend_ = state.backend()
        gate = state.gate()
        return {
            "app": "openfield-studio", "version": __version__, "policy": POLICY,
            "backend": {"kind": backend_.kind, "label": backend_.label, "locked": backend_.locked,
                        "health": await state.health(), "sdk_configured": settings.sdk_configured},
            "face_check": {"available": gate.available, "reason": receipts.scrub(gate.reason)},
            "recorded_takes": len(state.replay.index()),
        }

    @app.post("/api/backend")
    async def choose_backend(body: dict[str, str]) -> dict[str, Any]:
        state.set_mode(body.get("mode", ""))
        return await status()

    @app.post("/api/models/face")
    async def fetch_face_models() -> dict[str, Any]:
        await asyncio.to_thread(download_models, default_model_dir())
        gate = state.gate()
        return {"available": gate.available, "reason": receipts.scrub(gate.reason)}

    @app.get("/api/moves")
    async def moves() -> dict[str, Any]:
        return rigs.catalog()

    @app.get("/api/replay/recorded")
    async def recorded() -> list[dict[str, Any]]:
        return state.replay.recorded({
            settings.showcase_dir / "takes": "/showcase/takes/{id}",
            settings.takes_dir: "/api/takes/{id}/media",
        })

    @app.post("/api/replay/recreate", status_code=202)
    async def recreate(body: dict[str, str]) -> dict[str, Any]:
        return await pipeline.recreate(body.get("id", ""))

    # -- planning ------------------------------------------------------------------------------
    @app.post("/api/direct/plan")
    async def plan(body: DirectBody) -> dict[str, Any]:
        rig = rigs.CameraRig(**body.rig)
        shot = rigs.compile_shot(rig, body.subject, body.audio, prompt_only=body.prompt_only)
        templates = {}
        for name in {"qwen21_t2i", "qwen21_edit", *(s.template for s in shot.segments)}:
            try:
                pipeline.template(name)
                templates[name] = "ready"
            except WorkflowError as exc:
                templates[name] = str(exc)
        return {"plan": shot.to_dict(), "still_prompt": rigs.compile_still_prompt(rig, body.subject),
                "templates": templates, "backend": state.backend().kind}

    # -- cast ----------------------------------------------------------------------------------
    @app.get("/api/cast")
    async def list_cast() -> list[dict[str, Any]]:
        return state.cast.list()

    @app.post("/api/cast", status_code=201)
    async def create_cast(
        name: str = Form(...), kind: str = Form("character"), consent: str = Form(...),
        files: list[UploadFile] = File(...),
    ) -> dict[str, Any]:
        if len(files) > MAX_REFS:
            raise CastError(f"add between 1 and {MAX_REFS} images")
        images = []
        for upload in files:  # never read more than the limit into memory
            data = await upload.read(CAST_MAX_BYTES + 1)
            if len(data) > CAST_MAX_BYTES:
                raise CastError(f"{upload.filename}: larger than {CAST_MAX_BYTES // (1024 * 1024)} MB")
            images.append((upload.filename or "image", data))
        return await asyncio.to_thread(state.cast.create, name, kind, consent, images)

    @app.post("/api/cast/generate", status_code=202)
    async def generate_cast(body: PortraitBody) -> dict[str, Any]:
        return await pipeline.start_portrait(PortraitRequest(**body.model_dump()))

    @app.post("/api/cast/from-take", status_code=201)
    async def cast_from_take(body: CastFromTakeBody) -> dict[str, Any]:
        take = ledger.read(body.take_id)
        if take.get("kind") != "portrait" or take.get("status") != "succeeded":
            raise ValueError("pick a candidate from a finished generated-character take")
        image = ledger.media_path(body.take_id, f"candidates/{body.candidate:02d}.png")
        receipt = json.loads(ledger.media_path(body.take_id, "receipt.json").read_text(encoding="utf-8"))
        origin = generated_origin(take, receipt, body.candidate)
        return await asyncio.to_thread(
            state.cast.create, body.name, "character", "fictional", [(image.name, image.read_bytes())], origin)

    @app.delete("/api/cast/{cast_id}", status_code=204)
    async def delete_cast(cast_id: str) -> Response:
        state.cast.delete(cast_id)
        return Response(status_code=204)

    @app.get("/api/cast/{cast_id}/refs/{filename}")
    async def cast_ref(cast_id: str, filename: str) -> FileResponse:
        return FileResponse(state.cast.ref_file(cast_id, filename), media_type="image/png")

    # -- takes ---------------------------------------------------------------------------------
    @app.get("/api/takes")
    async def list_takes(kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return ledger.list(kind=kind, limit=min(limit, 500))

    @app.get("/api/takes/{take_id}")
    async def get_take(take_id: str) -> dict[str, Any]:
        return ledger.read(take_id)

    @app.delete("/api/takes/{take_id}", status_code=204)
    async def delete_take(take_id: str) -> Response:
        await pipeline.cancel(take_id)
        ledger.delete(take_id)
        return Response(status_code=204)

    @app.post("/api/takes/direct", status_code=202)
    async def start_direct(body: DirectBody) -> dict[str, Any]:
        refs, name = [], None
        if body.cast_id:
            cast = state.cast.get(body.cast_id)
            refs, name = state.cast.ref_paths(body.cast_id), cast["name"]
        return await pipeline.start_direct(DirectRequest(
            subject=body.subject, rig=body.rig, cast_refs=refs, cast_name=name, audio=body.audio,
            seed=body.seed, orientation=body.orientation, auto_approve=body.auto_approve,
            prompt_only=body.prompt_only))

    @app.post("/api/takes/reshoot", status_code=202)
    async def start_reshoot(
        prompt: str = Form(...), seed: int | None = Form(None), cast_id: str | None = Form(None),
        ref_index: int = Form(1), background: str | None = Form(None), motion: str | None = Form(None),
        source: UploadFile = File(...), reference: UploadFile | None = File(None),
    ) -> dict[str, Any]:
        uploads = settings.uploads_dir
        uploads.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []  # what this request wrote; the pipeline deletes it once the take is over
        try:
            clip = await _save_upload(source, uploads, 200, VIDEO_SUFFIXES)
            saved.append(clip)
            reference_name = None
            if reference is not None and reference.filename:
                ref_path = await _save_upload(reference, uploads, 20, IMAGE_SUFFIXES)
                saved.append(ref_path)
            elif cast_id:
                cast = state.cast.get(cast_id)
                paths = state.cast.ref_paths(cast_id)
                if not 1 <= ref_index <= len(paths):
                    raise ValueError(f"this cast has {len(paths)} reference image(s)")
                ref_path, reference_name = paths[ref_index - 1], cast["name"]
            else:
                raise ValueError("add a reference image or pick a cast")
            return await pipeline.start_reshoot(ReshootRequest(
                source=clip, reference=ref_path, prompt=prompt, seed=seed, reference_name=reference_name,
                background=background, motion=motion, owned=tuple(saved)))
        except BaseException:
            for path in saved:  # a refused request must not leave the person's footage on disk
                path.unlink(missing_ok=True)
            raise

    @app.post("/api/takes/{take_id}/approve")
    async def approve(take_id: str, body: ApproveBody) -> dict[str, Any]:
        pipeline.approve(take_id, body.reroll)
        return ledger.read(take_id)

    @app.post("/api/takes/{take_id}/cancel")
    async def cancel(take_id: str) -> dict[str, Any]:
        ledger.read(take_id)
        await pipeline.cancel(take_id)
        return ledger.read(take_id)

    @app.post("/api/takes/{take_id}/export/vertical", status_code=201)
    async def export_9x16(take_id: str, body: VerticalBody) -> dict[str, Any]:
        return await export_vertical(ledger, take_id, focus_x=body.focus_x)

    @app.post("/api/exports/reel", status_code=201)
    async def make_reel(body: ReelBody) -> dict[str, Any]:
        return await export_reel(ledger, body.take_ids, crossfade_s=body.crossfade_s)

    @app.get("/api/takes/{take_id}/events")
    async def take_events(take_id: str) -> StreamingResponse:
        ledger.read(take_id)

        async def stream():
            # a client that goes away cancels this generator; subscribe() cleans up after itself
            async for event in pipeline.subscribe(take_id, keepalive=15):
                yield ": keepalive\n\n" if event is None else f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/takes/{take_id}/media/{path:path}")
    async def take_media(take_id: str, path: str) -> FileResponse:
        file = ledger.media_path(take_id, path)
        return FileResponse(file, media_type=mimetypes.guess_type(file.name)[0] or "application/octet-stream")

    @app.get("/api/takes/{take_id}/receipt")
    async def take_receipt(take_id: str) -> dict[str, Any]:
        return share.read_receipt_view(ledger.media_path(take_id, "receipt.json"))

    @app.get("/api/takes/{take_id}/workflows.zip")
    async def take_workflows(take_id: str) -> Response:
        ledger.read(take_id)
        return Response(share.workflows_zip(ledger.take_dir(take_id)), media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="{take_id}-workflows.zip"'})

    @app.get("/api/takes/{take_id}/sdk-snippet")
    async def sdk_snippet(take_id: str) -> Response:
        ledger.read(take_id)
        snippet = share.take_snippet(ledger.take_dir(take_id))
        if snippet is None:
            raise LedgerError("this take has no recorded workflow")
        return Response(snippet, media_type="text/plain; charset=utf-8")

    @app.post("/api/receipts/import")
    async def import_receipt(file: UploadFile = File(...)) -> dict[str, Any]:
        tmp = settings.uploads_dir
        tmp.mkdir(parents=True, exist_ok=True)
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".mp4", ".png", ".json"}:
            raise ValueError("drop an OpenField .mp4, .png or receipt .json")
        path = await _save_upload(file, tmp, 300, (suffix,))
        try:
            found = await asyncio.to_thread(receipts.read_media, path)
        finally:
            path.unlink(missing_ok=True)
        if found is None:
            raise ValueError("no OpenField receipt found in that file (social sites strip metadata)")
        receipt, verified = found
        recipe = receipts.recipe_from_receipt(receipt)
        take = receipt.get("take")
        label = take.get("label") if isinstance(take, dict) else None
        return {"verified": verified, "recipe": recipe, "recipe_link": receipts.recipe_link(recipe),
                "label": label if isinstance(label, str) else None}

    # -- UI ------------------------------------------------------------------------------------
    @app.get("/static/manifest.json", include_in_schema=False)
    async def not_the_hosted_replay() -> dict[str, bool]:
        """The page asks this once, to learn whether it is the hosted Replay. Answering quietly (instead of 404)
        keeps a red error out of the browser console of the live app."""
        return {"static": False}

    @app.get("/dashboard", include_in_schema=False)
    async def old_dashboard() -> RedirectResponse:
        return RedirectResponse("/")

    if settings.web_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")
    return app


def _extra_hosts() -> list[str]:
    return [h.strip() for h in os.environ.get("OPENFIELD_ALLOWED_HOSTS", "").split(",") if h.strip()]


def _extra_origins() -> list[str]:
    """Extra web origins allowed to make changes, for a reverse proxy (OPENFIELD_ALLOWED_ORIGINS)."""
    return [o.strip() for o in os.environ.get("OPENFIELD_ALLOWED_ORIGINS", "").split(",") if o.strip()]


def clear_stale_uploads(folder: Path, max_age_s: float = 24 * 3600) -> int:
    """Delete uploads a crashed or abandoned request left behind; returns how many."""
    removed = 0
    if folder.is_dir():
        cutoff = time.time() - max_age_s
        for path in folder.iterdir():
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
    return removed


async def _save_upload(upload: UploadFile, folder: Path, limit_mb: int, suffixes: tuple[str, ...]) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in suffixes:
        raise HTTPException(422, f"{suffix or 'that file'} is not one of {', '.join(suffixes)}")
    dest = folder / f"{secrets.token_hex(6)}{suffix}"
    size = 0
    with dest.open("wb") as handle:
        while chunk := await upload.read(1 << 20):
            size += len(chunk)
            if size > limit_mb << 20:
                handle.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"larger than {limit_mb} MB")
            handle.write(chunk)
    return dest
