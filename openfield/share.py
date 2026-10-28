"""Files a take hands to other tools: the ComfyUI graphs, an SDK snippet, a verified receipt view.

The live server and the static Replay export both build these here, so a judge reading the hosted
copy sees byte-for-byte what a local run would give them.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from .engine import receipt as receipts

OPEN_IN_COMFY = """Open in ComfyUI
================
Each NN_step.api.json is the exact API-format graph one render step ran.
Load it in ComfyUI (Load, or drag the file onto the canvas).

A graph refers to its input files by name. Before loading NN_step.api.json, copy the files in
inputs/NN_step/ into ComfyUI/input/: they are the stills and clips that step used. A reference photo of a
character is not included; only its SHA-256 is kept (in the receipt), so supply your own and pick it in
the Load Image node.
Models are listed in the take's receipt; all are open-weights files.
"""


def workflow_files(take_dir: Path) -> list[Path]:
    """The API-format graph of every render step, in run order."""
    return sorted(Path(take_dir).glob("runs/*/workflow.api.json"))


def run_assets(run_dir: Path) -> list[dict[str, Any]]:
    """The files a render step uploaded: node, input, the name the graph shows, hash, and where it is kept."""
    try:
        record = json.loads((Path(run_dir) / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    assets = record.get("assets") if isinstance(record, dict) else None
    return [a for a in assets if isinstance(a, dict)] if isinstance(assets, list) else []


def _kept_file(take_dir: Path, asset: dict[str, Any]) -> Path | None:
    """The asset's file inside the take folder, or None when it is not kept (or points outside it)."""
    relative = asset.get("from")
    if not isinstance(relative, str) or not relative:
        return None
    root = Path(take_dir).resolve()
    candidate = (root / relative).resolve()
    return candidate if candidate.is_file() and root in candidate.parents else None


def sdk_snippet(run_name: str, assets: list[dict[str, Any]] | None = None, kept: set[str] | None = None) -> str:
    """A script that re-runs one render step. `kept` names the assets whose files come with the zip."""
    lines = []
    for asset in assets or []:
        call = f'wf.set_input("{asset["node"]}", "{asset["input"]}", ' \
               f'client.assets.from_file("inputs/{run_name}/{asset["name"]}"))'
        if kept is None or asset["name"] in kept:
            lines.append(f"    {call}")
        else:
            lines.append(f'    # "{asset["name"]}" is not kept with the take (only its SHA-256 is, in the receipt): '
                         "use your own file here")
            lines.append(f"    # {call}")
    if not lines:
        lines.append("    # this step uploads no files")
    binds = "\n".join(lines)
    return f'''# Reproduce this render step with the Comfy SDK (pip install "comfy-sdk>=0.5,<0.6")
# Target: set COMFY_BASE_URL for a GPU box (e.g. http://127.0.0.1:9189) or COMFY_API_KEY for Comfy Cloud.
# Unzip workflows.zip next to this file: it holds {run_name}.api.json and the files in inputs/{run_name}/.
import json

from comfy_sdk import Comfy

with open("{run_name}.api.json", encoding="utf-8") as handle:
    graph = json.load(handle)
with Comfy() as client:
    wf = client.workflows.from_json(graph)
{binds}
    job = client.run(wf)
    for output in job.outputs:
        output.to_file(output.name)
'''


def take_snippet(take_dir: Path) -> str | None:
    """The SDK snippet for the last render step of a take, or None when no workflow was recorded."""
    runs = workflow_files(take_dir)
    if not runs:
        return None
    run_dir = runs[-1].parent
    assets = run_assets(run_dir)
    kept = {a["name"] for a in assets if _kept_file(take_dir, a) is not None}
    return sdk_snippet(run_dir.name, assets, kept)


def workflows_zip(take_dir: Path, *, include_inputs: bool = True) -> bytes:
    """Every step's graph, plus the input files that step used, ready to open in ComfyUI.

    The hosted copy serves every input beside the take already, so it zips the graphs alone (`include_inputs=False`)
    and the README says where each input sits: shipping the stills twice put the site past its size limit."""
    take_dir = Path(take_dir).resolve()  # _kept_file answers with resolved paths: a relative --takes must match them
    notes: list[str] = []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for workflow in workflow_files(take_dir):
            run = workflow.parent.name
            archive.write(workflow, f"{run}.api.json")
            for asset in run_assets(workflow.parent):
                source = _kept_file(take_dir, asset)
                if source is not None and not include_inputs:
                    notes.append(f"{run}: {asset['name']} ({asset.get('slot', 'input')}) is served beside this zip at "
                                 f"{source.relative_to(take_dir).as_posix()}; put it in inputs/{run}/ to run the graph")
                elif source is not None:
                    archive.write(source, f"inputs/{run}/{asset['name']}")
                else:
                    digest = str(asset.get("sha256", ""))[:12]
                    notes.append(f"{run}: {asset['name']} ({asset.get('slot', 'input')}) is not kept; "
                                 f"its SHA-256 starts {digest}")
        extra = "\n" + "\n".join(notes) + "\n" if notes else ""
        archive.writestr("README.txt", OPEN_IN_COMFY + extra)
    return buffer.getvalue()


def receipt_view(receipt: dict[str, Any]) -> dict[str, Any]:
    """What the UI shows for a receipt: the receipt itself, whether its seal holds, a remix link."""
    return {"receipt": receipt, "verified": receipts.verify(receipt),
            "recipe_link": receipts.recipe_link(receipts.recipe_from_receipt(receipt))}


def read_receipt_view(path: Path) -> dict[str, Any]:
    return receipt_view(json.loads(Path(path).read_text(encoding="utf-8")))
