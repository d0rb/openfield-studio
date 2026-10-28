"""Preflight for a ComfyUI box: which of our workflows it can run, read from its own `/system_stats` and `/object_info`.

comfy-sdk speaks only the v2 API (Comfy Cloud, or comfy-api-proxy in front of a box), and that API lists no model
files. ComfyUI itself does: `/object_info` carries, for every loader node, the file names it would accept, which is
the very list ComfyUI validates a prompt against. Given the ComfyUI URL (the second tunnelled port on a box; optional
in the Connect panel) this answers, per workflow, "ready", "missing model <file> (expected in models/<dir>)" or
"unknown node class", before anyone pays for a render that would fail at its first loader.

`assess()` is a pure function over the two JSON documents, so tests need no server; `probe_comfy()` fetches them.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from .contract import CONTRACTS
from .models import manifest
from .workflows import Template, WorkflowError, load_template, sample_values

LABELS = {
    "qwen21_t2i": "Qwen-Image 2.1, text to still",
    "qwen21_edit": "Qwen-Image 2.1, edit a still",
    "ltx25_i2v": "LTX 2.5, still to video",
    "ltx25_flf2v": "LTX 2.5, first and last frame to video",
    "wan_animate2": "Wan Animate 2, motion transfer",
    "esrgan_upscale": "Real-ESRGAN, video upscale",
}
GROUPS = {"qwen21_t2i": "qwen", "qwen21_edit": "qwen", "ltx25_i2v": "ltx", "ltx25_flf2v": "ltx", "wan_animate2": "wan",
          "esrgan_upscale": "esrgan"}


def model_inputs(graph: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """(node id, class, input name, file) for every input whose value names one of the manifest's model files."""
    names = {m["name"] for m in manifest()["models"]}
    found = []
    for node_id, node in graph.items():
        for name, value in (node.get("inputs") or {}).items():
            if isinstance(value, str) and value in names:
                found.append((str(node_id), str(node.get("class_type", "")), name, value))
    return found


def sample_graph(template: Template) -> dict[str, Any]:
    """The graph as it would be submitted: patched with throwaway values and pruned of the unused branches."""
    with tempfile.TemporaryDirectory() as tmp:
        image, video = Path(tmp) / "sample.png", Path(tmp) / "sample.mp4"
        image.write_bytes(b"")
        video.write_bytes(b"")
        return template.patch(sample_values(template, image, video)).graph


def describe_system(stats: dict[str, Any] | None) -> dict[str, Any]:
    """ComfyUI's version and its first GPU, from `/system_stats`; every field None when unknown."""
    out: dict[str, Any] = {"version": None, "device": None, "vram_total_gb": None, "vram_free_gb": None}
    if not isinstance(stats, dict):
        return out
    out["version"] = (stats.get("system") or {}).get("comfyui_version")
    devices = stats.get("devices") or []
    if devices and isinstance(devices[0], dict):
        first = devices[0]
        name = str(first.get("name") or "")
        if ":" in name:  # "cuda:0 NVIDIA GeForce RTX 5090 : cudaMallocAsync"
            name = name.split(" ", 1)[-1].split(" : ")[0].strip()
        out["device"] = name or None
        for key, field in (("vram_total", "vram_total_gb"), ("vram_free", "vram_free_gb")):
            value = first.get(key)
            if isinstance(value, (int, float)) and value > 0:
                out[field] = round(value / 1e9, 1)
    return out


