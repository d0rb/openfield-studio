"""Record the showcase: render a spec of fictional casts and takes through a real backend.

    openfield showcase --spec showcase/spec.json [--only a,b] [--dry-run] [--force]

The spec lists the characters to generate (text to image, so they are invented and reproducible) and the
takes to render with them. Every take goes through the same pipeline the app uses, against whatever
backend is configured (never Replay), and the finished folders are slimmed (no intermediate video) into
the showcase folder that Replay plays and that `openfield export-static` publishes. A report of the real
render times is written next to the spec.

Recording is resumable: a take already recorded from an unchanged spec entry is skipped unless --force.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cast import CastStore, generated_origin
from .engine import safety
from .engine.rig import CameraRig, compile_portrait_prompt, compile_reshoot_prompt, compile_shot
from .ledger import Ledger, write_json
from .pipeline import (
    PORTRAIT_MAX,
    VIDEO_SIZES,
    DirectRequest,
    Pipeline,
    PortraitRequest,
    ReshootRequest,
)

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
STILL_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
KEEP_JSON = {"workflow.api.json", "run.json"}


class SpecError(ValueError):
    """The spec is wrong; `problems` lists everything found, not just the first."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class CastSpec:
    name: str
    description: str
    count: int = 3
    pick: int = 1
    seed: int | None = None


