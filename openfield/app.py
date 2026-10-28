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
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__, peek, share
from .backends.base import Backend, BackendError
from .backends.replay import ReplayBackend, hero_reel, hero_take, showcase_gpu
from .backends.sdk import SdkBackend
from .cast import MAX_BYTES as CAST_MAX_BYTES
from .cast import MAX_REFS, CastError, CastStore, generated_origin
from .chat import MAX_MESSAGE, Chat, ChatError
from .config import Settings, get_settings
from .engine import preflight
from .engine import receipt as receipts
from .engine import rig as rigs
from .engine.audit import POLICY
from .engine.identity import FaceGate, default_model_dir, download_models
from .engine.video import VideoError
from .engine.workflows import WorkflowError
from .exports import export_reel, export_vertical
from .fsutil import read_text
from .ledger import Ledger, LedgerError, write_json
from .logging_config import configure_logging
from .pipeline import (
    PORTRAIT_MAX,
    DirectRequest,
    EditRequest,
    ExtendRequest,
    Pipeline,
    PortraitRequest,
    ReshootRequest,
    ShotsRequest,
    TransitionRequest,
    UpscaleRequest,
)
from .security import SameOriginOnly

log = configure_logging()
VIDEO_SUFFIXES = (".mp4", ".mov", ".webm", ".mkv")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
ERROR_STATUS = {
    "replay_unavailable": 409, "unauthorized": 401, "forbidden": 403, "missing_api_key": 401,
    "insufficient_credits": 402, "queue_full": 429, "unreachable": 502, "timeout": 504,
    "not_configured": 422, "not_a_proxy": 502, "http_error": 502,
}
CONNECTION_FILE = "connection.json"  # a remembered target: its address and kind, never a key
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


class DirectBody(BaseModel):
    subject: str = Field(min_length=3, max_length=800)
    rig: dict[str, Any] = Field(default_factory=dict)
    cast_id: str | None = None
    audio: str | None = Field(default=None, max_length=400)
    line: str | None = Field(default=None, max_length=rigs.LINE_MAX)  # a spoken line; the engine checks the delivery
    delivery: str = Field(default="natural", max_length=20)
    language: str | None = Field(default=None, max_length=rigs.LANGUAGE_MAX)
    action: str | None = Field(default=None, max_length=rigs.ACTION_MAX)  # what happens; the video prompt only
    seed: int | None = Field(default=None, ge=0, lt=2**31)
    orientation: Literal["landscape", "portrait"] = "landscape"
    auto_approve: bool = False
    prompt_only: bool = False
    quality: Literal["draft", "standard", "fine"] = "standard"


class PortraitBody(BaseModel):
    description: str = Field(min_length=3, max_length=400)
    count: int = Field(default=3, ge=1, le=PORTRAIT_MAX)
    seed: int | None = Field(default=None, ge=0, lt=2**31)


class CastFromTakeBody(BaseModel):
    take_id: str
    candidate: int = Field(ge=1, le=PORTRAIT_MAX)
    name: str = Field(min_length=1, max_length=40)


class ChatBody(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_MESSAGE)


class ChatChoice(BaseModel):
    lane: str | None = Field(default=None, max_length=20)  # opencode | claude | codex: another agent is a new chat
    model: str | None = Field(default=None, max_length=120)  # "" is the agent's own default


class ApproveBody(BaseModel):
    reroll: list[Annotated[int, Field(ge=0, le=7)]] = Field(default_factory=list, max_length=8)  # still indices


class VerticalBody(BaseModel):
    focus_x: float = Field(default=0.5, ge=0.0, le=1.0)


class ReelBody(BaseModel):
    take_ids: list[str] = Field(min_length=2, max_length=8)
    crossfade_s: float = Field(default=0.5, ge=0.0, le=2.0)


class EditBody(BaseModel):
    preset: str = Field(max_length=24)
    detail: str | None = Field(default=None, max_length=rigs.EDIT_DETAIL_MAX)
    take: str | None = Field(default=None, max_length=40)  # edit this finished take's still...
    still: str | None = Field(default=None, max_length=200)  # ...or one of its stills, by its path in the take
    cast_id: str | None = Field(default=None, max_length=64)  # the face or person put in, for the swaps
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)


