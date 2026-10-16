from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import settings
from .logging_config import configure_logging
from .platform import PlatformClient, PlatformError
from .services.camera_compiler import CameraRig, compile_rig
from .services.job_service import JobStore
from .services.openjutsu_service import OpenJutsuRequest, build_openjutsu_workflow, required_nodes

log = configure_logging()
app = FastAPI(title="OpenField Studio", version="0.1.0")
jobs = JobStore()
dashboard_dir = Path(__file__).parent / "dashboard"
app.mount("/dashboard", StaticFiles(directory=dashboard_dir, html=True), name="dashboard")


class CinemaRequest(BaseModel):
    subject_prompt: str = Field(min_length=3, max_length=3000)
    rig: dict[str, Any] = Field(default_factory=dict)


class OpenJutsuInput(BaseModel):
    source_video: str
    references: list[str] = Field(min_length=1, max_length=8)
    prompt: str = ""
    backend: str = "ltx"
    duration_seconds: float = Field(default=5, ge=4, le=30)
    preserve_audio: bool = True
    mode: str = "motion_transfer"


class JobInput(BaseModel):
    kind: str
    workflow: dict[str, Any]
    assets: dict[str, str] = Field(default_factory=dict)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return PlatformClient().health()


@app.get("/api/catalog")
def catalog() -> dict[str, Any]:
    return {
        "name": "OpenField Studio",
        "execution_mode": settings.execution_mode,
        "open_weights_only": settings.open_weights_only,
        "camera_moves": 35,
        "backends": ["ltx", "minimax_h3"],
        "workspaces": ["cinema", "openjutsu", "soul_id", "timeline"],
    }


@app.post("/api/cinema/compile")
def cinema_compile(request: CinemaRequest) -> dict[str, Any]:
    try:
        rig = CameraRig(**request.rig)
        return compile_rig(rig, request.subject_prompt)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/openjutsu/compile")
def openjutsu_compile(request: OpenJutsuInput) -> dict[str, Any]:
    try:
        payload = OpenJutsuRequest(**request.model_dump())
        workflow = build_openjutsu_workflow(payload)
        return {"workflow": workflow, "required_nodes": sorted(required_nodes(payload.backend))}
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/jobs")
def submit_job(request: JobInput) -> dict[str, Any]:
    try:
        client = PlatformClient()
        assets = {(node, name): path for key, path in request.assets.items() for node, name in [key.split(":", 1)]}
        handle = client.submit_workflow(request.workflow, assets)
        job = jobs.create(request.kind, {"handle": handle.id, "backend": handle.backend})
        job.status = "submitted" if handle.backend != "dryrun" else "validated"
        return asdict(job)
    except (PlatformError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return asdict(job)


@app.get("/")
def index():
    return {"name": "OpenField Studio", "dashboard": "/dashboard", "docs": "/docs", "status": "ready"}


def create_app() -> FastAPI:
    return app
