"""Templates and strict slot patching for API-format ComfyUI graphs.

A template is an exported API graph (`<name>.api.json`) plus a slots file (`<name>.slots.json`)
that names the literal inputs we are allowed to change. Patching is deliberately strict: the
Comfy SDK's `set_input` silently creates a missing node or input, so every id and field is
checked against the graph here first. Nothing in this module talks to ComfyUI.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .audit import audit_graph

WORKFLOW_DIR = Path(__file__).resolve().parents[1] / "workflows"
OUTPUT_CLASSES = frozenset({"SaveVideo", "SaveImage", "SaveImageAdvanced", "SaveAudio"})
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
VIDEO_SUFFIXES = (".mp4", ".mov", ".webm", ".mkv")
KINDS = {"text", "int", "seed", "float", "bool", "choice", "image", "video", "image_list", "guide_list"}


class WorkflowError(ValueError):
    """A template or a patch request is invalid; the message says exactly what and where."""


@dataclass(frozen=True)
class Slot:
    name: str
    node: str
    input: str
    kind: str
    required: bool = True
    default: Any = None
    min: float | None = None
    max: float | None = None
    multiple_of: int | None = None
    choices: tuple[Any, ...] | None = None
    pattern: str | None = None  # image_list: consumer input name, e.g. "image_{i}"
    start: int = 1
    limit: int = 0
    loader: str | None = None  # image_list/guide_list: id of a LoadImage node to clone per reference
    chain: tuple[str, ...] = ()  # guide_list: preprocessor/resize nodes between the loader and the guide
    guide: str | None = None  # guide_list: id of the LTXVAddGuide node to clone per still
    unlink: bool = False  # the input is wired to a helper node in the template; replace the wiring

    @classmethod
    def from_json(cls, name: str, data: dict[str, Any]) -> Slot:
        if data.get("kind") not in KINDS:
            raise WorkflowError(f"slot {name!r}: kind must be one of {sorted(KINDS)}")
        choices = tuple(data["choices"]) if data.get("choices") else None
        chain = tuple(data["chain"]) if data.get("chain") else ()
        return cls(
            name=name, node=str(data["node"]), input=data.get("input", ""), kind=data["kind"],
            required=data.get("required", True), default=data.get("default"),
            min=data.get("min"), max=data.get("max"), multiple_of=data.get("multiple_of"),
            choices=choices, pattern=data.get("pattern"), start=data.get("start", 1),
            limit=data.get("limit", 0), loader=data.get("loader"), chain=chain,
            guide=data.get("guide"), unlink=bool(data.get("unlink", False)),
        )


@dataclass(frozen=True)
class AssetBinding:
    node: str
    input: str
    path: Path
    slot: str


@dataclass
class PatchedWorkflow:
    template: str
    graph: dict[str, Any]
    assets: list[AssetBinding]
    outputs: dict[str, str]
    snapped: dict[str, Any] = field(default_factory=dict)

    def sha256(self) -> str:
        """Hash of the executable graph with each uploaded file replaced by its content hash."""
        graph = copy.deepcopy(self.graph)
        for binding in self.assets:
            graph[binding.node]["inputs"][binding.input] = {"asset_sha256": _file_sha256(binding.path)}
        blob = json.dumps(graph, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_link(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)


def _links(graph: dict[str, Any]):
    for node_id, node in graph.items():
        for name, value in (node.get("inputs") or {}).items():
            if _is_link(value):
                yield node_id, name, value[0]


def prune_unreachable(graph: dict[str, Any], outputs: dict[str, str]) -> dict[str, Any]:
    """Keep only nodes ComfyUI would execute: those reachable from the output nodes."""
    keep: set[str] = set()
    stack = list(outputs.values())
    while stack:
        node_id = stack.pop()
        if node_id in keep or node_id not in graph:
            continue
        keep.add(node_id)
        for value in (graph[node_id].get("inputs") or {}).values():
            if _is_link(value):
                stack.append(value[0])
    return {k: v for k, v in graph.items() if k in keep}


@dataclass
class Template:
    name: str
    engine: str
    graph: dict[str, Any]
    slots: dict[str, Slot]
    outputs: dict[str, str]
    fixed: tuple[tuple[str, str, Any, bool], ...] = ()
    meta: dict[str, Any] = field(default_factory=dict)

    def problems(self) -> list[str]:
        """Everything wrong with the template itself; an empty list means it is usable."""
        issues: list[str] = []
        if "nodes" in self.graph and "links" in self.graph:
            return ["graph is a UI-format workflow; export API format"]
        for node_id, name, target in _links(self.graph):
            if target not in self.graph:
                issues.append(f"node {node_id} input {name!r} links to missing node {target!r}")
        for slot in self.slots.values():
            node = self.graph.get(slot.node)
            if node is None:
                issues.append(f"slot {slot.name!r}: node {slot.node!r} is not in the graph")
            elif slot.kind not in {"image_list", "guide_list"} and slot.input not in (node.get("inputs") or {}):
                issues.append(f"slot {slot.name!r}: node {slot.node} has no input {slot.input!r}")
            elif slot.kind == "image_list" and (slot.loader not in self.graph or not slot.pattern):
                issues.append(f"slot {slot.name!r}: loader {slot.loader!r} missing or no pattern")
            elif slot.kind == "guide_list":
                issues += _guide_list_problems(slot, self.graph)
            elif slot.kind not in {"image", "video", "image_list", "guide_list"}:
                issues += _wiring_issue(f"slot {slot.name!r}", self.graph, slot.node, slot.input, slot.unlink)
        for node_id, name, _, unlink in self.fixed:
            if name not in (self.graph.get(node_id, {}).get("inputs") or {}):
                issues.append(f"fixed value targets missing input {node_id}/{name}")
            else:
                issues += _wiring_issue("fixed value", self.graph, node_id, name, unlink)
        for role, node_id in self.outputs.items():
            cls = self.graph.get(node_id, {}).get("class_type")
            if cls not in OUTPUT_CLASSES:
                issues.append(f"output {role!r}: node {node_id} is {cls!r}, not an output node")
        result = audit_graph(self.graph)
        issues.extend(f"audit: {note}" for note in result.notes if "requires the attribution" not in note)
        return issues

    def patch(self, values: dict[str, Any], *, prune: bool = True) -> PatchedWorkflow:
        unknown = sorted(set(values) - set(self.slots))
        if unknown:
            raise WorkflowError(f"unknown slot(s) {unknown}; this template has {sorted(self.slots)}")
        graph = copy.deepcopy(self.graph)
        for node_id, name, value, unlink in self.fixed:
            _set_literal(graph, node_id, name, value, unlink=unlink)
        assets: list[AssetBinding] = []
        snapped: dict[str, Any] = {}
        applied: list[Slot] = []
        for slot in self.slots.values():
            if slot.name in values:
                raw = values[slot.name]
            elif slot.default is not None:
                raw = slot.default
            elif slot.kind in {"image_list", "guide_list"} and not slot.required:
                raw = []  # still strips the template's pre-wired placeholder inputs
            elif slot.required:
                raise WorkflowError(f"missing required slot {slot.name!r}")
            else:
                continue
            if slot.kind == "image_list":
                assets.extend(_wire_image_list(graph, slot, raw))
            elif slot.kind == "guide_list":
                assets.extend(_wire_guide_list(graph, slot, raw))
            elif slot.kind in {"image", "video"}:
                path = _check_file(slot.name, slot.kind, raw)
                _require_input(graph, slot.node, slot.input)
                assets.append(AssetBinding(slot.node, slot.input, path, slot.name))
            else:
                value = _coerce(slot, raw, snapped)
                _set_literal(graph, slot.node, slot.input, value, unlink=slot.unlink)
                applied.append(slot)
        if prune:
            graph = prune_unreachable(graph, self.outputs)
            for binding in assets:
                if binding.node not in graph:
                    raise WorkflowError(
                        f"slot {binding.slot!r}: node {binding.node} does not feed any output, "
                        "so the upload would be ignored (template bug)"
                    )
            for slot in applied:
                if slot.node not in graph:
                    raise WorkflowError(
                        f"slot {slot.name!r}: node {slot.node} does not feed any output, "
                        "so the value would be ignored (template bug)"
                    )
        return PatchedWorkflow(self.name, graph, assets, dict(self.outputs), snapped)


def _require_input(graph: dict[str, Any], node_id: str, name: str) -> dict[str, Any]:
    node = graph.get(node_id)
    if node is None:
        raise WorkflowError(f"node {node_id!r} is not in the graph")
    inputs = node.get("inputs") or {}
    if name not in inputs:
        raise WorkflowError(f"node {node_id} ({node.get('class_type')}) has no input {name!r}")
    return inputs


def _set_literal(graph: dict[str, Any], node_id: str, name: str, value: Any, *, unlink: bool = False) -> None:
    """Set an input to a literal. A wired input may only be replaced when the template says `unlink`."""
    inputs = _require_input(graph, node_id, name)
    wired = _is_link(inputs[name])
    if wired and not unlink:
        raise WorkflowError(
            f"node {node_id} input {name!r} is wired to another node, not a literal "
            "(declare it with unlink to replace the wiring)")
    if unlink and not wired:
        raise WorkflowError(f"node {node_id} input {name!r} is not wired; remove unlink from the template")
    inputs[name] = value


def _wiring_issue(what: str, graph: dict[str, Any], node_id: str, name: str, unlink: bool) -> list[str]:
    """A template problem when an input's wiring does not match what the template declares."""
    wired = _is_link(((graph.get(node_id) or {}).get("inputs") or {}).get(name))
    if wired and not unlink:
        return [f"{what}: node {node_id} input {name!r} is wired to another node; declare it with unlink"]
    if unlink and not wired:
        return [f"{what}: node {node_id} input {name!r} is not wired, so unlink is stale"]
    return []


