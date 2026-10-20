"""Command line: serve, demo, doctor, audit, export-static, showcase."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import threading
import webbrowser
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as dist_version
from pathlib import Path

from . import __version__
from .config import get_settings, load_env_file


def _serve(host: str, port: int, open_browser: bool) -> int:
    import uvicorn

    from .app import create_app

    url = f"http://{'localhost' if host in {'127.0.0.1', '0.0.0.0'} else host}:{port}/"  # noqa: S104
    print(f"OpenField Studio {__version__} on {url}")
    if open_browser:
        threading.Timer(1.2, webbrowser.open, args=(url,)).start()
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    if args.backend:
        os.environ["OPENFIELD_BACKEND"] = args.backend
    settings = get_settings()
    return _serve(args.host or settings.host, args.port or settings.port, args.open)


def cmd_demo(args: argparse.Namespace) -> int:
    os.environ["OPENFIELD_BACKEND"] = "replay"
    settings = get_settings()
    return _serve(args.host or settings.host, args.port or settings.port, not args.no_open)


class Report:
    def __init__(self) -> None:
        self.blocking = 0

    def line(self, state: str, name: str, detail: str = "") -> None:
        mark = {"ok": "[ ok ]", "warn": "[warn]", "fail": "[FAIL]"}[state]
        print(f"{mark} {name}" + (f"  {detail}" if detail else ""))
        if state == "fail":
            self.blocking += 1


def cmd_doctor(args: argparse.Namespace) -> int:
    report = Report()
    settings = get_settings()
    print(f"OpenField Studio {__version__} doctor\n")

    ok = sys.version_info >= (3, 10)
    report.line("ok" if ok else "fail", "Python", sys.version.split()[0] + ("" if ok else " (need 3.10+)"))

    try:
        report.line("ok", "comfy-sdk", dist_version("comfy-sdk"))
    except PackageNotFoundError:
        report.line("fail", "comfy-sdk", 'not installed: pip install "comfy-sdk>=0.5,<0.6"')

    from .engine import video

    try:
        report.line("ok", "ffmpeg", video.ffmpeg_exe())
    except Exception as exc:  # noqa: BLE001
        report.line("fail", "ffmpeg", str(exc))

    from .engine.identity import FaceGate, default_model_dir, download_models

    gate = FaceGate()
    if not gate.available and args.fetch_models:
        print("      downloading face models (about 38 MB)...")
        download_models(default_model_dir())
        gate = FaceGate()
    if gate.available:
        report.line("ok", "face check models", str(default_model_dir()))
    else:
        report.line("warn", "face check models",
                    f"{gate.reason}. Run `openfield doctor --fetch-models` (not needed for Replay).")

    target = settings.comfy_base_url or ("Comfy Cloud" if settings.has_api_key else None)
    if target is None:
        report.line("warn", "render target", "none configured: Replay only. See docs/POD.md.")
    else:
        from .backends.sdk import SdkBackend

        health = asyncio.run(SdkBackend.from_env().health())
        report.line("ok" if health["ok"] else "fail", f"render target: {health['label']}", health["detail"])

    from .backends.replay import ReplayBackend
    from .engine.contract import CONTRACTS
    from .engine.workflows import load_template

    problems = []
    for name in CONTRACTS:
        try:
            load_template(name, settings.workflow_dir)
        except FileNotFoundError:
            problems.append(name)
    if problems:
        report.line("warn", "workflow templates", f"missing: {', '.join(problems)} (live renders need them)")
    else:
        report.line("ok", "workflow templates", str(settings.workflow_dir))

    replay = ReplayBackend([settings.takes_dir, settings.showcase_dir / "takes"])
    count = len(replay.index())
    report.line("ok" if count else "warn", "recorded takes for Replay", str(count))

    free_gb = shutil.disk_usage(settings.data_dir.parent if settings.data_dir.parent.exists() else ".").free / 1e9
    report.line("ok" if free_gb > 5 else "warn", "free disk", f"{free_gb:.0f} GB")

    print("\nReady." if report.blocking == 0 else f"\n{report.blocking} blocking problem(s) above.")
    return 1 if report.blocking else 0


def cmd_audit(args: argparse.Namespace) -> int:
    from .engine.audit import audit_graph

    graph = json.loads(Path(args.workflow).read_text(encoding="utf-8"))
    result = audit_graph(graph)
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.passed else 1


def cmd_export_static(args: argparse.Namespace) -> int:
    from .static_export import StaticExportError, export_static

    settings = get_settings()
    try:
        result = export_static(settings, Path(args.out), takes_root=Path(args.takes) if args.takes else None)
    except StaticExportError as exc:
        print(f"export-static: {exc}", file=sys.stderr)
        return 1
    megabytes = result["media_bytes"] / 1_048_576
    print(f"Wrote the hosted Replay to {result['out']}")
    print(f"  {result['takes']} take(s), {megabytes:.1f} MB of media. Serve it with any static host,")
    print(f"  or try it here:  python -m http.server 8080 --directory \"{result['out']}\"")
    return 0


def cmd_showcase(args: argparse.Namespace) -> int:
    from .backends.sdk import SdkBackend
    from .cast import CastStore
    from .engine.identity import FaceGate
    from .ledger import Ledger
    from .pipeline import Pipeline
    from .showcase import SpecError, benchmarks_markdown, load_spec, plan_text, record, write_report

    settings = get_settings()
    try:
        spec = load_spec(Path(args.spec))
    except SpecError as exc:
        print("The spec has problems:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    only = {n.strip() for n in args.only.split(",") if n.strip()} if args.only else None
    try:
        print("Plan:")
        print("\n".join(plan_text(spec, only)))
    except SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.dry_run:
        return 0
    if not settings.sdk_configured:
        print("\nThe showcase is rendered for real: set COMFY_BASE_URL (a GPU box) or COMFY_API_KEY "
              "(Comfy Cloud). See docs/POD.md.", file=sys.stderr)
        return 1
    backend = SdkBackend.from_env()
    health = asyncio.run(backend.health())
    if not health["ok"]:
        print(f"\nThe render target ({health['label']}) is not ready: {health['detail']}", file=sys.stderr)
        return 1
    print(f"\nRendering on {backend.label}.\n")

    work = Path(args.work_dir)
    out = Path(args.out) if args.out else settings.showcase_dir / "takes"
    ledger = Ledger(work / "takes")
    gate = FaceGate()
    casts = CastStore(work / "cast", lambda: gate)
    pipeline = Pipeline(ledger, lambda: backend, settings.workflow_dir, gate=lambda: gate, timeout=args.timeout)
    try:
        outcomes = asyncio.run(record(spec, pipeline, ledger, casts, out, only=only, force=args.force))
    except SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    report = write_report(outcomes, Path(args.spec).with_name("report.json"), backend_label=backend.label)
    if args.benchmarks:
        Path(args.benchmarks).write_text(benchmarks_markdown(report), encoding="utf-8", newline="\n")
    counts = report["summary"]
    print(f"\n{counts['succeeded']} recorded, {counts['skipped']} skipped, {counts['failed']} failed. "
          f"Takes are in {out}; the report is {Path(args.spec).with_name('report.json')}.")
    return 1 if counts["failed"] else 0


def main(argv: list[str] | None = None) -> int:
    load_env_file(Path(".env"))
    parser = argparse.ArgumentParser(prog="openfield", description="OpenField Studio")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the app")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--backend", choices=["auto", "sdk", "replay"])
    serve.add_argument("--open", action="store_true", help="open the browser")
    serve.set_defaults(func=cmd_serve)

    demo = sub.add_parser("demo", help="run the app on recorded takes (no key, no GPU)")
    demo.add_argument("--host")
    demo.add_argument("--port", type=int)
    demo.add_argument("--no-open", action="store_true")
    demo.set_defaults(func=cmd_demo)

    doctor = sub.add_parser("doctor", help="check this machine and the render target")
    doctor.add_argument("--fetch-models", action="store_true", help="download the face models")
    doctor.set_defaults(func=cmd_doctor)

    audit = sub.add_parser("audit", help="open-weights audit of an API-format workflow")
    audit.add_argument("workflow")
    audit.set_defaults(func=cmd_audit)

    export = sub.add_parser(
        "export-static", help="build the hosted Replay: a folder of static files, no server needed")
    export.add_argument("--out", default="site", help="output folder (default: site)")
    export.add_argument("--takes", help="folder of recorded takes (default: the bundled showcase)")
    export.set_defaults(func=cmd_export_static)

    showcase = sub.add_parser(
        "showcase", help="render a spec of fictional casts and takes into the showcase (needs a real backend)")
    showcase.add_argument("--spec", default="showcase/spec.json")
    showcase.add_argument("--only", help="comma list of take names")
    showcase.add_argument("--dry-run", action="store_true", help="validate the spec and print the plan")
    showcase.add_argument("--force", action="store_true", help="re-render takes that are already recorded")
    showcase.add_argument("--out", help="where recorded takes go (default: the bundled showcase)")
    showcase.add_argument("--work-dir", default="data-showcase", help="scratch ledger and cast (not committed)")
    showcase.add_argument("--benchmarks", metavar="FILE", help="also write the render-time table (markdown) here")
    showcase.add_argument("--timeout", type=float, default=1800.0, help="seconds allowed per render step")
    showcase.set_defaults(func=cmd_showcase)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
