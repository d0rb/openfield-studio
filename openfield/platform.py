from dataclasses import dataclass
import importlib
import os
from typing import Any

import requests

from .config import settings
from .logging_config import configure_logging

log = configure_logging()


OPEN_WEIGHT_MODELS = {
    "qwen",
    "wan",
    "ltx",
    "flux",
    "minimax",
}


@dataclass
class JobHandle:
    id: str
    backend: str
    raw: Any = None


class PlatformError(RuntimeError):
    pass


class PlatformClient:
    """Small boundary around local ComfyUI, Comfy API v2, and Router.

    The SDK is optional so `dryrun` and local development remain installable
    without paid platform credentials.
    """

    def __init__(self, mode: str | None = None, open_weights_only: bool | None = None):
        self.mode = (mode or settings.execution_mode).lower()
        self.open_weights_only = settings.open_weights_only if open_weights_only is None else open_weights_only
        self._sdk = None
        if self.mode in {"platform", "router"}:
            try:
                self._sdk = importlib.import_module("comfy_sdk")
            except ImportError as exc:
                raise PlatformError("comfy-sdk is required for platform/router mode") from exc
        log.info("platform client initialized mode=%s open_weights_only=%s", self.mode, self.open_weights_only)

    def _guard_model(self, model: str) -> None:
        if self.open_weights_only and not any(token in model.lower() for token in OPEN_WEIGHT_MODELS):
            raise PlatformError(f"model blocked by open-weights-only policy: {model}")

    def submit_workflow(self, workflow: dict[str, Any], assets: dict[tuple[str, str], str] | None = None) -> JobHandle:
        if self.mode == "dryrun":
            return JobHandle("dryrun", self.mode, workflow)
        if self.mode == "local":
            body = {"prompt": workflow}
            response = requests.post(f"{settings.comfy_base_url.rstrip('/')}/prompt", json=body, timeout=60)
            if response.status_code != 200:
                raise PlatformError(f"local ComfyUI rejected workflow: {response.status_code} {response.text[:300]}")
            payload = response.json()
            return JobHandle(str(payload["prompt_id"]), self.mode, payload)
        if self.mode != "platform":
            raise PlatformError(f"workflow execution is not supported in mode={self.mode}")
        client = self._sdk.Comfy(api_key=settings.api_key)
        wf = client.workflows.from_dict(workflow)
        for (node_id, input_name), path in (assets or {}).items():
            asset = client.assets.from_file(path)
            wf.set_input(node_id, input_name, asset)
        job = client.submit(wf)
        return JobHandle(getattr(job, "id", "platform-job"), self.mode, job)

    def submit_router(self, model: str, payload: dict[str, Any]) -> JobHandle:
        self._guard_model(model)
        if self.mode == "dryrun":
            return JobHandle("dryrun-router", self.mode, {"model": model, "payload": payload})
        if self.mode != "router":
            raise PlatformError("Router calls require execution mode=router")
        client = self._sdk.Comfy(api_key=settings.api_key)
        handle = client.models.submit(model, payload)
        return JobHandle(getattr(handle, "id", "router-job"), self.mode, handle)

    def health(self) -> dict[str, Any]:
        result = {"mode": self.mode, "open_weights_only": self.open_weights_only, "base_url": settings.comfy_base_url}
        if self.mode == "dryrun":
            result["status"] = "ready"
            return result
        try:
            response = requests.get(f"{settings.comfy_base_url.rstrip('/')}/system_stats", timeout=10)
            result["status"] = "online" if response.ok else "error"
            result["http_status"] = response.status_code
        except requests.RequestException as exc:
            result.update(status="offline", error=str(exc))
        return result