class ShotsBody(BaseModel):
    take: str | None = Field(default=None, max_length=40)  # start from this finished take's still...
    cast_id: str | None = Field(default=None, max_length=64)  # ...checked against this cast when given
    quality: str = Field(default="standard", max_length=16)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)


class TransitionBody(BaseModel):
    first: str = Field(max_length=40)  # the take that plays first
    second: str = Field(max_length=40)  # the take the bridge lands on
    style: str = Field(default=rigs.TRANSITION_DEFAULT, max_length=24)
    seconds: int = Field(default=2, ge=min(rigs.TRANSITION_SECONDS), le=max(rigs.TRANSITION_SECONDS))
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    idea: str | None = Field(default=None, max_length=rigs.TRANSITION_IDEA_MAX + 40)  # how A becomes B (optional)


class ExtendBody(BaseModel):
    take: str = Field(max_length=40)  # the finished take to continue
    seconds: int = Field(default=3, ge=min(rigs.EXTEND_SECONDS), le=max(rigs.EXTEND_SECONDS))
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)


class UpscaleBody(BaseModel):
    take: str = Field(max_length=40)  # the finished take to enlarge
    target: str = Field(default="4k", max_length=8)  # a rig.UPSCALE_TARGETS id; the pipeline names the choices when it is not one


class TargetBody(BaseModel):
    """A render target from the Connect panel. No field constraints here: a validation error would echo the key."""

    base_url: str | None = None  # empty = Comfy Cloud
    api_key: str | None = None  # a Comfy Cloud key, or the token comfy-api-proxy was started with
    comfy_url: str | None = None  # ComfyUI itself, for the model and node check (optional)
    remember: bool = True


def clean_target(base_url: str | None, api_key: str | None, comfy_url: str | None) -> tuple[str | None, str | None, str | None]:
    """Normalised (base_url, key, comfy_url); raises ValueError with a message that never carries the key."""
    base = (base_url or "").strip()
    key = (api_key or "").strip() or None
    comfy = (comfy_url or "").strip()
    if base:
        base = preflight.check_url(base, "Proxy URL")
    if comfy:
        comfy = preflight.check_url(comfy, "ComfyUI URL")
    if key and (len(key) > 400 or any(c.isspace() for c in key)):
        raise ValueError("That does not look like a key or token (spaces, or longer than any Comfy key)")
    return base or None, key, comfy or None


def target_of(backend: SdkBackend) -> dict[str, Any]:
    """What the interface may show about a target: its kind, label, host and address, never a key or token."""
    host = urlsplit(backend.base_url).netloc if backend.base_url else "cloud.comfy.org"
    return {"kind": backend.kind, "label": backend.label, "host": host, "url": backend.base_url}


def target_warnings(base_url: str | None, api_key: str | None) -> list[str]:
    parts = urlsplit(base_url) if base_url else None
    if parts is None or (parts.hostname or "") in LOOPBACK_HOSTS:
        return []
    warnings = []
    if not api_key:
        warnings.append("This address is reachable by anyone who can reach the box, and no token was given. "
                        "Keep comfy-api-proxy behind an SSH tunnel, or start it with --token and paste the token here.")
    if parts.scheme == "http":
        warnings.append("Plain http: the token and your uploads travel unencrypted to that host.")
    return warnings