def assess(object_info: dict[str, Any], stats: dict[str, Any] | None = None, *,
           workflow_dir: Path | None = None) -> dict[str, Any]:
    """Per workflow: ready, missing model files (with where to get them), or node classes this ComfyUI lacks."""
    models = {m["name"]: m for m in manifest()["models"]}
    rows: list[dict[str, Any]] = []
    for name in CONTRACTS:
        row: dict[str, Any] = {"name": name, "label": LABELS.get(name, name), "missing": [], "unknown_nodes": []}
        try:
            graph = sample_graph(load_template(name, workflow_dir))
        except (FileNotFoundError, WorkflowError, ValueError, KeyError) as exc:
            rows.append({**row, "state": "unavailable", "detail": f"template not usable here: {exc}"})
            continue
        row["unknown_nodes"] = sorted({str(n.get("class_type", "")) for n in graph.values()
                                       if str(n.get("class_type", "")) not in object_info})
        seen: set[str] = set()
        for node_id, class_type, input_name, file in model_inputs(graph):
            spec = object_info.get(class_type)
            if spec is None or file in seen:
                continue  # an unknown class is reported once, above
            inputs = {**(spec.get("input") or {}).get("required", {}), **(spec.get("input") or {}).get("optional", {})}
            definition = inputs.get(input_name)
            if not definition or not isinstance(definition[0], list):
                continue  # not a file picker: ComfyUI will not check it either
            if file not in definition[0]:
                seen.add(file)
                entry = models[file]
                row["missing"].append({
                    "file": file, "directory": entry["directory"], "repo": entry["repo"], "url": entry["url"],
                    "node": f"{node_id} ({class_type})",
                    "hint": f"FETCH_ONLY={GROUPS.get(name, '')} bash /workspace/pod_setup.sh fetch",
                })
        row["state"] = "unknown_nodes" if row["unknown_nodes"] else "missing" if row["missing"] else "ready"
        rows.append(row)
    ready = sum(1 for r in rows if r["state"] == "ready")
    missing_files = sorted({m["file"] for r in rows for m in r["missing"]})
    if ready == len(rows):
        summary = f"{ready} of {len(rows)} workflows ready"
    elif missing_files:
        summary = f"{ready} of {len(rows)} workflows ready; {len(missing_files)} model file(s) missing"
    else:
        summary = f"{ready} of {len(rows)} workflows ready"
    return {"ok": ready == len(rows), "state": "checked", "comfyui": describe_system(stats), "workflows": rows,
            "missing_files": missing_files, "summary": summary}


def check_url(url: str, label: str = "ComfyUI URL") -> str:
    """A plain http(s) address: no credentials, query or fragment; a trailing slash is dropped."""
    clean = (url or "").strip().rstrip("/")
    parts = urlsplit(clean)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError(f"{label}: use the form http://host:port")
    if parts.username or parts.password:
        raise ValueError(f"{label}: take the user name and password out of the address; a token has its own field")
    if parts.query or parts.fragment:
        raise ValueError(f"{label}: no query string or fragment")
    return clean


async def probe_comfy(comfy_url: str, *, workflow_dir: Path | None = None, timeout: float = 60.0) -> dict[str, Any]:
    """Fetch `/system_stats` and `/object_info` from a ComfyUI and assess the workflows; never raises for a bad box."""
    base = check_url(comfy_url)
    unreachable = {"ok": False, "state": "unreachable", "comfyui": describe_system(None), "workflows": [],
                   "missing_files": []}
    try:
        async with httpx.AsyncClient(timeout=timeout) as http:
            stats = await http.get(f"{base}/system_stats")
            info = await http.get(f"{base}/object_info")
    except httpx.HTTPError as exc:
        return {**unreachable, "summary": f"Could not reach {urlsplit(base).netloc}: {type(exc).__name__}"}
    if info.status_code != 200:
        return {**unreachable, "summary": f"{urlsplit(base).netloc} does not answer like ComfyUI (no /object_info: HTTP {info.status_code})"}
    try:
        object_info = info.json()
    except ValueError:
        return {**unreachable, "summary": f"{urlsplit(base).netloc} did not return JSON for /object_info"}
    try:
        system = stats.json() if stats.status_code == 200 else None
    except ValueError:
        system = None  # the box's details are a nicety; the workflow check stands without them
    if not isinstance(object_info, dict) or not object_info:
        return {**unreachable, "summary": f"{urlsplit(base).netloc} returned an empty /object_info"}
    return assess(object_info, system, workflow_dir=workflow_dir)


def report_lines(result: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(state, name, detail) rows for a text report: one line for the box, one per workflow."""
    lines: list[tuple[str, str, str]] = []
    if result.get("state") != "checked":
        return [("fail", "ComfyUI", str(result.get("summary", "not checked")))]
    system = result.get("comfyui") or {}
    box = ", ".join(s for s in (
        f"ComfyUI {system['version']}" if system.get("version") else None,
        system.get("device"),
        f"{system['vram_total_gb']} GB" if system.get("vram_total_gb") else None,
    ) if s) or "no system details"
    lines.append(("ok", "ComfyUI", box))
    for row in result.get("workflows", []):
        if row["state"] == "ready":
            lines.append(("ok", row["label"], "ready"))
        elif row["state"] == "missing":
            files = "; ".join(f"missing {m['file']} (models/{m['directory']}, {m['repo']})" for m in row["missing"])
            lines.append(("fail", row["label"], files))
        elif row["state"] == "unknown_nodes":
            lines.append(("fail", row["label"], "this ComfyUI lacks: " + ", ".join(row["unknown_nodes"])))
        else:
            lines.append(("warn", row["label"], str(row.get("detail", row["state"]))))
    return lines