def _coerce(slot: Slot, raw: Any, snapped: dict[str, Any]) -> Any:
    kind = slot.kind
    if kind == "text":
        if not isinstance(raw, str) or (slot.required and not raw.strip()):
            raise WorkflowError(f"slot {slot.name!r} needs non-empty text")
        return raw
    if kind == "bool":
        if not isinstance(raw, bool):
            raise WorkflowError(f"slot {slot.name!r} needs true or false")
        return raw
    if kind == "choice":
        if slot.choices is None or raw not in slot.choices:
            raise WorkflowError(f"slot {slot.name!r} must be one of {list(slot.choices or ())}")
        return raw
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise WorkflowError(f"slot {slot.name!r} needs a number")
    value: Any = float(raw) if kind == "float" else int(raw)
    if slot.multiple_of:
        step = slot.multiple_of
        fitted = max(step, round(value / step) * step)
        if fitted != value:
            snapped[slot.name] = fitted
        value = fitted
    if slot.min is not None and value < slot.min or slot.max is not None and value > slot.max:
        raise WorkflowError(f"slot {slot.name!r} must be between {slot.min} and {slot.max}")
    return value


def _check_file(slot_name: str, kind: str, raw: Any) -> Path:
    path = Path(raw)
    suffixes = IMAGE_SUFFIXES if kind == "image" else VIDEO_SUFFIXES
    if not path.is_file():
        raise WorkflowError(f"slot {slot_name!r}: file not found: {path.name}")
    if path.suffix.lower() not in suffixes:
        raise WorkflowError(f"slot {slot_name!r}: {path.suffix} is not one of {suffixes}")
    return path


