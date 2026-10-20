"""Take pipeline: Direct and Re-shoot as stage machines over a backend.

Every ComfyUI run is audited against the open-weights allowlist *before* it is submitted, writes
its own folder (workflow, events, media), and feeds the next stage. A finished take gets a sealed
receipt. With a locked backend (Replay) nothing is rendered: a recorded take with the same recipe
fingerprint is replayed, anything else is refused.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import secrets
import shutil
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .backends.base import Backend, BackendError, RunResult
from .backends.replay import ReplayBackend
from .engine import receipt as receipts
from .engine import video
from .engine.audit import Audit, audit_graph
from .engine.contract import check_contract
from .engine.rig import (
    CameraRig,
    ShotPlan,
    compile_portrait_prompt,
    compile_reshoot_prompt,
    compile_shot,
    compile_still_prompt,
)
from .engine.safety import require_safe
from .engine.workflows import PatchedWorkflow, Template, WorkflowError, load_template
from .ledger import TERMINAL, Ledger, replace_file, write_json

log = logging.getLogger("openfield.pipeline")

VIDEO_SIZES = {"landscape": (1280, 720), "portrait": (720, 1280)}
STILL_SIZES = {"landscape": (1344, 768), "portrait": (768, 1344)}
IDENTITY_RETRY_SEED_STEP = 7919
PORTRAIT_SIZE = 1024
RESHOOT_SIZES = {"portrait": (482, 854), "landscape": (854, 482)}  # Wan Animate 2's working size
PORTRAIT_MAX = 4


@dataclass
class DirectRequest:
    subject: str
    rig: dict[str, Any]
    cast_refs: list[Path] = field(default_factory=list)
    cast_name: str | None = None
    audio: str | None = None
    seed: int | None = None
    orientation: str = "landscape"
    auto_approve: bool = False
    identity_retry: bool = True
    prompt_only: bool = False  # quick mode: one still and a camera instruction, no anchor stills


@dataclass
class ReshootRequest:
    source: Path
    reference: Path
    prompt: str  # who the new character is
    seed: int | None = None
    reference_name: str | None = None
    background: str | None = None  # the setting; a plain studio backdrop when omitted
    motion: str | None = None  # what happens in the source clip; a neutral sentence when omitted
    owned: tuple[Path, ...] = ()  # uploaded files the pipeline deletes once the take is over


@dataclass
class PortraitRequest:
    description: str
    count: int = 3
    seed: int | None = None


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return receipts.sha256_file(path)


class TakeBus:
    """Per-take event history (memory + take-level events.jsonl) and live subscribers."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._queues: dict[str, set[asyncio.Queue[dict[str, Any] | None]]] = {}
        self._t0: dict[str, float] = {}

    def publish(self, take_id: str, event: dict[str, Any]) -> None:
        t0 = self._t0.setdefault(take_id, time.monotonic())
        event = {"t": round(time.monotonic() - t0, 3), **event}
        self._history.setdefault(take_id, []).append(event)
        path = self.ledger.take_dir(take_id) / "events.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        for queue in list(self._queues.get(take_id, ())):
            queue.put_nowait(event)
        if event.get("type") == "end":
            for queue in list(self._queues.get(take_id, ())):
                queue.put_nowait(None)

    def history(self, take_id: str) -> list[dict[str, Any]]:
        if take_id not in self._history:
            path = self.ledger.take_dir(take_id) / "events.jsonl"
            lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
            self._history[take_id] = [json.loads(ln) for ln in lines if ln.strip()]
        return self._history[take_id]

    async def subscribe(self, take_id: str, keepalive: float | None = None) -> AsyncIterator[dict[str, Any] | None]:
        """Events of a take, history first. With `keepalive`, yields None whenever that many seconds pass
        quietly, so a streaming response can keep its connection warm without owning a task for the generator."""
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._queues.setdefault(take_id, set()).add(queue)
        try:
            replayed = list(self.history(take_id))
            for event in replayed:
                yield event
            if replayed and replayed[-1].get("type") == "end":
                return
            # a take that finished without ever publishing an end (exports, or one recovered after the
            # app was killed) would leave the stream open for ever: report where it ended instead
            take = self.ledger.read(take_id)
            if take["status"] in TERMINAL:
                yield {"type": "take", "take": take}
                yield {"type": "end", "status": take["status"]}
                return
            while True:
                try:
                    event = await (asyncio.wait_for(queue.get(), keepalive) if keepalive else queue.get())
                except asyncio.TimeoutError:
                    yield None
                    continue
                if event is None:
                    return
                yield event
        finally:
            self._queues.get(take_id, set()).discard(queue)


