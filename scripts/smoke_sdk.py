#!/usr/bin/env python3
"""Day-1 smoke test: run an API-format ComfyUI graph through comfy-sdk and report what returns.

Works against any Comfy API v2 target: Comfy Cloud (default; needs COMFY_API_KEY), a pod through
an SSH tunnel to comfy-api-proxy (COMFY_BASE_URL=http://127.0.0.1:9189), or a deployment.

    python scripts/smoke_sdk.py --graph g.api.json --list-nodes
    python scripts/smoke_sdk.py --graph g.api.json \\
        --asset 31/image=ref.png --asset 240/file=clip.mp4 --set 252/value="a red fox" --out out

`--set` and `--asset` take NODE/INPUT=VALUE (node ids may contain ':', hence the '/'). Every id
and input is checked against the graph first, because the SDK's set_input would silently create
a missing node. The run is recorded to <out>/events.jsonl (the format the Replay backend plays).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from comfy_sdk import (
    AsyncComfy,
    ComfyError,
    JobFailed,
    OutputReady,
    Preview,
    Progress,
    StatusChange,
)

EXT_BY_TYPE = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/flac": ".flac",
}


def parse_pair(spec: str, flag: str) -> tuple[str, str, str]:
    left, sep, value = spec.partition("=")
    node, slash, name = left.partition("/")
    if not (sep and slash and node and name):
        raise SystemExit(f"{flag} expects NODE/INPUT=VALUE, got {spec!r}")
    return node, name, value


def load_graph(path: Path) -> dict[str, Any]:
    graph = json.loads(path.read_text(encoding="utf-8"))
    if "nodes" in graph and "links" in graph:
        raise SystemExit("that file is a UI-format workflow; export API format (Export (API)).")
    return graph


def check_target(graph: dict[str, Any], node: str, name: str) -> None:
    if node not in graph:
        raise SystemExit(f"node {node!r} is not in the graph (try --list-nodes)")
    if name not in graph[node].get("inputs", {}):
        have = ", ".join(sorted(graph[node].get("inputs", {})))
        raise SystemExit(f"node {node} ({graph[node].get('class_type')}) has no input {name!r}; has: {have}")


def list_nodes(graph: dict[str, Any]) -> None:
    for node_id in sorted(graph, key=lambda k: [int(p) if p.isdigit() else p for p in k.split(":")]):
        entry = graph[node_id]
        title = (entry.get("_meta") or {}).get("title", "")
        literal = [k for k, v in entry.get("inputs", {}).items() if not isinstance(v, list)]
        print(f"{node_id:>10}  {entry.get('class_type', '?'):32} {title:28} literal inputs: {', '.join(literal)}")


def out_name(node_id: str, name: str, content_type: str) -> str:
    stem = f"{node_id.replace(':', '_')}__{Path(name).name}"
    return stem if Path(stem).suffix else stem + EXT_BY_TYPE.get(content_type, ".bin")


class Recorder:
    def __init__(self, path: Path, quiet: bool) -> None:
        self.t0 = time.monotonic()
        self.fh = path.open("w", encoding="utf-8")
        self.quiet = quiet
        self.previews = 0
        self.last_print = 0.0

    def write(self, kind: str, **data: Any) -> None:
        self.fh.write(json.dumps({"t": round(time.monotonic() - self.t0, 3), "kind": kind, **data}) + "\n")
        self.fh.flush()

    def handle(self, event: Any, out_dir: Path) -> None:
        if isinstance(event, Progress):
            self.write(
                "progress", value=event.value, step=event.step, steps=event.steps,
                node=event.current_node, nodes_done=event.nodes_done, nodes_total=event.nodes_total,
            )
            now = time.monotonic()
            if not self.quiet and now - self.last_print > 2:
                self.last_print = now
                print(f"  progress {event.value:5.1%}  step {event.step}/{event.steps}  node {event.current_node}")
        elif isinstance(event, Preview):
            self.previews += 1
            if self.previews == 1:
                (out_dir / "first_preview.jpg").write_bytes(event.data)
            self.write("preview", node=event.node_id, bytes=len(event.data), content_type=event.content_type)
        elif isinstance(event, OutputReady):
            o = event.output
            self.write("output", node=o.node_id, name=o.name, type=o.type, content_type=o.content_type)
            print(f"  output ready: node {o.node_id} {o.name} type={o.type} content_type={o.content_type}")
        elif isinstance(event, StatusChange):
            self.write("status", status=event.status, queue_position=event.queue_position)
            print(f"  status -> {event.status}" + (f" (queue {event.queue_position})" if event.queue_position else ""))
        else:
            self.write("other", repr=repr(event)[:200])


async def run(args: argparse.Namespace) -> int:
    graph = load_graph(Path(args.graph))
    sets = [parse_pair(s, "--set") for s in args.set or []]
    assets = [parse_pair(s, "--asset") for s in args.asset or []]
    for node, name, _ in sets + assets:
        check_target(graph, node, name)
    for _, _, path in assets:
        if not Path(path).is_file():
            raise SystemExit(f"asset file not found: {path}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = os.environ.get("COMFY_BASE_URL") or "Comfy Cloud (COMFY_BASE_URL unset)"
    print(f"target: {target}")

    async with AsyncComfy(timeout=180.0) as client:
        wf = client.workflows.from_json(graph)
        for node, name, raw in sets:
            try:
                value: Any = json.loads(raw)
            except json.JSONDecodeError:
                value = raw
            wf.set_input(node, name, value)
        for node, name, path in assets:
            wf.set_input(node, name, client.assets.from_file(path))
            print(f"asset bound: {node}/{name} <- {Path(path).name} ({Path(path).stat().st_size / 1e6:.1f} MB)")

        print("submitting (assets upload during submit)...")
        started = time.monotonic()
        job = await client.submit(wf)
        print(f"job id: {job.id}   <- recorded; recover with client.jobs.get() if this process dies")
        (out_dir / "job.json").write_text(json.dumps({"job_id": job.id, "target": target}), encoding="utf-8")
        recorder = Recorder(out_dir / "events.jsonl", args.quiet)

        async def consume() -> None:
            async for event in job.events():
                recorder.handle(event, out_dir)

        try:
            await asyncio.wait_for(consume(), timeout=args.timeout)
            await job.wait(timeout=60)
        except asyncio.TimeoutError:
            print(f"timed out after {args.timeout}s; cancelling")
            await job.cancel()
            return 3
        elapsed = time.monotonic() - started
        print(f"final status: {job.status} after {elapsed:.0f}s; {recorder.previews} preview frame(s)")
        if job.status != "succeeded":
            err = job.error
            print("job error:", json.dumps(getattr(err, "model_dump", lambda: err)(), default=str)[:2000])
            return 1

        rows = []
        for output in job.outputs:
            target_file = out_dir / out_name(output.node_id, output.name, output.content_type)
            await output.to_file(target_file)
            data = target_file.read_bytes()
            rows.append((output.node_id, output.type, output.content_type, output.size_bytes, target_file, data))
        print("\noutputs (note: type vs content_type, and reported vs real size):")
        for node, kind, ctype, reported, path, data in rows:
            digest = hashlib.sha256(data).hexdigest()[:12]
            print(f"  node {node:>8}  type={kind:6} content_type={ctype:12} reported={reported:>9} real={len(data):>9}  {path.name}  sha256:{digest}")
        if not rows:
            print("  NONE: the graph produced no outputs the API recognises")
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--graph", required=True, help="API-format workflow JSON")
    p.add_argument("--list-nodes", action="store_true", help="print node ids and literal inputs, then exit")
    p.add_argument("--set", action="append", metavar="NODE/INPUT=VALUE", help="literal input (JSON or text)")
    p.add_argument("--asset", action="append", metavar="NODE/INPUT=PATH", help="upload a file and bind it")
    p.add_argument("--out", default="smoke_out", help="output directory")
    p.add_argument("--timeout", type=float, default=1800.0, help="seconds to wait for the job")
    p.add_argument("--quiet", action="store_true", help="do not print progress lines")
    args = p.parse_args(argv)
    if args.list_nodes:
        list_nodes(load_graph(Path(args.graph)))
        return 0
    try:
        return asyncio.run(run(args))
    except JobFailed as exc:
        print(f"job failed: {exc}", file=sys.stderr)
        return 1
    except ComfyError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