def _wire_image_list(graph: dict[str, Any], slot: Slot, raw: Any) -> list[AssetBinding]:
    paths = [_check_file(slot.name, "image", p) for p in (raw or [])]
    if len(paths) > slot.limit:
        raise WorkflowError(f"slot {slot.name!r} takes at most {slot.limit} images, got {len(paths)}")
    if slot.required and not paths:
        raise WorkflowError(f"slot {slot.name!r} needs at least one image")
    consumer = graph[slot.node]["inputs"]
    bindings = []
    for i, path in enumerate(paths):
        loader_id = f"{slot.loader}_{slot.name}_{i}"
        graph[loader_id] = copy.deepcopy(graph[slot.loader])
        bindings.append(AssetBinding(loader_id, "image", path, slot.name))
        consumer[slot.pattern.format(i=slot.start + i)] = [loader_id, 0]
    for i in range(len(paths), slot.limit):
        consumer.pop(slot.pattern.format(i=slot.start + i), None)
    return bindings


def _guide_list_problems(slot: Slot, graph: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if not slot.chain:
        issues.append(f"slot {slot.name!r}: chain is empty")
    if slot.loader not in graph:
        issues.append(f"slot {slot.name!r}: loader {slot.loader!r} is not in the graph")
    missing_chain = [c for c in slot.chain if c not in graph]
    if missing_chain:
        issues.append(f"slot {slot.name!r}: chain nodes {missing_chain} are not in the graph")
    guide = graph.get(slot.guide or "")
    if guide is None:
        issues.append(f"slot {slot.name!r}: guide node {slot.guide!r} is not in the graph")
    elif guide.get("class_type") != "LTXVAddGuide":
        issues.append(
            f"slot {slot.name!r}: guide node {slot.guide} is {guide.get('class_type')!r}, not LTXVAddGuide"
        )
    if slot.limit < 1:
        issues.append(f"slot {slot.name!r}: limit must be at least 1")
    if issues:
        return issues
    prev = slot.loader
    for _k, chain_id in enumerate(slot.chain):
        chain_node = graph[chain_id]
        if not any(_is_link(v) and v[0] == prev for v in (chain_node.get("inputs") or {}).values()):
            issues.append(f"slot {slot.name!r}: chain node {chain_id} has no input linked to {prev!r}")
        prev = chain_id
    guide_inputs = guide["inputs"]
    image_link = guide_inputs.get("image")
    if not _is_link(image_link) or image_link[0] != slot.chain[-1]:
        issues.append(
            f"slot {slot.name!r}: guide node {slot.guide} image input is not linked to chain tail {slot.chain[-1]!r}"
        )
    prev_node: str | None = None
    for name in ("positive", "negative", "latent"):
        link = guide_inputs.get(name)
        if not _is_link(link):
            issues.append(f"slot {slot.name!r}: guide node {slot.guide} input {name!r} is not a link")
            continue
        node = graph.get(link[0])
        if node is None or node.get("class_type") != "LTXVAddGuide":
            issues.append(
                f"slot {slot.name!r}: guide node {slot.guide} input {name!r} links to non-LTXVAddGuide {link[0]!r}"
            )
        if prev_node is None:
            prev_node = link[0]
        elif link[0] != prev_node:
            issues.append(
                f"slot {slot.name!r}: guide node {slot.guide} inputs positive/negative/latent link to different nodes"
            )
    return issues


def _wire_guide_list(graph: dict[str, Any], slot: Slot, raw: Any) -> list[AssetBinding]:
    if not isinstance(raw, list):
        raise WorkflowError(f"slot {slot.name!r} needs a list")
    if len(raw) > slot.limit:
        raise WorkflowError(f"slot {slot.name!r} takes at most {slot.limit} stills, got {len(raw)}")
    bindings: list[AssetBinding] = []
    last_guide_id: str | None = None
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise WorkflowError(f"slot {slot.name!r}: item {i} is not an object")
        path = _check_file(slot.name, "image", item.get("image"))
        frame_idx = item.get("frame_idx")
        if not isinstance(frame_idx, int) or frame_idx < 1:
            raise WorkflowError(f"slot {slot.name!r}: frame_idx must be an integer >= 1")
        if i > 0 and frame_idx <= raw[i - 1]["frame_idx"]:
            raise WorkflowError(f"slot {slot.name!r}: frame_idx must be strictly increasing")
        strength = item.get("strength")
        if strength is not None and (
            isinstance(strength, bool)
            or not isinstance(strength, (int, float))
            or not (0 < float(strength) <= 1)
        ):
            raise WorkflowError(f"slot {slot.name!r}: strength must be a number in (0, 1]")

        loader_id = f"{slot.loader}_{slot.name}_{i}"
        graph[loader_id] = copy.deepcopy(graph[slot.loader])
        graph[loader_id].setdefault("_meta", {})["title"] = f"Mid still {i + 1}"
        bindings.append(AssetBinding(loader_id, "image", path, slot.name))

        prev_id = loader_id
        for k, chain_id in enumerate(slot.chain):
            expected_source = slot.loader if k == 0 else slot.chain[k - 1]
            clone_id = f"{chain_id}_{slot.name}_{i}"
            graph[clone_id] = copy.deepcopy(graph[chain_id])
            graph[clone_id].setdefault("_meta", {})["title"] = f"Mid still {i + 1}"
            found = False
            for input_name, value in graph[clone_id].get("inputs", {}).items():
                if _is_link(value) and value[0] == expected_source:
                    graph[clone_id]["inputs"][input_name] = [prev_id, value[1]]
                    found = True
                    break
            if not found:
                raise WorkflowError(
                    f"slot {slot.name!r}: clone of {chain_id} has no input linked to {expected_source!r}"
                )
            prev_id = clone_id

        guide_id = f"{slot.guide}_{slot.name}_{i}"
        graph[guide_id] = copy.deepcopy(graph[slot.guide])
        graph[guide_id].setdefault("_meta", {})["title"] = f"Mid still {i + 1}"
        found = False
        for input_name, value in graph[guide_id].get("inputs", {}).items():
            if _is_link(value) and value[0] == slot.chain[-1]:
                graph[guide_id]["inputs"][input_name] = [prev_id, value[1]]
                found = True
                break
        if not found:
            raise WorkflowError(
                f"slot {slot.name!r}: clone of guide {slot.guide} has no input linked to {slot.chain[-1]!r}"
            )

        if i == 0:
            prev_guide = graph[slot.guide]["inputs"]["positive"][0]
        else:
            prev_guide = last_guide_id
        graph[guide_id]["inputs"]["positive"] = [prev_guide, 0]
        graph[guide_id]["inputs"]["negative"] = [prev_guide, 1]
        graph[guide_id]["inputs"]["latent"] = [prev_guide, 2]
        graph[guide_id]["inputs"]["frame_idx"] = frame_idx
        if strength is not None:
            graph[guide_id]["inputs"]["strength"] = float(strength)
        last_guide_id = guide_id

    if raw:
        graph[slot.guide]["inputs"]["positive"] = [last_guide_id, 0]
        graph[slot.guide]["inputs"]["negative"] = [last_guide_id, 1]
        graph[slot.guide]["inputs"]["latent"] = [last_guide_id, 2]
    return bindings


def sample_values(template: Template, image: Path, video: Path) -> dict[str, Any]:
    """Throwaway values for every slot, to patch a template and see what the real graph looks like.

    Used by tooling (which model files a workflow really loads, validation against a live ComfyUI) and
    tests. `image` and `video` are existing files of the right type; reference lists are left empty.
    """
    values: dict[str, Any] = {}
    for slot in template.slots.values():
        if slot.kind == "image":
            values[slot.name] = image
        elif slot.kind == "video":
            values[slot.name] = video
        elif slot.kind == "text":
            values[slot.name] = "sample"
        elif slot.kind in {"int", "seed", "float"}:
            values[slot.name] = slot.default if slot.default is not None else (slot.min or 1)
        elif slot.kind == "bool":
            values[slot.name] = bool(slot.default)
        elif slot.kind == "choice" and slot.choices:
            values[slot.name] = slot.choices[0]
    return values


def load_template(name: str, directory: Path | None = None) -> Template:
    base = directory or WORKFLOW_DIR
    graph = json.loads((base / f"{name}.api.json").read_text(encoding="utf-8"))
    spec = json.loads((base / f"{name}.slots.json").read_text(encoding="utf-8"))
    slots = {k: Slot.from_json(k, v) for k, v in spec["slots"].items()}
    fixed = tuple((str(f["node"]), f["input"], f["value"], bool(f.get("unlink", False)))
                  for f in spec.get("fixed", []))
    return Template(
        name=name, engine=spec.get("engine", ""), graph=graph, slots=slots,
        outputs={k: str(v) for k, v in spec["outputs"].items()}, fixed=fixed,
        meta={k: v for k, v in spec.items() if k not in {"slots", "outputs", "fixed"}},
    )
