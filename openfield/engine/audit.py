"""Open-weights audit: prove a workflow graph uses only allowlisted nodes and known open weights.

The allowlist is every executable node class in the pinned official templates, so partner/API
nodes (which call a hosted model) cannot pass. A weight file the registry does not know cannot be
shown to be open-weights, so it fails too. The result goes into the receipt and the UI lock.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import ModelInfo, allowed_node_types, model_info

POLICY = "open-weights-only"
MODEL_SUFFIXES = (".safetensors", ".ckpt", ".pt", ".pth", ".gguf", ".bin", ".onnx")
_PARTNER_HINT = re.compile(
    r"(?i)(kling|veo|runway|luma|pika|openai|gpt|gemini|ideogram|recraft|stability|moonvalley|"
    r"seedance|seedream|bytedance|hailuo|minimaxapi|bfl|api)"
)


@dataclass(frozen=True)
class Audit:
    policy: str
    result: str  # "pass" | "fail"
    nodes_checked: int
    disallowed_nodes: tuple[str, ...]
    unknown_models: tuple[str, ...]
    models: tuple[dict[str, Any], ...]
    notes: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.result == "pass"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def referenced_models(graph: dict[str, Any]) -> list[str]:
    """Weight file base names mentioned as literal inputs anywhere in an API graph."""
    found: list[str] = []
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        for value in (node.get("inputs") or {}).values():
            if isinstance(value, str) and value.lower().endswith(MODEL_SUFFIXES):
                name = Path(value.replace("\\", "/")).name
                if name not in found:
                    found.append(name)
    return found


def audit_graph(graph: dict[str, Any]) -> Audit:
    allowed = allowed_node_types()
    classes = [n.get("class_type", "") for n in graph.values() if isinstance(n, dict)]
    disallowed = sorted({c for c in classes if c not in allowed})
    files = referenced_models(graph)
    infos: list[ModelInfo] = []
    unknown: list[str] = []
    for file in files:
        info = model_info(file)
        if info is None:
            unknown.append(file)
        else:
            infos.append(info)
    notes: list[str] = []
    for cls in disallowed:
        kind = "looks like a partner/API node" if _PARTNER_HINT.search(cls) else "not in the allowlist"
        notes.append(f"{cls}: {kind}")
    notes.extend(f"{f}: not a known open-weights file" for f in unknown)
    for info in infos:
        if info.attribution:
            notes.append(f"{info.file}: licence requires the attribution '{info.attribution}'")
    ok = not disallowed and not unknown and bool(classes)
    return Audit(
        policy=POLICY, result="pass" if ok else "fail", nodes_checked=len(classes),
        disallowed_nodes=tuple(disallowed), unknown_models=tuple(unknown),
        models=tuple(i.to_dict() for i in infos), notes=tuple(notes),
    )