class AppState:
    def __init__(self, settings: Settings, backend: Backend | None = None) -> None:
        self.settings = settings
        self.ledger = Ledger(settings.takes_dir)
        self.ledger.recover_interrupted()
        clear_stale_uploads(settings.uploads_dir)
        self._gate: FaceGate | None = None
        self.cast = CastStore(settings.cast_dir, self.gate, shelf=[settings.showcase_dir / "cast"])
        self.replay = ReplayBackend([settings.takes_dir, settings.showcase_dir / "takes"])
        self._override = backend
        self._mode = settings.effective_backend
        self._sdk: SdkBackend | None = None
        self._source: str | None = "env" if settings.sdk_configured else None  # env | saved | session | None
        self.comfy_url: str | None = None  # ComfyUI itself, when the person gave it for the model check
        self._health: tuple[float, tuple[str, str | None], dict[str, Any]] | None = None
        if not settings.sdk_configured:
            self._restore_connection()
        self.pipeline = Pipeline(self.ledger, self.backend, settings.workflow_dir, gate=self.gate,
                                 shelves=[settings.showcase_dir / "takes"])  # a transition may join a recorded take

    def gate(self) -> FaceGate:
        if self._gate is None or not self._gate.available:
            self._gate = FaceGate()
        return self._gate

    def backend(self) -> Backend:
        if self._override is not None:
            return self._override
        if self._mode == "sdk":
            if self._sdk is None:
                self._sdk = SdkBackend.from_env()
                self._source = "env"
            return self._sdk
        return self.replay

    # -- the render target: from the environment, a remembered file, or the Connect panel --------------------------
    @property
    def configured(self) -> bool:
        """Whether a render target exists at all (the environment, a remembered address, or this session)."""
        return self._sdk is not None or self.settings.sdk_configured

    @property
    def source(self) -> str | None:
        return self._source if self.configured else None

    @property
    def connection_path(self) -> Path:
        return self.settings.data_dir / CONNECTION_FILE

    def target(self) -> dict[str, Any] | None:
        backend = self._sdk if self._sdk is not None else (SdkBackend.from_env() if self.settings.sdk_configured else None)
        return {**target_of(backend), "comfy_url": self.comfy_url} if backend is not None else None

    def _restore_connection(self) -> None:
        """A remembered target (address and kind only) is used again, like a .env would be."""
        try:
            saved = json.loads(self.connection_path.read_text(encoding="utf-8"))
            base_url, _, comfy_url = clean_target(saved.get("base_url"), None, saved.get("comfy_url"))
        except (OSError, ValueError, AttributeError):
            return
        self._sdk = SdkBackend(base_url=base_url)
        self.comfy_url = comfy_url
        self._source = "saved"
        self._mode = "sdk"

    async def test_target(self, base_url: str | None, api_key: str | None, comfy_url: str | None) -> dict[str, Any]:
        """Probe a target without switching to it; with a ComfyUI URL, also the model and node check."""
        base, key, comfy = clean_target(base_url, api_key, comfy_url)
        candidate = SdkBackend(base_url=base, api_key=key)
        result: dict[str, Any] = {"health": await candidate.health(), "target": target_of(candidate),
                                  "warnings": target_warnings(base, key), "preflight": None}
        if comfy:
            result["preflight"] = await preflight.probe_comfy(comfy, workflow_dir=self.settings.workflow_dir)
        return result

    async def connect(self, base_url: str | None, api_key: str | None, comfy_url: str | None, *,
                      remember: bool = True) -> dict[str, Any]:
        """Switch new takes to a target that answered; running takes keep the backend they started on."""
        base, key, comfy = clean_target(base_url, api_key, comfy_url)
        candidate = SdkBackend(base_url=base, api_key=key)
        health = await candidate.health()
        if not health.get("ok"):
            raise BackendError(health.get("code") or "unreachable", f"Not connected: {health.get('detail', 'no answer')}")
        self._sdk = candidate
        self.comfy_url = comfy
        self._mode = "sdk"
        self._source = "session"
        self._health = None
        if remember:
            write_json(self.connection_path, {"base_url": base, "comfy_url": comfy, "kind": candidate.kind,
                                              "label": candidate.label, "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            if os.name != "nt":
                os.chmod(self.connection_path, 0o600)
            self._source = "saved"
        return health

    def forget(self) -> None:
        """Drop the connected target and the remembered address; back to the environment's target, or Replay."""
        self.connection_path.unlink(missing_ok=True)
        self._sdk = None
        self.comfy_url = None
        self._health = None
        self._source = "env" if self.settings.sdk_configured else None
        self._mode = "sdk" if self.settings.sdk_configured else "replay"

    async def health(self) -> dict[str, Any]:
        """Backend health, cached for a few seconds so a polling UI cannot hammer the target."""
        backend = self.backend()
        now = time.monotonic()
        key = (backend.kind, getattr(backend, "base_url", None))
        if self._health and self._health[1] == key and now - self._health[0] < 8:
            return self._health[2]
        result = await backend.health()
        self._health = (now, key, result)
        return result

    def set_mode(self, mode: str) -> None:
        if mode not in {"sdk", "replay"}:
            raise ValueError("mode must be sdk or replay")
        if mode == "sdk" and not self.configured:
            raise BackendError(
                "not_configured",
                "No render target yet. Connect a GPU box or Comfy Cloud from the header, or set COMFY_BASE_URL "
                "or COMFY_API_KEY in the environment before starting.")
        self._mode = mode


def create_app(settings: Settings | None = None, *, backend: Backend | None = None) -> FastAPI:
    settings = settings or get_settings()
    state = AppState(settings, backend)
    app = FastAPI(title="OpenField Studio", version=__version__)
    app.state.openfield = state
    chat = Chat(settings.data_dir, settings.host)  # the Chat room's agent: started by the first message, never before
    app.state.chat = chat
    app.router.on_shutdown.append(chat.close)
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

    @app.exception_handler(ChatError)
    async def _chat_error(_: Request, exc: ChatError) -> JSONResponse:
        return error(exc.status, exc.code, exc.message)

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
                        "health": await state.health(), "sdk_configured": state.configured,
                        "configured": state.configured, "source": state.source, "target": state.target(),
                        "comfy_url": bool(state.comfy_url)},
            "face_check": {"available": gate.available, "reason": receipts.scrub(gate.reason)},
            "recorded_takes": len(state.replay.index()),
            "hero_take": hero_take(settings.showcase_dir),  # what the first screen shows in Replay
            "hero_reel": hero_reel(settings.showcase_dir),  # the filmstrip's order for recorded takes
            "gpu": showcase_gpu(settings.showcase_dir),  # the GPU time the recorded takes' receipts list, summed
        }

    @app.post("/api/backend")
    async def choose_backend(body: dict[str, str]) -> dict[str, Any]:
        state.set_mode(body.get("mode", ""))
        return await status()

    @app.post("/api/backend/test")
    async def test_backend(body: TargetBody) -> dict[str, Any]:
        """Probe a target the person typed; nothing switches, nothing is remembered."""
        return await state.test_target(body.base_url, body.api_key, body.comfy_url)

    @app.post("/api/backend/connect")
    async def connect_backend(body: TargetBody) -> dict[str, Any]:
        await state.connect(body.base_url, body.api_key, body.comfy_url, remember=body.remember)
        return await status()

    @app.post("/api/backend/forget")
    async def forget_backend() -> dict[str, Any]:
        state.forget()
        return await status()

    @app.post("/api/models/face")
    async def fetch_face_models() -> dict[str, Any]:
        await asyncio.to_thread(download_models, default_model_dir())
        gate = state.gate()
        return {"available": gate.available, "reason": receipts.scrub(gate.reason)}

    # -- the Chat room: the person's own agent drives the studio through its MCP tools (openfield/chat.py) ----------
    def local(request: Request) -> None:
        chat.guard(request.client.host if request.client else None)

    @app.get("/api/chat")
    async def chat_info(request: Request) -> dict[str, Any]:
        local(request)
        return chat.info()

    @app.post("/api/chat/messages", status_code=202)
    async def chat_send(request: Request, body: ChatBody) -> dict[str, Any]:
        local(request)
        return await asyncio.to_thread(chat.send, body.text, str(request.base_url).rstrip("/"))

    @app.post("/api/chat/stop")
    async def chat_stop(request: Request) -> dict[str, Any]:
        local(request)
        return await asyncio.to_thread(chat.stop)

    @app.post("/api/chat/reset")
    async def chat_reset(request: Request) -> dict[str, Any]:
        local(request)
        return await asyncio.to_thread(chat.reset)

    @app.post("/api/chat/settings")
    async def chat_settings(request: Request, body: ChatChoice) -> dict[str, Any]:
        local(request)
        return await asyncio.to_thread(chat.choose, body.lane, body.model)

    @app.get("/api/chat/events")
    async def chat_events(request: Request, since: int = 0) -> StreamingResponse:
        local(request)
        last = request.headers.get("last-event-id", "")
        start = int(last) if last.isdigit() else max(0, since)

        async def stream():
            async for event in chat.log.follow(start, keepalive=15):
                yield ": keepalive\n\n" if event is None else f"id: {event['seq']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

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
        shot = rigs.compile_shot(rig, body.subject, body.audio, prompt_only=body.prompt_only,
                                 line=body.line, delivery=body.delivery, language=body.language, action=body.action)
        templates = {}
        for name in {"qwen21_t2i", "qwen21_edit", *(s.template for s in shot.segments)}:
            try:
                pipeline.template(name)
                templates[name] = "ready"
            except WorkflowError as exc:
                templates[name] = str(exc)
        return {"plan": shot.to_dict(), "still_prompt": rigs.compile_still_prompt(rig, body.subject, one_still=shot.mode != "keyframed",
                                                                                 action=body.action),
                "templates": templates, "backend": state.backend().kind}

    @app.get("/api/direct/estimate")
    async def estimate(quality: str = "standard", movement: str = "dolly_in", duration_seconds: int = 5,
                       prompt_only: bool = False, orientation: str = "landscape", source: bool = False,
                       effect: str = "none", angle: str = "front/eye/medium") -> dict[str, Any]:
        """How long a shot of this shape took on this install's backend: measured, or null. Never a guess."""
        if state.backend().locked:
            return {"seconds": None, "low": None, "high": None, "samples": 0, "backend": state.backend().label,
                    "basis": "Replay renders nothing"}
        return pipeline.estimate_direct(quality_tier=quality, movement=movement, duration_seconds=duration_seconds,
                                        prompt_only=prompt_only, orientation=orientation, source=source, effect=effect, angle=angle)

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

    def take_folder(take_id: str) -> Path:
        """A take's folder: the ledger first, then the recorded shelf (bundled takes are served, never changed)."""
        own = ledger.take_dir(take_id)
        if (own / "take.json").is_file():
            return own
        shelf = state.replay.folder(take_id)
        if shelf is None:
            raise LedgerError(f"no such take: {take_id}")
        return shelf

    @app.get("/api/takes/{take_id}")
    async def get_take(take_id: str) -> dict[str, Any]:
        # retried like the ledger's own reads: take.json is rewritten on every progress update (Windows sharing errors)
        return json.loads(read_text(take_folder(take_id) / "take.json"))

    @app.delete("/api/takes/{take_id}", status_code=204)
    async def delete_take(take_id: str) -> Response:
        await pipeline.cancel(take_id)
        ledger.delete(take_id)
        return Response(status_code=204)

    def direct_request(body: DirectBody, **extra: Any) -> DirectRequest:
        refs, name = [], None
        if body.cast_id:
            cast = state.cast.get(body.cast_id)
            refs, name = state.cast.ref_paths(body.cast_id), cast["name"]
        return DirectRequest(
            subject=body.subject, rig=body.rig, cast_refs=refs, cast_name=name, audio=body.audio,
            line=body.line, delivery=body.delivery, language=body.language, action=body.action,
            seed=body.seed, orientation=body.orientation, auto_approve=body.auto_approve,
            prompt_only=body.prompt_only, quality=body.quality, **extra)

    @app.post("/api/takes/direct", status_code=202)
    async def start_direct(body: DirectBody) -> dict[str, Any]:
        return await pipeline.start_direct(direct_request(body))

    @app.post("/api/takes/direct/from-image", status_code=202)
    async def start_direct_from_image(request: str = Form(...), source: UploadFile = File(...)) -> dict[str, Any]:
        """The same shot, but the person's own still is the hero: `request` is the Direct body as JSON, `source` the image."""
        try:
            body = DirectBody.model_validate_json(request)
        except ValidationError as exc:
            raise HTTPException(422, f"request: {'; '.join(e.get('msg', '') for e in exc.errors()[:3])}") from None
        uploads = settings.uploads_dir
        uploads.mkdir(parents=True, exist_ok=True)
        image = await _save_upload(source, uploads, 20, IMAGE_SUFFIXES)
        try:
            return await pipeline.start_direct(direct_request(body, source=image, owned=(image,)))
        except Exception:
            image.unlink(missing_ok=True)
            raise

    @app.post("/api/takes/reshoot", status_code=202)
    async def start_reshoot(
        prompt: str = Form(...), seed: int | None = Form(None), cast_id: str | None = Form(None),
        ref_index: int = Form(1), background: str | None = Form(None), motion: str | None = Form(None),
        source: UploadFile = File(...), reference: UploadFile | None = File(None), face_only: bool = Form(False),
    ) -> dict[str, Any]:
        uploads = settings.uploads_dir
        uploads.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []  # what this request wrote; the pipeline deletes it once the take is over
        try:
            clip = await _save_upload(source, uploads, 200, VIDEO_SUFFIXES)
            saved.append(clip)
            reference_name = None
            face_refs: list[Path] = []
            if face_only:  # the face comes from a Cast (consent is recorded there); the clip's first frame is the look
                if not cast_id:
                    raise ValueError("swapping only the face needs a Cast")
                face_refs, reference_name = state.cast.ref_paths(cast_id), state.cast.get(cast_id)["name"]
                ref_path = face_refs[0]
            elif reference is not None and reference.filename:
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
                background=background, motion=motion, owned=tuple(saved), face_only=face_only, face_refs=face_refs))
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

    @app.post("/api/takes/edit", status_code=202)
    async def take_edit(request: str = Form(...), source: UploadFile | None = File(None)) -> dict[str, Any]:
        """One still changed by words: `request` is an EditBody as JSON; `source` an image, or none when it names a take."""
        try:
            body = EditBody.model_validate_json(request)
        except ValidationError as exc:
            raise HTTPException(422, f"request: {'; '.join(e.get('msg', '') for e in exc.errors()[:3])}") from None
        refs, name = [], None
        if body.cast_id:
            refs, name = state.cast.ref_paths(body.cast_id), state.cast.get(body.cast_id)["name"]
        image = None
        if source is not None:
            uploads = settings.uploads_dir
            uploads.mkdir(parents=True, exist_ok=True)
            image = await _save_upload(source, uploads, 20, IMAGE_SUFFIXES)
        try:
            return await pipeline.start_edit(EditRequest(
                preset=body.preset, detail=body.detail, source=image, take=body.take, still=body.still,
                cast_refs=refs, cast_name=name, seed=body.seed, owned=(image,) if image else ()))
        except Exception:
            if image:
                image.unlink(missing_ok=True)
            raise

    @app.post("/api/takes/shots", status_code=202)
    async def take_shots(request: str = Form("{}"), source: UploadFile | None = File(None)) -> dict[str, Any]:
        """One still re-shot as a board of nine setups: `request` is a ShotsBody as JSON; `source` an image, or none
        when the body names a take to start from."""
        try:
            body = ShotsBody.model_validate_json(request)
        except ValidationError as exc:
            raise HTTPException(422, f"request: {'; '.join(e.get('msg', '') for e in exc.errors()[:3])}") from None
        refs, name = [], None
        if body.cast_id:
            refs, name = state.cast.ref_paths(body.cast_id), state.cast.get(body.cast_id)["name"]
        image = None
        if source is not None:
            uploads = settings.uploads_dir
            uploads.mkdir(parents=True, exist_ok=True)
            image = await _save_upload(source, uploads, 20, IMAGE_SUFFIXES)
        try:
            return await pipeline.start_shots(ShotsRequest(
                source=image, take=body.take, cast_refs=refs, cast_name=name, seed=body.seed, quality=body.quality,
                owned=(image,) if image else ()))
        except Exception:
            if image:
                image.unlink(missing_ok=True)
            raise

    @app.post("/api/takes/transition", status_code=202)
    async def take_transition(body: TransitionBody) -> dict[str, Any]:
        return await pipeline.start_transition(TransitionRequest(
            first=body.first, second=body.second, style=body.style, seconds=body.seconds, seed=body.seed, idea=body.idea))

    @app.post("/api/takes/extend", status_code=202)
    async def take_extend(body: ExtendBody) -> dict[str, Any]:
        return await pipeline.start_extend(ExtendRequest(
            take=body.take, seconds=body.seconds, seed=body.seed))

    @app.post("/api/takes/upscale", status_code=202)
    async def take_upscale(body: UpscaleBody) -> dict[str, Any]:
        return await pipeline.start_upscale(UpscaleRequest(take=body.take, target=body.target))

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
    async def take_media(take_id: str, path: str, w: int | None = None) -> Response:
        """A file of a take; an image with ?w= comes back as a JPEG that wide at most (a preview for slow links)."""
        file = ledger.file_in(take_folder(take_id), path)
        if w is not None and file.suffix.lower() in IMAGE_SUFFIXES:
            try:
                return Response(await asyncio.to_thread(peek.thumbnail_jpeg, file, w), media_type="image/jpeg")
            except OSError as exc:
                return error(422, "preview_failed", f"could not shrink {file.name}: {type(exc).__name__}")
        return FileResponse(file, media_type=mimetypes.guess_type(file.name)[0] or "application/octet-stream")

    strips: dict[tuple[str, int, int, int], bytes] = {}  # a small cache: a take's video never changes once finished
    strip_slots = asyncio.Semaphore(2)  # each strip is up to 12 ffmpeg runs; two at a time

    @app.get("/api/takes/{take_id}/strip.jpg")
    async def take_strip(take_id: str, frames: int = 6, w: int = 256) -> Response:
        """Frames spread across the take's video, three to a row: what happens in it, in one small JPEG."""
        clip = ledger.file_in(take_folder(take_id), "take.mp4")
        frames, w = max(1, min(frames, peek.STRIP_MAX_FRAMES)), max(96, min(w, 640))
        key = (str(clip), clip.stat().st_mtime_ns, frames, w)
        if key not in strips:
            async with strip_slots:
                try:
                    data = await asyncio.to_thread(peek.strip_jpeg, clip, frames, w)
                except (OSError, VideoError) as exc:
                    return error(422, "preview_failed", f"could not read frames from the take: {type(exc).__name__}")
            if len(strips) >= 64:
                strips.pop(next(iter(strips)))
            strips[key] = data
        return Response(strips[key], media_type="image/jpeg")

    @app.get("/api/takes/{take_id}/receipt")
    async def take_receipt(take_id: str) -> dict[str, Any]:
        return share.read_receipt_view(ledger.file_in(take_folder(take_id), "receipt.json"))

    @app.get("/api/takes/{take_id}/workflows.zip")
    async def take_workflows(take_id: str) -> Response:
        return Response(share.workflows_zip(take_folder(take_id)), media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="{take_id}-workflows.zip"'})

    @app.get("/api/takes/{take_id}/sdk-snippet")
    async def sdk_snippet(take_id: str) -> Response:
        snippet = share.take_snippet(take_folder(take_id))
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

    @app.middleware("http")
    async def revalidate_the_interface(request: Request, call_next):
        # The interface is ES modules with no build step and no hashed names: a browser that kept yesterday's copy of
        # one module next to today's copy of another breaks on an import. `no-cache` keeps the files cached but makes
        # the browser ask first (ETag, so a 304 is the usual answer); recorded media stays cacheable as before.
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.endswith((".html", ".js", ".css", ".json")) and not path.startswith(("/api/", "/showcase/")):
            response.headers["Cache-Control"] = "no-cache"
        return response

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
