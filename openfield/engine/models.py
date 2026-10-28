"""Model registry: which weight files the app knows, what they are and under what licence.

The file list comes from the pinned official templates (`manifest.json`); this module adds the
human facts the audit and the receipts need. A file that is not here is not provably open-weights,
so the audit refuses it.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

MANIFEST_PATH = Path(__file__).with_name("manifest.json")


@dataclass(frozen=True)
class License:
    id: str
    name: str
    url: str
    commercial: str
    attribution: str | None = None


LICENSES: dict[str, License] = {
    "ltx-2.x-community": License(
        "ltx-2.x-community", "LTX-2.x Community License Agreement",
        "https://huggingface.co/Lightricks/LTX-2.5",
        "free for commercial and production use under $10M annual revenue; paid agreement above",
    ),
    "qwen-research": License(
        "qwen-research", "Qwen Research License Agreement",
        "https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE",
        "non-commercial use only", attribution="Built with Qwen",
    ),
    "apache-2.0": License(
        "apache-2.0", "Apache License 2.0", "https://www.apache.org/licenses/LICENSE-2.0",
        "free for commercial use",
    ),
    # The repack's model card declares bsd-3-clause; the upstream repository gives that licence for its code and names no
    # separate one for the weights, so this is the licence as declared, not one confirmed from the authors.
    "bsd-3-clause": License(
        "bsd-3-clause", "BSD 3-Clause License", "https://github.com/xinntao/Real-ESRGAN/blob/a4abfb2/LICENSE",
        "free for commercial use; keep the copyright notice with any copy",
    ),
}
REPO_LICENSE = {
    "Lightricks/LTX-2.5": "ltx-2.x-community",
    "Comfy-Org/Qwen-Image-2.1": "qwen-research",
    "Comfy-Org/Wan-Animate-2": "apache-2.0",
    "Comfy-Org/gemma-4": "apache-2.0",
    "Comfy-Org/Real-ESRGAN_repackaged": "bsd-3-clause",  # the name the official template uses ...
    "Comfy-Org/Real-ESRGAN": "bsd-3-clause",  # ... and the one Hugging Face now redirects it to
}


@dataclass(frozen=True)
class ModelInfo:
    file: str
    role: str
    repo: str
    license_id: str
    license_name: str
    license_url: str
    commercial: str
    attribution: str | None
    open_weights: bool
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _role(name: str, directory: str) -> str:
    lowered = name.lower()
    if directory == "diffusion_models":
        if "ltx" in lowered:
            return "video:ltx-2.5"
        if "wan" in lowered:
            return "video:wan-animate-2"
        return "image:qwen-image-2.1" if "qwen" in lowered else "diffusion"
    if directory == "vae":
        return "audio_vae" if "audio" in lowered else "vae"
    if directory == "upscale_models":
        return "upscaler:real-esrgan" if "esrgan" in lowered else "upscaler"
    return {
        "text_encoders": "text_encoder", "clip": "text_encoder", "loras": "lora",
        "clip_vision": "clip_vision", "latent_upscale_models": "upscaler",
    }.get(directory, directory)


@lru_cache(maxsize=1)
def manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def registry() -> dict[str, ModelInfo]:
    out: dict[str, ModelInfo] = {}
    for item in manifest()["models"]:
        license_ = LICENSES[REPO_LICENSE[item["repo"]]]
        out[item["name"]] = ModelInfo(
            file=item["name"], role=_role(item["name"], item["directory"]), repo=item["repo"],
            license_id=license_.id, license_name=license_.name, license_url=license_.url,
            commercial=license_.commercial, attribution=license_.attribution, open_weights=True,
            source=item["url"],
        )
    return out


def model_info(file: str) -> ModelInfo | None:
    """Registry entry for a weight file by base name, or None when it is not a known model."""
    return registry().get(Path(file.replace("\\", "/")).name)


def allowed_node_types() -> frozenset[str]:
    return frozenset(manifest()["allowed_node_types"])


def attributions(files: list[str]) -> list[str]:
    """Attribution lines the licences of the given files require (de-duplicated, ordered)."""
    seen: list[str] = []
    for file in files:
        info = model_info(file)
        if info and info.attribution and info.attribution not in seen:
            seen.append(info.attribution)
    return seen
