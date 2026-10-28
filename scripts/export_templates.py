#!/usr/bin/env python3
"""Export the official ComfyUI templates to API format, using the ComfyUI frontend's own converter.

The Comfy API only accepts API-format graphs, but the official templates are UI-format (and use
subgraphs). The frontend already knows how to flatten and convert them (`app.graphToPrompt()`),
so this script drives a real ComfyUI page with Playwright instead of re-implementing that.

    # ComfyUI reachable at http://127.0.0.1:9188 (an SSH tunnel to the GPU box is fine)
    pip install playwright            # uses your installed Chrome or Edge, nothing to download
    python scripts/export_templates.py --out openfield/workflows

For each template it writes <name>.api.json, plus <name>.slots.draft.json: a best-effort list of
candidate nodes for each slot the pipeline needs. The draft is a starting point only: review it
(`python scripts/smoke_sdk.py --graph <name>.api.json --list-nodes`), save it as <name>.slots.json
with the real choices, then run `python scripts/validate_workflows.py`.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_template_models as ftm  # noqa: E402

OFFICIAL = {
    "ltx25_i2v": "video_ltx2_5_i2v",
    "ltx25_flf2v": "video_ltx2_5_flf2v",
    "qwen21_t2i": "image_qwen_image_2_1_t2i",
    "qwen21_edit": "image_qwen_image_2_1_image_edit",
    "wan_animate2": "video_wan_animate2",
    "esrgan_upscale": "utility-gan_upscaler",  # plus one ImageScale: see AFTER_EXPORT
}
CONVERT_JS = """
async (workflow) => {
  const app = window.app || window.comfyApp;
  if (!app) throw new Error("ComfyUI frontend not ready: window.app is missing");
  await app.loadGraphData(workflow);
  const result = await app.graphToPrompt();
  return result.output;
}
"""
OUTPUT_CLASSES = ("SaveVideo", "SaveImage", "SaveImageAdvanced")


def add_image_scale(graph: dict[str, Any]) -> dict[str, Any]:
    """esrgan_upscale: the official graph plus one core ImageScale between ImageUpscaleWithModel and CreateVideo.

    The model always enlarges 4x, so this is the one node that lands the result on the size the slot map asks for (its
    width and height are slots; 3840 x 2160 is only the value the committed graph shows). Everything else stays as the
    frontend exported it. Refuses a template where CreateVideo no longer reads the model directly.
    """
    graph = copy.deepcopy(graph)
    model = next(k for k, node in graph.items() if node["class_type"] == "ImageUpscaleWithModel")
    create = next(k for k, node in graph.items() if node["class_type"] == "CreateVideo")
    if graph[create]["inputs"].get("images") != [model, 0]:
        raise ValueError("CreateVideo does not read ImageUpscaleWithModel directly: the official template changed")
    new_id = str(max(int(k) for k in graph if k.isdigit()) + 1)
    graph[new_id] = {
        "inputs": {"upscale_method": "area", "width": 3840, "height": 2160, "crop": "disabled", "image": [model, 0]},
        "class_type": "ImageScale", "_meta": {"title": "Upscale Image"}}
    graph[create]["inputs"]["images"] = [new_id, 0]
    return graph


AFTER_EXPORT = {"esrgan_upscale": add_image_scale}  # edits made to a graph right after the frontend exports it


def title_of(node: dict[str, Any]) -> str:
    return (node.get("_meta") or {}).get("title", "")


def candidates(graph: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Candidate nodes per pipeline slot, with the reason each was suggested."""
    out: dict[str, list[dict[str, Any]]] = {}

    def add(slot: str, node_id: str, input_name: str, why: str) -> None:
        out.setdefault(slot, []).append({"node": node_id, "input": input_name, "why": why})

    for node_id, node in graph.items():
        cls, title = node.get("class_type", ""), title_of(node).lower()
        inputs = node.get("inputs", {})
        literal = {k for k, v in inputs.items() if not (isinstance(v, list) and len(v) == 2)}
        if cls in {"PrimitiveStringMultiline", "TextEncodeQwenImage21", "CLIPTextEncode", "ComfySwitchNode"}                 and "negative" not in title and "system" not in title:
            for name in ("value", "prompt", "text", "on_false"):
                if name in literal and isinstance(inputs[name], str):
                    add("prompt", node_id, name, f"{cls} '{title_of(node)}'")
        for name in ("noise_seed", "seed"):
            if cls in {"RandomNoise", "KSampler", "SamplerCustom", "KSamplerAdvanced"} and name in literal:
                add("seed", node_id, name, cls)
        if cls == "PrimitiveInt" and "value" in literal:
            for slot in ("duration", "width", "height"):
                if slot in title:
                    add(slot, node_id, "value", f"PrimitiveInt '{title_of(node)}'")
        if cls == "LoadImage":
            for slot, hint in (("first_frame", "first"), ("last_frame", "last"), ("reference_image", "ref"),
                               ("base_image", "image")):
                if hint in title:
                    add(slot, node_id, "image", f"LoadImage '{title_of(node)}'")
            add("any_image", node_id, "image", f"LoadImage '{title_of(node)}'")
        if cls == "LoadVideo":
            add("pose_video", node_id, "file", f"LoadVideo '{title_of(node)}'")
        if cls in OUTPUT_CLASSES:
            add("output", node_id, "", f"{cls} '{title_of(node)}'")
        if cls == "PrimitiveBoolean":
            add("toggle", node_id, "value", f"PrimitiveBoolean '{title_of(node)}'")
    # a prompt primitive is the real prompt; text encoders (which may hold a negative prompt) come last
    rank = {"PrimitiveStringMultiline": 0, "ComfySwitchNode": 1, "TextEncodeQwenImage21": 2, "CLIPTextEncode": 3}
    if "prompt" in out:
        out["prompt"].sort(key=lambda c: rank.get(c["why"].split(" ")[0], 9))
    return out


