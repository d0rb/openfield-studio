from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OpenJutsuRequest:
    source_video: str
    references: list[str] = field(default_factory=list)
    prompt: str = ""
    backend: str = "ltx"
    duration_seconds: float = 5.0
    preserve_audio: bool = True
    mode: str = "motion_transfer"

    def validate(self) -> None:
        if not self.source_video:
            raise ValueError("source_video is required")
        if not 4 <= self.duration_seconds <= 30:
            raise ValueError("source video duration must be between 4 and 30 seconds")
        if not 1 <= len(self.references) <= 8:
            raise ValueError("one to eight reference images are required")
        if self.backend not in {"ltx", "minimax_h3", "qwen"}:
            raise ValueError("backend must be ltx, minimax_h3, or qwen")
        if self.mode not in {"motion_transfer", "object_swap", "multi_angle"}:
            raise ValueError("unsupported OpenJutsu mode")


def build_openjutsu_workflow(request: OpenJutsuRequest, task_id: str = "openjutsu") -> dict[str, Any]:
    request.validate()
    if request.backend == "ltx":
        return _build_ltx(request, task_id)
    if request.backend == "qwen":
        return _build_qwen(request, task_id)
    return _build_h3(request, task_id)


def _build_ltx(request: OpenJutsuRequest, task_id: str) -> dict[str, Any]:
    """Build an API graph contract for guide-driven LTX V2V.

    Node names are declared explicitly so a live /object_info preflight can
    reject an incompatible Comfy installation before a GPU job is submitted.
    """
    return {
        "1": {"class_type": "LoadVideo", "inputs": {"video": request.source_video}},
        "2": {"class_type": "LTXVPreprocess", "inputs": {"video": ["1", 0]}},
        "3": {"class_type": "LoadImage", "inputs": {"image": request.references[0]}},
        "4": {"class_type": "LTXVAddGuide", "inputs": {"video": ["2", 0], "image": ["3", 0]}},
        "5": {"class_type": "LTXVConditioning", "inputs": {
            "positive": request.prompt or "recast the subject and environment while preserving motion and timing",
            "motion_guide": ["4", 0],
        }},
        "6": {"class_type": "LTXVImgToVideo", "inputs": {
            "conditioning": ["5", 0], "audio_from_source": request.preserve_audio,
            "duration": request.duration_seconds,
        }},
        "7": {"class_type": "LTXVAudioVAEDecode", "inputs": {"samples": ["6", 0]}},
        "8": {"class_type": "SaveVideo", "inputs": {"video": ["7", 0], "filename_prefix": f"openfield/{task_id}"}},
    }


def _build_h3(request: OpenJutsuRequest, task_id: str) -> dict[str, Any]:
    return {
        "1": {"class_type": "LoadVideo", "inputs": {"video": request.source_video}},
        "2": {"class_type": "LoadImage", "inputs": {"image": request.references[0]}},
        "3": {"class_type": "MiniMaxH3AddGuide", "inputs": {"video": ["1", 0], "reference": ["2", 0]}},
        "4": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
            "guide": ["3", 0],
            "prompt": request.prompt or "preserve the original camera movement, timing, cuts, and audio",
            "duration": request.duration_seconds,
        }},
        "5": {"class_type": "SaveVideo", "inputs": {"video": ["4", 0], "filename_prefix": f"openfield/{task_id}"}},
    }


def _build_qwen(request: OpenJutsuRequest, task_id: str) -> dict[str, Any]:
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": request.references[0]}},
        "2": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {
            "image": ["1", 0],
            "prompt": request.prompt or "create a consistent multi-angle re-shoot of this scene",
        }},
        "3": {"class_type": "QwenImageEditPlus", "inputs": {"conditioning": ["2", 0]}},
        "4": {"class_type": "SaveImage", "inputs": {
            "images": ["3", 0], "filename_prefix": f"openfield/{task_id}_angle",
        }},
    }


def required_nodes(backend: str) -> set[str]:
    if backend == "ltx":
        return {"LoadVideo", "LoadImage", "LTXVPreprocess", "LTXVAddGuide", "LTXVConditioning", "LTXVImgToVideo", "LTXVAudioVAEDecode", "SaveVideo"}
    if backend == "qwen":
        return {"LoadImage", "TextEncodeQwenImageEditPlus", "QwenImageEditPlus", "SaveImage"}
    return {"LoadVideo", "LoadImage", "MiniMaxH3AddGuide", "MiniMaxH3ReferenceToVideo", "SaveVideo"}
