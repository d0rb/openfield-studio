#!/usr/bin/env python3
"""Render the interface's own pictures on a GPU box, through the app's own audited template.

    python scripts/render_art.py --jobs docs/art-jobs-r16.json --comfy http://127.0.0.1:9188 --out C:/openfield-scratch/r16/art

Every picture in the interface is made the way a take is: the same `qwen21_t2i` workflow, open weights only, with the
prompt, seed, size and the patched graph's hash recorded beside the file so the art carries provenance like the
footage does. This submits each job, waits for it, and writes the PNG plus a sidecar JSON next to it. Resizing to webp
and the manifest entry are a later step (scripts/gen_manifest.py), so a re-render never silently changes what ships.

A job is {"file", "prompt", "width", "height", "seed", "steps"}; width and height are snapped by the template's own
slot rules (multiples of 16, at most 2048).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openfield.engine.workflows import load_template  # noqa: E402

TEMPLATE = "qwen21_t2i"


def request(base: str, path: str, body: dict | None = None) -> tuple[int, Any]:
    payload = json.dumps(body).encode() if body is not None else None
    head = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(base.rstrip("/") + path, payload, head)
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            return err.code, (json.loads(raw) if raw.strip() else {})
        except ValueError:
            return err.code, {"error": {"message": raw[:300].decode("utf-8", "replace")}}


def fetch(base: str, name: str, subfolder: str, kind: str) -> bytes:
    query = urllib.parse.urlencode({"filename": name, "subfolder": subfolder, "type": kind})
    with urllib.request.urlopen(f"{base.rstrip('/')}/view?{query}", timeout=300) as response:
        return response.read()


def render(base: str, template, job: dict[str, Any], client: str) -> tuple[bytes, dict[str, Any]]:
    """Submit one job and return the PNG bytes and what it was made from."""
    values = {"prompt": job["prompt"], "seed": int(job["seed"]), "steps": int(job.get("steps", 25)),
              "width": int(job["width"]), "height": int(job["height"])}
    patched = template.patch(values)
    status, body = request(base, "/prompt", {"prompt": patched.graph, "client_id": client})
    if status != 200 or "prompt_id" not in body:
        raise RuntimeError(f"{job['file']}: ComfyUI refused the job: HTTP {status} {json.dumps(body)[:400]}")
    prompt_id = body["prompt_id"]
    started = time.time()
    while True:
        status, history = request(base, f"/history/{prompt_id}")
        entry = history.get(prompt_id) if status == 200 else None
        if entry and entry.get("status", {}).get("completed"):
            break
        if entry and entry.get("status", {}).get("status_str") == "error":
            raise RuntimeError(f"{job['file']}: the render failed: {json.dumps(entry.get('status'))[:400]}")
        if time.time() - started > 900:
            raise RuntimeError(f"{job['file']}: no result after 15 minutes")
        time.sleep(3)
    images = [i for out in entry.get("outputs", {}).values() for i in out.get("images", [])]
    if not images:
        raise RuntimeError(f"{job['file']}: the render produced no image")
    first = images[0]
    made = {"template": TEMPLATE, "kind": "still", "prompt": job["prompt"], "seed": values["seed"],
            "steps": values["steps"], "width": values["width"], "height": values["height"],
            "workflow_sha256": patched.sha256(), "seconds": round(time.time() - started, 1)}
    return fetch(base, first["filename"], first.get("subfolder", ""), first.get("type", "output")), made


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jobs", required=True, type=Path, help="the job list, a JSON array")
    parser.add_argument("--comfy", required=True, help="the box's ComfyUI, usually through an SSH tunnel")
    parser.add_argument("--out", required=True, type=Path, help="where the PNGs and their sidecars go")
    parser.add_argument("--only", default="", help="render only the jobs whose file name contains this")
    args = parser.parse_args()

    jobs = json.loads(args.jobs.read_text(encoding="utf-8"))
    if args.only:
        jobs = [j for j in jobs if args.only in j["file"]]
    if not jobs:
        print("nothing to render", file=sys.stderr)
        return 2
    template = load_template(TEMPLATE)
    problems = template.problems()
    if problems:
        print(f"the template itself is broken: {problems}", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    client = uuid.uuid4().hex
    failed = 0
    for n, job in enumerate(jobs, 1):
        name = job["file"]
        print(f"[{n}/{len(jobs)}] {name} ({job['width']}x{job['height']}, seed {job['seed']})", flush=True)
        try:
            png, made = render(args.comfy, template, job, client)
        except Exception as exc:  # noqa: BLE001 - one bad job must not end the session
            print(f"    failed: {exc}", file=sys.stderr, flush=True)
            failed += 1
            continue
        target = args.out / f"{Path(name).stem}.png"
        target.write_bytes(png)
        (args.out / f"{Path(name).stem}.json").write_text(json.dumps(made, indent=1), encoding="utf-8")
        print(f"    {len(png) // 1024} KB in {made['seconds']}s -> {target}", flush=True)
    print(f"{len(jobs) - failed} rendered, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