@dataclass
class _Ctx:
    take_id: str
    kind: str
    total_stages: int = 1
    stage_index: int = 0
    run_number: int = 0
    runs: list[dict[str, Any]] = field(default_factory=list)
    audits: list[Audit] = field(default_factory=list)
    identity: dict[str, dict[str, Any]] = field(default_factory=dict)
    refs: list[Path] = field(default_factory=list)
    identity_retry: bool = True
    backend: Backend | None = None  # fixed when the take starts: switching mode mid-take must not move it
    started: float = field(default_factory=time.monotonic)


class Pipeline:
    def __init__(
        self, ledger: Ledger, backend: Callable[[], Backend], templates_dir: Path, *,
        gate: Any = None, timeout: float = 1800.0, gpu_slots: int = 1,
    ) -> None:
        self.ledger = ledger
        self.backend = backend
        self.templates_dir = Path(templates_dir)
        self.gate = gate  # a FaceGate, or a callable returning the current one
        self.timeout = timeout
        self.bus = TakeBus(ledger)
        self._gpu = asyncio.Semaphore(gpu_slots)
        self._templates: dict[str, Template] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._approvals: dict[str, asyncio.Future[list[int]]] = {}
        self._owned: dict[str, tuple[Path, ...]] = {}

    # -- templates -----------------------------------------------------------------------
    def template(self, name: str) -> Template:
        if name not in self._templates:
            try:
                template = load_template(name, self.templates_dir)
            except FileNotFoundError:
                raise WorkflowError(
                    f"workflow template {name!r} is not installed in {self.templates_dir}") from None
            problems = check_contract(name, template) + template.problems()
            if problems:
                raise WorkflowError(f"template {name!r} is not usable: " + "; ".join(problems[:4]))
            self._templates[name] = template
        return self._templates[name]

    # -- public API ----------------------------------------------------------------------
    async def start_direct(self, req: DirectRequest) -> dict[str, Any]:
        rig = CameraRig(**req.rig)
        plan = compile_shot(rig, req.subject, req.audio, prompt_only=req.prompt_only)  # validates first
        if req.orientation not in VIDEO_SIZES:
            raise ValueError("orientation must be landscape or portrait")
        seed = req.seed if req.seed is not None else secrets.randbelow(2**31)
        refs = [file_sha256(p) for p in req.cast_refs]
        recipe = {
            "kind": "direct", "subject": req.subject.strip(), "rig": asdict(rig), "audio": req.audio,
            "seed": seed, "orientation": req.orientation, "cast_refs": refs,
        }
        if req.prompt_only:
            recipe["prompt_only"] = True  # only when set, so ordinary recipes keep their fingerprint
        extras = {"cast_name": req.cast_name, "auto_approve": req.auto_approve}
        label = f"{plan.move_id.replace('_', ' ')}: {req.subject.strip()[:48]}"
        backend = self.backend()
        take = self._new_take("direct", label, recipe | extras, recipe, backend)
        if backend.locked:
            return self._spawn(take, self._replay(take["id"], backend))
        return self._spawn(take, self._run_direct(take["id"], req, rig, plan, seed, backend))

    async def start_reshoot(self, req: ReshootRequest) -> dict[str, Any]:
        for path in (req.source, req.reference):
            if not Path(path).is_file():
                raise ValueError(f"file not found: {Path(path).name}")
        compile_reshoot_prompt(req.prompt, req.background)  # validates before anything is created
        if req.motion:
            require_safe(req.motion)
        seed = req.seed if req.seed is not None else secrets.randbelow(2**31)
        recipe = {
            "kind": "reshoot", "prompt": req.prompt.strip(), "background": (req.background or "").strip(),
            "motion": (req.motion or "").strip(), "seed": seed,
            "source_sha256": file_sha256(req.source), "reference_sha256": file_sha256(req.reference),
        }
        label = f"re-shoot: {req.prompt.strip()[:48]}"
        backend = self.backend()
        take = self._new_take("reshoot", label, recipe | {"reference_name": req.reference_name}, recipe, backend)
        if backend.locked:
            _delete(req.owned)  # Replay never reads the upload
            return self._spawn(take, self._replay(take["id"], backend))
        self._owned[take["id"]] = tuple(req.owned)
        return self._spawn(take, self._run_reshoot(take["id"], req, seed, backend))

    async def start_portrait(self, req: PortraitRequest) -> dict[str, Any]:
        """Generate a few candidate portraits of an invented character; the user keeps one as a Cast."""
        prompt = compile_portrait_prompt(req.description)  # validates before anything is created
        if not 1 <= req.count <= PORTRAIT_MAX:
            raise ValueError(f"ask for between 1 and {PORTRAIT_MAX} candidates")
        seed = req.seed if req.seed is not None else secrets.randbelow(2**31)
        description = " ".join(req.description.split())
        recipe = {"kind": "portrait", "description": description, "count": req.count, "seed": seed}
        backend = self.backend()
        take = self._new_take("portrait", f"character: {description[:48]}", recipe, recipe, backend)
        if backend.locked:
            return self._spawn(take, self._replay(take["id"], backend))
        return self._spawn(take, self._run_portrait(take["id"], prompt, req.count, seed, backend))

    async def recreate(self, recorded_id: str) -> dict[str, Any]:
        """Replay a recorded take as a new take: the first-minute 'watch it, then recreate it' path."""
        backend = self.backend()
        if not isinstance(backend, ReplayBackend):
            raise BackendError(
                "replay_unavailable",
                "Recorded takes are replayed in Replay mode. With a backend connected, use Remix "
                "on the take to render it yourself.")
        match = next((r for r in backend.recorded() if r["id"] == recorded_id), None)
        if match is None:
            raise BackendError("replay_unavailable", "That recorded take is not available.")
        label = f"{match['label']} (replay)"
        take = self.ledger.create(match["kind"], label, match["recipe"],
                                  backend={"kind": backend.kind, "label": backend.label})
        take = self.ledger.update(take["id"], recipe_hash=match["recipe_hash"])
        return self._spawn(take, self._replay(take["id"], backend))

    def approve(self, take_id: str, reroll: list[int] | None = None) -> None:
        future = self._approvals.get(take_id)
        if future is None or future.done():
            raise ValueError("this take is not waiting for approval")
        future.set_result(sorted(set(reroll or [])))

    async def cancel(self, take_id: str) -> None:
        task = self._tasks.get(take_id)
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        # a task cancelled before it ever started never reaches its own handler
        if self.ledger.read(take_id)["status"] not in TERMINAL:
            self._finish(take_id, "canceled", None)
        self._release_uploads(take_id)

    async def wait(self, take_id: str) -> None:
        task = self._tasks.get(take_id)
        if task:
            await asyncio.shield(task)

    def subscribe(self, take_id: str, keepalive: float | None = None) -> AsyncIterator[dict[str, Any] | None]:
        return self.bus.subscribe(take_id, keepalive)

    # -- plumbing ------------------------------------------------------------------------
    def _new_take(self, kind: str, label: str, recipe: dict[str, Any], fp: dict[str, Any],
                  backend: Backend) -> dict[str, Any]:
        take = self.ledger.create(kind, label, recipe, backend={"kind": backend.kind, "label": backend.label})
        return self.ledger.update(take["id"], recipe_hash=fingerprint(fp))

    def _spawn(self, take: dict[str, Any], coro: Any) -> dict[str, Any]:
        take_id = take["id"]

        async def guarded() -> None:
            try:
                await coro
            except asyncio.CancelledError:
                self._finish(take_id, "canceled", None)
            except BackendError as exc:
                self._finish(take_id, "failed", exc.to_dict())
            except (WorkflowError, video.VideoError, OSError, ValueError) as exc:
                self._finish(take_id, "failed", {"code": "pipeline_error", "message": str(exc),
                                                 "retryable": False})
            except Exception as exc:  # noqa: BLE001 - a take must always end in a terminal state
                self._finish(take_id, "failed", {"code": "unexpected",
                                                 "message": f"{type(exc).__name__}: {exc}", "retryable": False})
            finally:
                self._approvals.pop(take_id, None)
                self._release_uploads(take_id)

        task = asyncio.create_task(guarded())
        task.add_done_callback(lambda done: self._task_ended(take_id, done))
        self._tasks[take_id] = task
        self.bus.publish(take_id, {"type": "take", "take": self.ledger.read(take_id)})
        return self.ledger.read(take_id)

    def _task_ended(self, take_id: str, task: asyncio.Task[None]) -> None:
        """Nothing a take's task raises may go unseen: the task is kept for the take's life, so Python would
        never report it, and the take would look busy for ever."""
        if task.cancelled() or task.exception() is None:
            return
        exc = task.exception()
        log.error("the task for %s ended with an unhandled %s", take_id, type(exc).__name__, exc_info=exc)
        with contextlib.suppress(Exception):
            if self.ledger.read(take_id)["status"] not in TERMINAL:
                self._finish(take_id, "failed", {"code": "unexpected", "message": f"{type(exc).__name__}: {exc}",
                                                 "retryable": False})

    def _release_uploads(self, take_id: str) -> None:
        """Delete the files a request uploaded for this take: they are the person's footage, kept nowhere else."""
        _delete(self._owned.pop(take_id, ()))

    def _finish(self, take_id: str, status: str, error: dict[str, Any] | None) -> None:
        error = receipts.scrub(error) if error else error  # messages may quote a path or an ffmpeg command
        take = self.ledger.update(take_id, status=status, error=error,
                                  progress=1.0 if status == "succeeded" else self.ledger.read(take_id)["progress"])
        if error:
            self.bus.publish(take_id, {"type": "error", "error": error})
        self.bus.publish(take_id, {"type": "take", "take": take})
        self.bus.publish(take_id, {"type": "end", "status": status})

    def _stage(self, ctx: _Ctx, name: str, state: str = "start") -> None:
        starting = state == "start"
        if starting:
            ctx.stage_index += 1
        changes: dict[str, Any] = {
            "stage": name,
            "progress": round((ctx.stage_index - (1 if starting else 0)) / ctx.total_stages, 3),
        }
        if starting:
            changes["status"] = "running"
        take = self.ledger.update(ctx.take_id, **changes)
        self.bus.publish(ctx.take_id, {"type": "stage", "stage": name, "index": ctx.stage_index,
                                       "total": ctx.total_stages, "state": state})
        # a late joiner replays history: every status change needs a snapshot, or it ends on a stale one
        self.bus.publish(ctx.take_id, {"type": "take", "take": take})

    # -- one ComfyUI run ---------------------------------------------------------------------
    async def _run(
        self, ctx: _Ctx, stage: str, template_name: str, values: dict[str, Any],
    ) -> tuple[RunResult, PatchedWorkflow]:
        template = self.template(template_name)
        patched = template.patch(values)
        audit = audit_graph(patched.graph)
        if not audit.passed:
            raise BackendError("audit_failed", "This workflow is not open-weights-only: "
                               + "; ".join(audit.notes[:3]), details=audit.to_dict())
        ctx.run_number += 1
        run_dir = self.ledger.run_dir(ctx.take_id, ctx.run_number, stage)
        portable, assets = _portable(patched, self.ledger.take_dir(ctx.take_id))
        write_json(run_dir / "workflow.api.json", portable)

        def on_event(event: dict[str, Any]) -> None:
            self.bus.publish(ctx.take_id, {"type": "run", "stage": stage, "run": run_dir.name,
                                           "event": event})
            if event.get("kind") == "progress":
                frac = (ctx.stage_index - 1 + event["value"]) / ctx.total_stages
                self.ledger.update(ctx.take_id, progress=round(min(frac, 0.99), 3))

        backend = ctx.backend or self.backend()
        if self._gpu.locked():
            # another take of this app is rendering: say so, or the Monitor looks idle while it waits its turn
            self.bus.publish(ctx.take_id, {"type": "run", "stage": stage, "run": run_dir.name,
                                           "event": {"kind": "status", "status": "queued", "queue_position": None}})
        async with self._gpu:
            result = await backend.run(patched, out_dir=run_dir, on_event=on_event, timeout=self.timeout)
        record = {
            "stage": stage, "template": template_name, "workflow_sha256": patched.sha256(),
            "snapped": patched.snapped, "job_id": result.job_id, "backend": result.backend,
            "timings": result.timings, "outputs": [f.to_dict() for f in result.files.values()],
            "assets": assets,
        }
        write_json(run_dir / "run.json", record)
        ctx.runs.append(record)
        ctx.audits.append(audit)
        return result, patched

    # -- stills with the identity check ----------------------------------------------------------
    async def _still(
        self, ctx: _Ctx, stage: str, template_name: str, values: dict[str, Any], *, check: bool = True,
    ) -> Path:
        result, _ = await self._run(ctx, stage, template_name, values)
        image = result.files["image"].path
        report = await self._identity(ctx, stage, image) if check else None
        if (report and report["status"] == "drift" and ctx.identity_retry
                and values.get("seed") is not None):
            retry = dict(values, seed=values["seed"] + IDENTITY_RETRY_SEED_STEP)
            second, _ = await self._run(ctx, f"{stage}_retry", template_name, retry)
            candidate = second.files["image"].path
            retry_report = await self._identity(ctx, f"{stage}_retry", candidate)
            if retry_report and (retry_report["score"] or -1) > (report["score"] or -1):
                ctx.identity[stage] = dict(retry_report, retried=True)
                return candidate
            ctx.identity[stage] = dict(report, retried=True)
        return image

    def _gate(self) -> Any:
        return self.gate() if callable(self.gate) else self.gate

    async def _check_shot(self, ctx: _Ctx, stage: str, clip: Path) -> None:
        """Report-only identity check on the middle frame of a rendered shot (re-rolling a video is too costly)."""
        if self._gate() is None or not ctx.refs:
            return
        frame = clip.with_name("identity_frame.png")
        try:
            await asyncio.to_thread(video.extract_frame, clip, frame, "mid")
        except video.VideoError:
            return  # no frame, no verdict: the take itself is fine
        await self._identity(ctx, stage, frame)

    async def _identity(self, ctx: _Ctx, stage: str, image: Path) -> dict[str, Any] | None:
        gate = self._gate()
        if gate is None or not ctx.refs:
            return None
        report = (await asyncio.to_thread(gate.check, ctx.refs, image)).to_dict()
        ctx.identity[stage] = report
        self.bus.publish(ctx.take_id, {"type": "identity", "stage": stage, "report": report})
        return report

    # -- Direct --------------------------------------------------------------------------------
    async def _run_direct(self, take_id: str, req: DirectRequest, rig: CameraRig, plan: ShotPlan,
                          seed: int, backend: Backend) -> None:
        edits = [a for a in plan.anchors if a.role == "edit"]
        ctx = _Ctx(take_id, "direct", total_stages=1 + len(edits) + len(plan.segments) + 1,
                   refs=list(req.cast_refs), identity_retry=req.identity_retry, backend=backend)
        vw, vh = VIDEO_SIZES[req.orientation]
        sw, sh = STILL_SIZES[req.orientation]
        hero_prompt = compile_still_prompt(rig, req.subject)
        if req.cast_refs:
            hero_prompt += " Keep the person's face and identity exactly as in the reference images."

        async def make_hero(seed_value: int) -> Path:
            if req.cast_refs:
                values = {"prompt": hero_prompt, "seed": seed_value, "base_image": req.cast_refs[0],
                          "refs": req.cast_refs[1:9], "custom_size": True, "width": sw, "height": sh}
                return await self._still(ctx, "hero", "qwen21_edit", values)
            values = {"prompt": hero_prompt, "seed": seed_value, "width": sw, "height": sh}
            return await self._still(ctx, "hero", "qwen21_t2i", values, check=False)

        async def make_anchor(index: int, edit_prompt: str, seed_value: int, hero: Path) -> Path:
            values: dict[str, Any] = {"prompt": edit_prompt, "seed": seed_value, "base_image": hero}
            if req.cast_refs:
                values["refs"] = req.cast_refs[:8]
            return await self._still(ctx, f"anchor_{index}", "qwen21_edit", values)

        self._stage(ctx, "hero")
        anchors: dict[int, Path] = {0: await make_hero(seed)}
        self._stage(ctx, "hero", "done")
        for a in plan.anchors:
            if a.role == "edit":
                self._stage(ctx, f"anchor_{a.index}")
                anchors[a.index] = await make_anchor(a.index, a.edit_prompt or "", seed + a.index, anchors[0])
                self._stage(ctx, f"anchor_{a.index}", "done")
            elif a.role == "repeat_hero":
                anchors[a.index] = anchors[0]
        if not req.auto_approve:  # the stills are the cheap part: look before paying for the video
            attempt = 0
            while True:
                attempt += 1
                reroll = await self._await_approval(take_id, ctx, anchors)
                if not reroll:
                    break
                if 0 in reroll:
                    anchors[0] = await make_hero(seed + 1000 * attempt)
                for a in edits:
                    if a.index in reroll or 0 in reroll:
                        anchors[a.index] = await make_anchor(
                            a.index, a.edit_prompt or "", seed + a.index + 1000 * attempt, anchors[0])
                for a in plan.anchors:
                    if a.role == "repeat_hero":
                        anchors[a.index] = anchors[0]

        clips: list[Path] = []
        for seg in plan.segments:
            self._stage(ctx, f"shoot_{seg.index + 1}")
            values = {"prompt": plan.prompt, "seed": seed + 31 * seg.index, "duration": seg.seconds,
                      "width": vw, "height": vh, "first_frame": anchors[seg.start_anchor]}
            if seg.end_anchor is not None:
                values["last_frame"] = anchors[seg.end_anchor]
            result, _ = await self._run(ctx, f"shoot_{seg.index + 1}", seg.template, values)
            clip = result.files["video"].path
            clips.append(clip)
            await self._check_shot(ctx, f"shoot_{seg.index + 1}", clip)
            self._stage(ctx, f"shoot_{seg.index + 1}", "done")

        self._stage(ctx, "finish")
        take_dir = self.ledger.take_dir(take_id)
        final = take_dir / "take.mp4"
        if len(clips) == 1:
            shutil.copyfile(clips[0], final)
        else:
            await asyncio.to_thread(video.concat, clips, final, crossfade_s=0.0, lufs=-14.0)
        stills = {i: p for i, p in anchors.items()}
        await self._seal_and_finish(ctx, final, recipe_inputs={
            "subject": req.subject.strip(), "rig": asdict(rig), "move": plan.move_id,
            "mode": plan.mode, "final_prompt": plan.prompt, "negative": plan.negative,
            "seed": seed, "orientation": req.orientation, "audio": req.audio,
            "anchors": [{"index": i, "file": str(p.relative_to(take_dir)).replace("\\", "/")}
                        for i, p in sorted(stills.items())],
            "cast": {"name": req.cast_name, "refs": [file_sha256(p) for p in req.cast_refs]},
        }, notes=list(plan.notes))

    async def _await_approval(self, take_id: str, ctx: _Ctx, anchors: dict[int, Path]) -> list[int]:
        take_dir = self.ledger.take_dir(take_id)
        shown = [{"index": i, "file": str(p.relative_to(take_dir)).replace("\\", "/")}
                 for i, p in sorted(anchors.items())]
        self.ledger.update(take_id, status="awaiting_approval", stage="review", anchors=shown,
                           identity=ctx.identity)
        self.bus.publish(take_id, {"type": "approval", "anchors": shown, "identity": ctx.identity})
        self.bus.publish(take_id, {"type": "take", "take": self.ledger.read(take_id)})
        future: asyncio.Future[list[int]] = asyncio.get_running_loop().create_future()
        self._approvals[take_id] = future
        reroll = await future
        take = self.ledger.update(take_id, status="running", stage="shoot")
        self.bus.publish(take_id, {"type": "take", "take": take})
        return reroll

    # -- Re-shoot ------------------------------------------------------------------------------
    async def _run_reshoot(self, take_id: str, req: ReshootRequest, seed: int, backend: Backend) -> None:
        ctx = _Ctx(take_id, "reshoot", total_stages=3, backend=backend)
        take_dir = self.ledger.take_dir(take_id)
        inputs = take_dir / "inputs"
        inputs.mkdir(exist_ok=True)
        self._stage(ctx, "prepare")
        source = inputs / "source.mp4"
        reference = inputs / "reference.png"
        info = await asyncio.to_thread(video.prepare_source, req.source, source)
        await asyncio.to_thread(_normalise_image, req.reference, reference)
        await asyncio.to_thread(video.extract_frame, source, inputs / "source_poster.png", "mid")
        ctx.refs = [reference]  # the new character should look like the reference: reported after the render
        self._stage(ctx, "prepare", "done")
        self._stage(ctx, "motion")
        # the template works at a fixed portrait size and centre-crops; give a landscape clip a landscape frame
        orientation = "landscape" if info.width > info.height * 1.15 else "portrait"
        width, height = RESHOOT_SIZES[orientation]
        caption = compile_reshoot_prompt(req.prompt, req.background)
        values: dict[str, Any] = {"prompt": caption, "seed": seed, "reference_image": reference,
                                  "pose_video": source, "width": width, "height": height}
        if req.motion and req.motion.strip():
            values["motion_prompt"] = " ".join(req.motion.split())
        result, _ = await self._run(ctx, "motion", "wan_animate2", values)
        await self._check_shot(ctx, "motion", result.files["video"].path)
        final = take_dir / "take.mp4"
        shutil.copyfile(result.files["video"].path, final)
        self._stage(ctx, "motion", "done")
        self._stage(ctx, "finish")
        await self._seal_and_finish(ctx, final, recipe_inputs={
            "prompt": req.prompt, "background": req.background or "", "motion": req.motion or "",
            "final_prompt": caption, "orientation": orientation, "frame": [width, height],
            "seed": seed, "reference_name": req.reference_name,
            "source": {"sha256": file_sha256(source), "seconds": round(info.duration_s, 2),
                       "size": [info.width, info.height]},
            "reference": {"sha256": file_sha256(reference)},
        }, notes=[])

    # -- Portrait candidates ---------------------------------------------------------------------
    async def _run_portrait(self, take_id: str, prompt: str, count: int, seed: int, backend: Backend) -> None:
        ctx = _Ctx(take_id, "portrait", total_stages=count + 1, backend=backend)
        folder = self.ledger.take_dir(take_id) / "candidates"
        folder.mkdir(exist_ok=True)
        made: list[Path] = []
        for index in range(1, count + 1):
            stage = f"candidate_{index}"
            self._stage(ctx, stage)
            result, _ = await self._run(ctx, stage, "qwen21_t2i", {
                "prompt": prompt, "seed": seed + index - 1, "width": PORTRAIT_SIZE, "height": PORTRAIT_SIZE})
            target = folder / f"{index:02d}.png"
            await asyncio.to_thread(_normalise_image, result.files["image"].path, target)
            made.append(target)
            self._stage(ctx, stage, "done")
        self._stage(ctx, "finish")
        take_dir = self.ledger.take_dir(take_id)
        take = self.ledger.read(take_id)
        files = [f"candidates/{path.name}" for path in made]
        raw = receipts.new_receipt(
            take_id=take_id, kind="portrait", label=take["label"],
            inputs=dict(take["recipe"], final_prompt=prompt, recipe_hash=take.get("recipe_hash")),
            workflow=self._workflow_section(ctx), models=self._model_table(ctx),
            audit=self._audit_section(ctx), backend=self._backend_section(ctx),
            outputs=[{"role": "candidate", "file": name, "node_id": "", "content_type": "image/png",
                      "sha256_before_receipt": file_sha256(take_dir / name)} for name in files])
        sealed = receipts.seal(raw)
        for name in files:
            await asyncio.to_thread(_embed_in_png, take_dir / name, sealed)
        write_json(take_dir / "receipt.json", sealed)
        outputs = [{"role": "candidate", "file": name, "kind": "image", "content_type": "image/png"}
                   for name in files]
        outputs.append({"role": "receipt", "file": "receipt.json", "kind": "json",
                        "content_type": "application/json"})
        updated = self.ledger.update(
            take_id, status="succeeded", stage="done", progress=1.0, outputs=outputs,
            candidates=files, audit=sealed["audit"])
        self._stage(ctx, "finish", "done")
        self.bus.publish(take_id, {"type": "take", "take": updated})
        self.bus.publish(take_id, {"type": "end", "status": "succeeded"})

    # -- receipt sections shared by every kind of take ---------------------------------------------
    @staticmethod
    def _model_table(ctx: _Ctx) -> list[dict[str, Any]]:
        models: dict[str, dict[str, Any]] = {}
        for audit in ctx.audits:
            for model in audit.models:
                models.setdefault(model["file"], {
                    "role": model["role"], "file": model["file"], "license": model["license_name"],
                    "open_weights": model["open_weights"], "source": model["source"],
                    "attribution": model.get("attribution")})
        return list(models.values())

    @staticmethod
    def _workflow_section(ctx: _Ctx) -> dict[str, Any]:
        run_hashes = [r["workflow_sha256"] for r in ctx.runs]
        return {"template": ctx.runs[-1]["template"] if ctx.runs else "",
                "sha256": hashlib.sha256("".join(run_hashes).encode()).hexdigest(),
                "runs": [{k: r[k] for k in ("stage", "template", "workflow_sha256", "job_id")}
                         for r in ctx.runs],
                "snapped": {r["stage"]: r["snapped"] for r in ctx.runs if r["snapped"]}}

    @staticmethod
    def _audit_section(ctx: _Ctx) -> dict[str, Any]:
        ok = all(a.passed for a in ctx.audits)
        return {"policy": "open-weights-only", "result": "pass" if ok else "fail",
                "disallowed": sorted({n for a in ctx.audits for n in a.disallowed_nodes})}

    def _backend_section(self, ctx: _Ctx) -> dict[str, Any]:
        backend = ctx.backend or self.backend()
        return {"kind": backend.kind, "label": backend.label,
                "job_id": ",".join(r["job_id"] for r in ctx.runs),
                "timings": {"total_s": round(time.monotonic() - ctx.started, 1)}}

    # -- receipt and wrap-up ---------------------------------------------------------------------
    async def _seal_and_finish(self, ctx: _Ctx, final: Path, *, recipe_inputs: dict[str, Any],
                               notes: list[str]) -> None:
        take_id = ctx.take_id
        take_dir = self.ledger.take_dir(take_id)
        take = self.ledger.read(take_id)
        info = await asyncio.to_thread(video.probe, final)
        poster = take_dir / "poster.png"
        await asyncio.to_thread(video.extract_frame, final, poster, "mid")
        statuses = [r["status"] for r in ctx.identity.values()]
        identity_status = ("drift" if "drift" in statuses else "pass" if "pass" in statuses
                           else statuses[0] if statuses else "n/a")
        scores = [r["score"] for r in ctx.identity.values() if r.get("score") is not None]
        raw = receipts.new_receipt(
            take_id=take_id, kind=ctx.kind, label=take["label"],
            inputs=dict(recipe_inputs, recipe_hash=take.get("recipe_hash")),
            workflow=self._workflow_section(ctx),
            models=self._model_table(ctx),
            audit=self._audit_section(ctx),
            identity={"status": identity_status,
                      "score": max(scores) if scores else None, "threshold": 0.363,
                      "refs_used": len(ctx.refs), "reports": ctx.identity},
            backend=self._backend_section(ctx),
            outputs=[{"role": "video", "file": "take.mp4", "node_id": "", "content_type": "video/mp4",
                      "sha256_before_receipt": file_sha256(final),
                      "seconds": round(info.duration_s, 2)}],
        )
        sealed = receipts.seal(raw)
        embedded = final.with_name("take.embedded.mp4")
        await asyncio.to_thread(receipts.embed_mp4, final, embedded, sealed)
        replace_file(embedded, final)
        await asyncio.to_thread(_embed_in_png, poster, sealed)  # the poster can be dropped back in to Remix too
        write_json(take_dir / "receipt.json", sealed)
        receipts.write_sidecar(final, sealed)
        outputs = [
            {"role": "video", "file": "take.mp4", "kind": "video", "content_type": "video/mp4"},
            {"role": "poster", "file": "poster.png", "kind": "image", "content_type": "image/png"},
            {"role": "receipt", "file": "receipt.json", "kind": "json", "content_type": "application/json"},
        ]
        updated = self.ledger.update(
            take_id, status="succeeded", stage="done", progress=1.0, outputs=outputs, notes=notes,
            identity=ctx.identity, audit=sealed["audit"], seconds=round(info.duration_s, 2),
            size=[info.width, info.height])
        self._stage(ctx, "finish", "done")
        self.bus.publish(take_id, {"type": "take", "take": updated})
        self.bus.publish(take_id, {"type": "end", "status": "succeeded"})

    # -- Replay -------------------------------------------------------------------------------
    async def _replay(self, take_id: str, backend: Backend) -> None:
        if not isinstance(backend, ReplayBackend):
            raise BackendError("replay_unavailable", "The active backend cannot replay.")
        take = self.ledger.read(take_id)
        source = backend.find(take["recipe_hash"])
        if source is None:
            raise BackendError(
                "replay_unavailable",
                "This exact recipe was not rendered, and Replay never fakes a result. Connect a "
                "backend (Comfy Cloud or a GPU box) to render new takes, or pick a recorded one.",
                details={"recorded": [r["label"] for r in backend.recorded()][:12]})
        recorded = json.loads((source / "take.json").read_text(encoding="utf-8"))
        events = _read_events(source / "events.jsonl")
        self.ledger.update(take_id, status="running", stage="replay", replay=True)
        # the media goes first: the browser asks for a preview or a still the moment its event arrives
        await asyncio.to_thread(_copy_recorded, source, self.ledger.take_dir(take_id))
        total = events[-1]["t"] if events else 0.0
        factor = min(1.0, 8.0 / total) if total > 0 else 0.0
        previous = 0.0
        for event in events:
            await asyncio.sleep(max(0.0, (event["t"] - previous) * factor))
            previous = event["t"]
            if event.get("type") in {"run", "stage", "identity", "approval"}:
                self.bus.publish(take_id, {k: v for k, v in event.items() if k != "t"} | {"replayed": True})
        updated = self.ledger.update(
            take_id, status="succeeded", stage="done", progress=1.0, outputs=recorded["outputs"],
            replay=True, replay_of=recorded["id"], notes=recorded.get("notes", []),
            candidates=recorded.get("candidates", []),
            identity=recorded.get("identity", {}), audit=recorded.get("audit"),
            seconds=recorded.get("seconds"), size=recorded.get("size"),
            anchors=recorded.get("anchors", []))
        self.bus.publish(take_id, {"type": "take", "take": updated})
        self.bus.publish(take_id, {"type": "end", "status": "succeeded"})


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _copy_recorded(source: Path, target: Path) -> None:
    """Copy what the UI shows (final media, receipt, stills, inputs) and the graphs that ran; skip
    the heavy per-segment video."""
    for name in ("take.mp4", "poster.png", "receipt.json", "take.mp4.receipt.json"):
        if (source / name).is_file():
            shutil.copyfile(source / name, target / name)
    for folder in ("inputs", "candidates"):
        if (source / folder).is_dir():
            shutil.copytree(source / folder, target / folder, dirs_exist_ok=True)
    for run in sorted((source / "runs").glob("*")) if (source / "runs").is_dir() else []:
        dest = target / "runs" / run.name
        dest.mkdir(parents=True, exist_ok=True)
        for item in run.iterdir():
            if item.is_file() and (item.suffix.lower() in {".png", ".jpg"}
                                   or item.name in {"workflow.api.json", "run.json"}):
                shutil.copyfile(item, dest / item.name)