@dataclass(frozen=True)
class TakeSpec:
    name: str
    kind: str
    raw: dict[str, Any] = field(compare=False, default_factory=dict)

    @property
    def sha(self) -> str:
        blob = json.dumps(self.raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Spec:
    casts: tuple[CastSpec, ...]
    takes: tuple[TakeSpec, ...]
    base: Path  # relative file paths in the spec resolve against this folder


def load_spec(path: Path) -> Spec:
    """Parse and fully validate a spec before anything is rendered."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SpecError([f"cannot read {path.name}: {exc}"]) from None
    problems: list[str] = []
    base = path.parent

    casts: list[CastSpec] = []
    for index, item in enumerate(data.get("casts", [])):
        label = f"cast #{index + 1}"
        name = str(item.get("name", "")).strip()
        label = f"cast {name!r}" if name else label
        if not 1 <= len(name) <= 40:
            problems.append(f"{label}: name must be 1 to 40 characters")
        if any(c.name == name for c in casts):
            problems.append(f"{label}: duplicate cast name")
        count, pick = int(item.get("count", 3)), int(item.get("pick", 1))
        if not 1 <= count <= PORTRAIT_MAX:
            problems.append(f"{label}: count must be 1 to {PORTRAIT_MAX}")
        if not 1 <= pick <= max(count, 1):
            problems.append(f"{label}: pick must be between 1 and count")
        try:
            compile_portrait_prompt(str(item.get("description", "")))
        except ValueError as exc:
            problems.append(f"{label}: {exc}")
        casts.append(CastSpec(name, str(item.get("description", "")), count, pick, item.get("seed")))
    cast_names = {c.name for c in casts}

    takes: list[TakeSpec] = []
    for index, item in enumerate(data.get("takes", [])):
        name = str(item.get("name", "")).strip()
        label = f"take {name!r}" if name else f"take #{index + 1}"
        kind = item.get("kind")
        if not NAME.match(name):
            problems.append(f"{label}: name must be lowercase letters, digits and dashes")
        if any(t.name == name for t in takes):
            problems.append(f"{label}: duplicate take name")
        if item.get("cast") and item["cast"] not in cast_names:
            problems.append(f"{label}: cast {item['cast']!r} is not defined in casts")
        if kind == "direct":
            problems += _check_direct(label, item)
        elif kind == "reshoot":
            problems += _check_reshoot(label, item, base, cast_names)
        else:
            problems.append(f"{label}: kind must be 'direct' or 'reshoot'")
        takes.append(TakeSpec(name, str(kind), dict(item)))
    if not takes:
        problems.append("the spec has no takes")
    if problems:
        raise SpecError(problems)
    return Spec(tuple(casts), tuple(takes), base)


def _check_direct(label: str, item: dict[str, Any]) -> list[str]:
    try:
        compile_shot(CameraRig(**item.get("rig", {})), str(item.get("subject", "")), item.get("audio"),
                     prompt_only=bool(item.get("prompt_only")))
    except (ValueError, TypeError) as exc:
        return [f"{label}: {exc}"]
    if item.get("orientation", "landscape") not in VIDEO_SIZES:
        return [f"{label}: orientation must be landscape or portrait"]
    return []


def _check_reshoot(label: str, item: dict[str, Any], base: Path, cast_names: set[str]) -> list[str]:
    problems = []
    source = base / str(item.get("source", ""))
    if not item.get("source") or not source.is_file():
        problems.append(f"{label}: source clip not found ({item.get('source')!r}, relative to the spec)")
    reference = item.get("reference")
    if reference and not (base / reference).is_file():
        problems.append(f"{label}: reference image not found ({reference!r})")
    if not reference and not item.get("cast"):
        problems.append(f"{label}: give a cast or a reference image")
    try:
        compile_reshoot_prompt(str(item.get("prompt", "")), item.get("background"))
        if item.get("motion"):
            safety.require_safe(item["motion"])
    except ValueError as exc:
        problems.append(f"{label}: {exc}")
    return problems


def check_only(spec: Spec, only: set[str] | None) -> None:
    """Refuse --only names that match no take, so a typo never plans (or renders) nothing."""
    unknown = (only or set()) - {t.name for t in spec.takes}
    if unknown:
        raise SpecError([f"--only names no such take: {', '.join(sorted(unknown))}"])


def plan_text(spec: Spec, only: set[str] | None = None) -> list[str]:
    """A readable plan and render count per item, for --dry-run."""
    check_only(spec, only)
    lines = []
    selected = [t for t in spec.takes if not only or t.name in only]
    needed = {t.raw.get("cast") for t in selected if t.raw.get("cast")}
    renders = 0
    for cast in spec.casts:
        if cast.name in needed:
            lines.append(f"  cast  {cast.name:<22} {cast.count} portrait render(s)")
            renders += cast.count
    for take in selected:
        if take.kind == "direct":
            plan = compile_shot(CameraRig(**take.raw.get("rig", {})), take.raw["subject"], take.raw.get("audio"),
                                prompt_only=bool(take.raw.get("prompt_only")))
            count = sum(a.role != "repeat_hero" for a in plan.anchors) + len(plan.segments)  # a reused hero is not a render
            detail = f"{plan.move_id} ({plan.mode}), {plan.total_seconds}s"
        else:
            count, detail = 1, "motion transfer"
        renders += count
        lines.append(f"  take  {take.name:<22} {take.kind:<8} {count} render(s)  {detail}")
    lines.append(f"  total {renders} ComfyUI render(s)")
    return lines


def slim_copy(source: Path, target: Path) -> int:
    """Copy a finished take keeping what Replay and the hosted copy need; returns bytes copied.

    Kept: the final media, receipt, events, inputs, candidates, and per step the graph, run record and
    stills. Dropped: the intermediate per-step video, which is large and not needed to replay a take.
    """
    if target.exists():
        shutil.rmtree(target)
    total = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.name.endswith(".tmp"):
            continue
        rel = path.relative_to(source)
        in_run = rel.parts[0] == "runs"
        if in_run and len(rel.parts) == 3 and path.suffix.lower() not in STILL_SUFFIXES \
                and path.name not in KEEP_JSON:
            continue
        if in_run and len(rel.parts) != 3:
            continue
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        total += destination.stat().st_size
    return total


@dataclass
class Outcome:
    name: str
    kind: str
    status: str  # succeeded | failed | skipped
    take_id: str | None = None
    seconds: float | None = None
    error: str | None = None
    runs: list[dict[str, Any]] = field(default_factory=list)
    media_bytes: int = 0
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "", [], 0)} | {
            "name": self.name, "kind": self.kind, "status": self.status}


def already_recorded(out_dir: Path, take: TakeSpec) -> str | None:
    """The id of a recorded take made from this exact spec entry, if there is one."""
    for take_json in Path(out_dir).glob("*/take.json"):
        try:
            data = json.loads(take_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (data.get("showcase_name") == take.name and data.get("showcase_sha") == take.sha
                and data.get("status") == "succeeded"):
            return data["id"]
    return None


async def record(
    spec: Spec, pipeline: Pipeline, ledger: Ledger, casts: CastStore, out_dir: Path, *,
    only: set[str] | None = None, force: bool = False, log: Callable[[str], None] = print,
) -> list[Outcome]:
    """Render the selected takes (and the casts they need) and copy the results into `out_dir`."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    check_only(spec, only)
    selected = [t for t in spec.takes if not only or t.name in only]
    outcomes: list[Outcome] = []
    cast_ids: dict[str, str | None] = {}

    async def ensure_cast(name: str) -> str | None:
        if name in cast_ids:
            return cast_ids[name]
        cast = next(c for c in spec.casts if c.name == name)
        for existing in casts.list():  # reuse across runs and across takes
            if existing["name"] == name and existing.get("origin", {}).get("description") == cast.description:
                cast_ids[name] = existing["id"]
                return existing["id"]
        log(f"[cast] generating {name!r} ({cast.count} candidates)")
        made = await pipeline.start_portrait(PortraitRequest(cast.description, cast.count, cast.seed))
        await pipeline.wait(made["id"])
        take = ledger.read(made["id"])
        if take["status"] != "succeeded":
            log(f"[cast] {name!r} failed: {(take.get('error') or {}).get('message')}")
            cast_ids[name] = None
            return None
        receipt = json.loads((ledger.take_dir(take["id"]) / "receipt.json").read_text(encoding="utf-8"))
        image = ledger.take_dir(take["id"]) / "candidates" / f"{cast.pick:02d}.png"
        record_ = casts.create(name, "character", "fictional", [(image.name, image.read_bytes())],
                               origin=generated_origin(take, receipt, cast.pick))
        cast_ids[name] = record_["id"]
        return record_["id"]

    for take in selected:
        done = None if force else already_recorded(out_dir, take)
        if done:
            log(f"[skip] {take.name}: already recorded as {done}")
            outcomes.append(Outcome(take.name, take.kind, "skipped", done, note="already recorded"))
            continue
        raw = take.raw
        cast_id = await ensure_cast(raw["cast"]) if raw.get("cast") else None
        if raw.get("cast") and cast_id is None:
            outcomes.append(Outcome(take.name, take.kind, "failed", error=f"cast {raw['cast']!r} could not be made"))
            continue
        log(f"[take] {take.name} ({take.kind})")
        started = time.monotonic()
        try:
            started_take = await _start(pipeline, casts, spec, take, cast_id)
        except ValueError as exc:
            outcomes.append(Outcome(take.name, take.kind, "failed", error=str(exc)))
            continue
        await pipeline.wait(started_take["id"])
        finished = ledger.read(started_take["id"])
        wall = round(time.monotonic() - started, 1)
        if finished["status"] != "succeeded":
            message = (finished.get("error") or {}).get("message", finished["status"])
            log(f"        failed after {wall}s: {message}")
            outcomes.append(Outcome(take.name, take.kind, "failed", finished["id"], wall, message))
            continue
        ledger.update(finished["id"], showcase_name=take.name, showcase_sha=take.sha)
        size = slim_copy(ledger.take_dir(finished["id"]), out_dir / finished["id"])
        runs = _run_records(ledger.take_dir(finished["id"]))
        log(f"        ok in {wall}s, {size / 1_048_576:.1f} MB kept")
        outcomes.append(Outcome(take.name, take.kind, "succeeded", finished["id"], wall, runs=runs,
                                media_bytes=size))
    return outcomes


async def _start(pipeline: Pipeline, casts: CastStore, spec: Spec, take: TakeSpec,
                 cast_id: str | None) -> dict[str, Any]:
    raw = take.raw
    refs = casts.ref_paths(cast_id) if cast_id else []
    cast_name = casts.get(cast_id)["name"] if cast_id else None
    if take.kind == "direct":
        return await pipeline.start_direct(DirectRequest(
            subject=raw["subject"], rig=raw.get("rig", {}), cast_refs=refs, cast_name=cast_name,
            audio=raw.get("audio"), seed=raw.get("seed"), orientation=raw.get("orientation", "landscape"),
            auto_approve=raw.get("auto_approve", True), prompt_only=bool(raw.get("prompt_only"))))
    reference = spec.base / raw["reference"] if raw.get("reference") else refs[0]
    return await pipeline.start_reshoot(ReshootRequest(
        source=spec.base / raw["source"], reference=reference, prompt=raw["prompt"], seed=raw.get("seed"),
        reference_name=cast_name, background=raw.get("background"), motion=raw.get("motion")))


def _run_records(take_dir: Path) -> list[dict[str, Any]]:
    out = []
    for run_json in sorted(take_dir.glob("runs/*/run.json")):
        record_ = json.loads(run_json.read_text(encoding="utf-8"))
        out.append({"stage": record_["stage"], "template": record_["template"],
                    "seconds": record_.get("timings", {}).get("total_s")})
    return out


def write_report(outcomes: list[Outcome], path: Path, *, backend_label: str) -> dict[str, Any]:
    report = {
        "backend": backend_label, "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "takes": [o.to_dict() for o in outcomes],
        "summary": {s: sum(o.status == s for o in outcomes) for s in ("succeeded", "failed", "skipped")},
    }
    write_json(path, report)
    return report


def benchmarks_markdown(report: dict[str, Any]) -> str:
    """Render times from a recording, as a table. Only measured numbers appear."""
    lines = [
        "# Render times", "",
        f"Measured on **{report['backend']}**, recorded {report['recorded_at'][:10]}. Wall time for a whole take includes "
        "every step (stills, approvals skipped, shots, wrap-up). Times vary with the box, the queue and the clip.", "",
        "| Take | Kind | Steps | Seconds per step | Total |", "|---|---|---|---|---|",
    ]
    for item in report["takes"]:
        if item["status"] != "succeeded" or not item.get("seconds"):
            continue
        steps = item.get("runs", [])
        per = ", ".join(f"{r['template']} {r['seconds']:.0f}s" for r in steps if r.get("seconds") is not None)
        lines.append(f"| {item['name']} | {item['kind']} | {len(steps)} | {per} | {item['seconds']:.0f}s |")
    failed = [i for i in report["takes"] if i["status"] == "failed"]
    if failed:
        lines += ["", "Not recorded: " + ", ".join(f"{i['name']} ({i.get('error', 'failed')})" for i in failed)]
    return "\n".join(lines) + "\n"
