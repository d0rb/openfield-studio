#!/usr/bin/env python3
"""Submit OpenField's patched workflows to a real ComfyUI and report what its own validator says.

    python scripts/validate_on_comfy.py --comfy http://127.0.0.1:9188            # a GPU box (through the tunnel)
    python scripts/validate_on_comfy.py --comfy http://127.0.0.1:9199 --stub-models path/to/ComfyUI
                                                                                # a CPU-only ComfyUI, no weights

ComfyUI checks a prompt before it runs it: node classes, input types and ranges, links, required
inputs and that every model file name exists. This runs exactly that for each of our six workflows,
patched with sample values, so a template that has drifted, or a model file missing from the box, is
found in seconds instead of at the end of a render.

ComfyUI accepts a prompt when *any* of its output nodes validates and lists the rest in `node_errors`,
so a pass here means HTTP 200 **and** no node errors. After submitting, the job is interrupted and the
queue cleared: this checks validity, it does not render. With --stub-models, empty files named after
every required model are created in that (local, throwaway) ComfyUI so the file-name check passes; it
would fail to load them, which is expected.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openfield.engine.workflows import WORKFLOW_DIR, load_template, sample_values  # noqa: E402

TEMPLATES = ("qwen21_t2i", "qwen21_edit", "ltx25_i2v", "ltx25_flf2v", "wan_animate2", "esrgan_upscale")
MANIFEST = WORKFLOW_DIR.parent / "engine" / "manifest.json"


def request(base: str, path: str, body: dict | None = None, *, data: bytes | None = None,
            headers: dict[str, str] | None = None) -> tuple[int, Any]:
    payload = data if data is not None else (json.dumps(body).encode() if body is not None else None)
    head = headers or ({"Content-Type": "application/json"} if body is not None else {})
    req = urllib.request.Request(base.rstrip("/") + path, payload, head)
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            return err.code, (json.loads(raw) if raw.strip() else {})
        except ValueError:
            return err.code, {"error": {"message": raw[:200].decode("utf-8", "replace")}}


def upload(base: str, path: Path, content_type: str) -> str:
    """Put a file in ComfyUI's input folder (the same endpoint comfy-api-proxy uses) and return its name."""
    boundary = uuid.uuid4().hex
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\n"
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        path.read_bytes(),
        f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n".encode(),
    ]
    status, body = request(base, "/upload/image", data=b"".join(parts),
                           headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    if status != 200 or "name" not in body:
        raise RuntimeError(f"upload of {path.name} failed: HTTP {status} {body}")
    return body["name"]


def stub_models(comfy_dir: Path) -> int:
    """Empty files for every model our workflows load, so ComfyUI's file-name check can pass."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    count = 0
    for model in manifest["models"]:
        if model.get("required", True):
            target = comfy_dir / "models" / model["directory"] / model["name"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()
            count += 1
    return count


def make_samples(folder: Path) -> tuple[Path, Path]:
    from PIL import Image

    image, video = folder / "openfield_sample.png", folder / "openfield_sample.mp4"
    Image.new("RGB", (64, 64), "red").save(image)
    try:
        import imageio_ffmpeg

        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                        "-i", "testsrc2=size=320x240:rate=24:duration=2", "-pix_fmt", "yuv420p", str(video)],
                       check=True)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"could not make a sample clip: {exc}") from exc
    return image, video


def validate_one(base: str, name: str, image_name: str, video_name: str, local: tuple[Path, Path],
                 extra: dict | None = None) -> list[str]:
    """Problems ComfyUI reports for one patched workflow (empty = accepted with no node errors). `extra` adds slot
    values on top of the samples (the first-last-frame graph with two middle stills guided inside one pass)."""
    template = load_template(name, WORKFLOW_DIR)
    patched = template.patch(sample_values(template, *local) | (extra or {}))
    graph = json.loads(json.dumps(patched.graph))
    for binding in patched.assets:  # what comfy-api-proxy does after uploading an asset
        graph[binding.node]["inputs"][binding.input] = video_name if binding.input == "file" else image_name
    status, body = request(base, "/prompt", {"prompt": graph, "client_id": "openfield-validate"})
    problems: list[str] = []
    if status != 200:
        error = body.get("error", {})
        problems.append(f"HTTP {status}: {error.get('type', '')}: {error.get('message', '')}".strip())
    for node_id, info in (body.get("node_errors") or {}).items():
        for e in info.get("errors", [])[:3]:
            problems.append(f"node {node_id} ({info.get('class_type')}): {e.get('message')} {e.get('details', '')[:120]}")
    if status == 200:  # validity is all we wanted: do not render
        stop_ours(base, body.get("prompt_id"))
    return problems


def stop_ours(base: str, prompt_id: str | None) -> None:
    """Take only our own prompt off the box: drop it if still queued, interrupt it if it already started.

    Never clears the queue or interrupts blindly: the box may be rendering someone else's job.
    """
    if not prompt_id:
        return
    request(base, "/queue", {"delete": [prompt_id]})  # removes it when pending; a no-op otherwise
    _, queue = request(base, "/queue")
    running = [item[1] for item in queue.get("queue_running", []) if len(item) > 1]
    if prompt_id in running:
        request(base, "/interrupt", {"prompt_id": prompt_id})
        time.sleep(0.3)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--comfy", required=True, help="ComfyUI base URL (not the proxy)")
    parser.add_argument("--stub-models", metavar="COMFYUI_DIR",
                        help="local ComfyUI folder to fill with empty model files (CPU-only checks)")
    parser.add_argument("--only", help="comma list of: " + ", ".join(TEMPLATES))
    args = parser.parse_args(argv)

    if args.stub_models:
        print(f"created {stub_models(Path(args.stub_models))} empty model files in {args.stub_models}")
    names = [n.strip() for n in args.only.split(",")] if args.only else list(TEMPLATES)
    unknown = [n for n in names if n not in TEMPLATES]
    if unknown:
        parser.error(f"unknown template(s): {', '.join(unknown)}")

    with tempfile.TemporaryDirectory() as tmp:
        local = make_samples(Path(tmp))
        image_name = upload(args.comfy, local[0], "image/png")
        video_name = upload(args.comfy, local[1], "video/mp4")
        failures = 0
        # the first-last-frame graph is checked twice: as exported, and with two middle stills guided inside one pass
        passes = [(name, None) for name in names]
        if "ltx25_flf2v" in names:
            passes.append(("ltx25_flf2v", {"mids": [{"image": local[0], "frame_idx": 32}, {"image": local[0], "frame_idx": 64}]}))
        for name, extra in passes:
            label = f"{name} (two middle stills)" if extra else name
            problems = validate_one(args.comfy, name, image_name, video_name, local, extra)
            if problems:
                failures += 1
                print(f"[FAIL] {label}")
                for problem in problems:
                    print(f"         - {problem}")
            else:
                print(f"[ ok ] {label}: accepted by ComfyUI with no node errors")
    print(f"\n{len(passes) - failures}/{len(passes)} workflows valid on this ComfyUI")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