def _portable(patched: PatchedWorkflow, take_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The patched graph with each uploaded file shown by a distinct name, so it can be loaded in ComfyUI,
    and a record of those files (their name, hash and, when they live in the take, where)."""
    graph = json.loads(json.dumps(patched.graph))
    assets: list[dict[str, Any]] = []
    used: set[str] = set()
    root = take_dir.resolve()
    for binding in patched.assets:
        suffix = binding.path.suffix.lower()
        name, n = f"{binding.slot}{suffix}", 1
        while name in used:  # several references share a slot name
            n += 1
            name = f"{binding.slot}_{n}{suffix}"
        used.add(name)
        graph[binding.node]["inputs"][binding.input] = name
        try:
            kept: str | None = binding.path.resolve().relative_to(root).as_posix()
        except ValueError:
            kept = None  # a reference photo from the Cast: only its hash is recorded
        assets.append({"node": binding.node, "input": binding.input, "slot": binding.slot, "name": name,
                       "sha256": file_sha256(binding.path), "from": kept})
    return graph, assets


def _delete(paths: tuple[Path, ...] | list[Path]) -> None:
    for path in paths:
        with contextlib.suppress(OSError):
            Path(path).unlink(missing_ok=True)


def _embed_in_png(image: Path, sealed: dict[str, Any]) -> None:
    """Write the sealed receipt into a PNG in place (through a temporary file)."""
    temporary = image.with_name(image.stem + ".embedded.png")
    receipts.embed_png(image, temporary, sealed)
    replace_file(temporary, image)


def _normalise_image(src: Path, dest: Path, max_side: int = 1536) -> None:
    try:
        with Image.open(src) as img:
            if img.width * img.height > 48_000_000:  # a tiny file can claim a gigantic canvas
                raise ValueError(f"{Path(src).name} has far too many pixels")
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((max_side, max_side))
            img.save(dest, "PNG")
    except Image.DecompressionBombError:
        raise ValueError(f"{Path(src).name} has far too many pixels") from None