def export(base_url: str, ref: str, out_dir: Path, names: list[str], headless: bool) -> int:
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    with sync_playwright() as p:
        browser = None
        for channel in ("chrome", "msedge"):
            try:
                browser = p.chromium.launch(channel=channel, headless=headless)
                break
            except Exception as exc:  # noqa: BLE001
                print(f"could not launch {channel}: {str(exc).splitlines()[0]}")
        if browser is None:
            print("no Chrome or Edge found; install one or run `playwright install chromium`", file=sys.stderr)
            return 2
        page = browser.new_page()
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(base_url, wait_until="domcontentloaded")
        page.wait_for_function("() => (window.app || window.comfyApp) && (window.app || window.comfyApp).graph", timeout=90_000)
        for name in names:
            official = OFFICIAL[name]
            try:
                template, digest, _ = ftm.fetch_template(official, ref)
                graph = AFTER_EXPORT.get(name, lambda g: g)(page.evaluate(CONVERT_JS, template))
            except Exception as exc:  # noqa: BLE001
                print(f"[FAIL] {name} ({official}): {str(exc).splitlines()[0]}")
                failures += 1
                continue
            (out_dir / f"{name}.api.json").write_text(json.dumps(graph, indent=1) + "\n", encoding="utf-8")
            draft = {"_draft": True, "source_template": official, "template_sha256": digest,
                     "candidates": candidates(graph)}
            (out_dir / f"{name}.slots.draft.json").write_text(json.dumps(draft, indent=1) + "\n", encoding="utf-8")
            print(f"[ ok ] {name}: {len(graph)} nodes -> {name}.api.json (+ slots draft)")
        browser.close()
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--comfy", default="http://127.0.0.1:9188", help="ComfyUI frontend URL")
    parser.add_argument("--out", default="openfield/workflows", help="output directory")
    parser.add_argument("--ref", default=ftm.DEFAULT_REF, help="Comfy-Org/workflow_templates git ref")
    parser.add_argument("--only", help="comma list of: " + ", ".join(OFFICIAL))
    parser.add_argument("--show", action="store_true", help="show the browser window")
    args = parser.parse_args(argv)
    names = [n.strip() for n in args.only.split(",")] if args.only else list(OFFICIAL)
    unknown = [n for n in names if n not in OFFICIAL]
    if unknown:
        parser.error(f"unknown template(s): {', '.join(unknown)}")
    return export(args.comfy, args.ref, Path(args.out), names, headless=not args.show)


if __name__ == "__main__":
    sys.exit(main())
