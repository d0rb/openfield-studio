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
import os
import secrets
import shutil
import tempfile
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .backends.base import Backend, BackendError, RunResult
from .backends.replay import ReplayBackend
from .engine import quality, video
from .engine import receipt as receipts
from .engine import rig as rig_module
from .engine.audit import Audit, audit_graph
from .engine.contract import check_contract
from .engine.rig import (
    ANGLE_DEFAULT,
    EDITS,
    EXTEND_SECONDS,
    FACE_SWAP,
    SHOTS_BOARD,
    SHOTS_SECONDS_EACH,
    TRANSFORMATIONS,
    TRANSITION_DEFAULT,
    TRANSITION_JOIN_FADE,
    TRANSITION_SECONDS,
    TRANSITIONS,
    UPSCALE_MODEL_SCALE,
    UPSCALE_TARGETS,
    AnchorSpec,
    CameraRig,
    ShotPlan,
    angle_directive,
    compile_edit_prompt,
    compile_extend_prompt,
    compile_portrait_prompt,
    compile_prompt,
    compile_reshoot_prompt,
    compile_shot,
    compile_still_prompt,
    compile_transition_prompt,
    transition_idea,
)
from .engine.safety import require_safe
from .engine.workflows import PatchedWorkflow, Template, WorkflowError, load_template
from .ledger import TAKE_ID, TERMINAL, Ledger, replace_file, write_json

log = logging.getLogger("openfield.pipeline")

VIDEO_SIZES = {"landscape": (1280, 720), "portrait": (720, 1280)}
STILL_SIZES = {"landscape": (1344, 768), "portrait": (768, 1344)}
IDENTITY_RETRY_SEED_STEP = 7919
PORTRAIT_SIZE = 1024
RESHOOT_SIZES = {"portrait": (482, 854), "landscape": (854, 482)}  # Wan Animate 2's working size
PORTRAIT_MAX = 4
FACE_TRACK_FPS = 4  # how often a tracked reframe (rig.TRACKED) looks for the face in the render


@dataclass
class DirectRequest:
    subject: str
    rig: dict[str, Any]
    cast_refs: list[Path] = field(default_factory=list)
    cast_name: str | None = None
    audio: str | None = None
    line: str | None = None  # a spoken line, in the prompt as quoted speech; LTX writes the voice with the picture
    delivery: str = "natural"  # a rig.DELIVERIES id
    language: str | None = None  # named in the prompt when given; LTX otherwise assumes English
    action: str | None = None  # what happens: in the video prompt only, so the hero still shows the moment before it
    seed: int | None = None
    orientation: str = "landscape"
    auto_approve: bool = False
    identity_retry: bool = True
    prompt_only: bool = False  # quick mode: one still and a camera instruction, no anchor stills
    source: Path | None = None  # the person's own still as the hero: no text-to-image run, anchors edited from it
    owned: tuple[Path, ...] = ()  # uploaded files the pipeline deletes once the take is over
    quality: str = "standard"  # draft | standard | fine: still and video sizes, still steps (engine/quality.py)


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
    notes: tuple[str, ...] = ()  # what a reader should know about the source, kept in the take and its receipt
    face_only: bool = False  # keep the clip's look: swap only the face (from face_refs) on its first frame, then re-perform
    face_refs: list[Path] = field(default_factory=list)  # a Cast's reference images, for face_only


@dataclass
class TransitionRequest:
    first: str  # the take that plays first: the bridge starts on its last frame
    second: str  # the take that plays after it: the bridge lands on its first frame
    style: str = TRANSITION_DEFAULT  # a rig.TRANSITIONS id
    seconds: int = 2  # the bridge's length, one of rig.TRANSITION_SECONDS
    seed: int | None = None
    idea: str | None = None  # how the first shot becomes the second, in words (optional)


@dataclass
class ExtendRequest:
    take: str  # the finished take whose last frame the extension starts from
    seconds: int = 3  # how many seconds to add, one of rig.EXTEND_SECONDS
    seed: int | None = None


@dataclass
class UpscaleRequest:
    take: str  # the finished take to enlarge: the clip it holds goes to the upscaler as it is
    target: str = "4k"  # a rig.UPSCALE_TARGETS id
    seed: int | None = None  # accepted so every request reads alike; Real-ESRGAN has no sampler, so it is not in the recipe


@dataclass
class EditRequest:
    preset: str  # a rig.EDITS id
    detail: str | None = None  # the person's words: what to remove, the outfit, the light, the edit
    source: Path | None = None  # an uploaded still
    take: str | None = None  # or a finished take: its first approved still, or one of its stills by path (`still`)
    still: str | None = None  # a still inside that take's folder (a Shots setup, an anchor)
    cast_refs: list[Path] = field(default_factory=list)  # the face or person put in, for the swaps
    cast_name: str | None = None
    seed: int | None = None
    owned: tuple[Path, ...] = ()


@dataclass
class ShotsRequest:
    source: Path | None = None  # the person's own still
    take: str | None = None  # or a finished take: its first approved still (a Direct take) or its poster
    cast_refs: list[Path] = field(default_factory=list)
    cast_name: str | None = None
    seed: int | None = None
    quality: str = "standard"
    owned: tuple[Path, ...] = ()  # uploaded files the pipeline deletes once the take is over


# one Real-ESRGAN pass holds every frame at 4x, twice (float32): past this a 62 GB box runs out of memory
UPSCALE_MAX_BYTES = 24 * 2**30  # OPENFIELD_UPSCALE_MAX_GB sets another limit (a box with more memory); read on each request


def upscale_max_bytes() -> int:
    """The memory one upscale may take: OPENFIELD_UPSCALE_MAX_GB when it is a positive number, else UPSCALE_MAX_BYTES."""
    try:
        gb = float(os.environ.get("OPENFIELD_UPSCALE_MAX_GB", ""))
    except ValueError:
        return UPSCALE_MAX_BYTES
    return int(gb * 2**30) if 0 < gb < float("inf") else UPSCALE_MAX_BYTES


BRIDGE_SIDE = (512, 1920)  # the LTX first-last-frame template's width and height limits


def bridge_size(width: int, height: int) -> tuple[int, int]:
    """The bridge's frame: the first take's aspect scaled into the template's limits, in multiples of 32."""
    low, high = BRIDGE_SIDE
    if width <= 0 or height <= 0:
        return 1280, 704
    factor = max(1.0, low / min(width, height))
    factor = min(factor, high / max(width, height))
    snap = lambda v: min(high, max(low, int(v * factor) // 32 * 32))  # noqa: E731
    return snap(width), snap(height)


def upscale_size(width: int, height: int, target: str) -> tuple[int, int]:
    """The frame an upscale lands on: the target's long side, the take's own shape, both sides even (the video is yuv420p)."""
    if target not in UPSCALE_TARGETS:
        raise ValueError(f"unknown upscale target: {target!r} (one of {', '.join(UPSCALE_TARGETS)})")
    if width <= 0 or height <= 0:
        raise ValueError("that take's size is not known")
    factor = UPSCALE_TARGETS[target] / max(width, height)

    def even(side: int) -> int:
        return max(2, round(side * factor / 2) * 2)

    return even(width), even(height)


def recipe_detail(detail: str | None) -> str:
    return " ".join((detail or "").split())


def describe_take(take: dict[str, Any]) -> str:
    """What a take shows, in the words it was made from: a Direct subject, a Re-shoot character, else its label."""
    recipe = take.get("recipe") or {}
    return str(recipe.get("subject") or recipe.get("prompt") or take.get("label") or "")


def recipe_rig(rig: CameraRig) -> dict[str, Any]:
    """The rig as a recipe records it: a preset appears only when one is set, so recipes without one keep their fingerprint."""
    data = asdict(rig)
    for key in ("effect", "grade", "score", "soundscape"):  # a preset at its default is left out, so recipes made before it existed keep their fingerprint
        if data.get(key, "none") == "none":
            data.pop(key, None)
    if data.get("angle", ANGLE_DEFAULT) == ANGLE_DEFAULT:  # the same rule for the camera's start: as shot adds nothing
        data.pop("angle", None)
    return data


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
    skipped: dict[str, str] = field(default_factory=dict)  # stages whose identity check was skipped on purpose, and why
    refs: list[Path] = field(default_factory=list)
    identity_retry: bool = True
    backend: Backend | None = None  # fixed when the take starts: switching mode mid-take must not move it
    started: float = field(default_factory=time.monotonic)


class Pipeline:
    def __init__(
        self, ledger: Ledger, backend: Callable[[], Backend], templates_dir: Path, *,
        gate: Any = None, timeout: float = 1800.0, gpu_slots: int = 1, shelves: tuple[Path, ...] | list[Path] = (),
    ) -> None:
        self.ledger = ledger
        self.shelves = tuple(Path(s) for s in shelves)  # read-only folders of recorded takes a transition may join
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
        plan = compile_shot(rig, req.subject, req.audio, prompt_only=req.prompt_only,
                            line=req.line, delivery=req.delivery, language=req.language,
                            action=req.action)  # validates first
        if req.source is not None and rig_module.dresses_down(req.subject, req.action):  # a real photo: an edit's rule
            _delete(req.owned)
            raise ValueError("A shot from your own image never puts the person in underwear, swimwear or lingerie, or makes "
                             "clothes see-through. Describe a different scene.")
        if req.orientation not in VIDEO_SIZES:
            raise ValueError("orientation must be landscape or portrait")
        tier = quality.check(req.quality)
        seed = req.seed if req.seed is not None else secrets.randbelow(2**31)
        refs = [file_sha256(p) for p in req.cast_refs]
        recipe = {
            "kind": "direct", "subject": req.subject.strip(), "rig": recipe_rig(rig), "audio": req.audio,
            "seed": seed, "orientation": req.orientation, "cast_refs": refs,
        }
        if req.prompt_only:
            recipe["prompt_only"] = True  # only when set, so ordinary recipes keep their fingerprint
        if any(s.mids for s in plan.segments):
            recipe["single_pass"] = True  # the same rule: a one-pass shot is a different recording from its segmented twin
        if plan.dialogue:  # a spoken line is part of the recipe only when there is one, so silent recipes keep their fingerprint
            recipe["line"] = plan.dialogue["line"]
            recipe["delivery"] = plan.dialogue["delivery"]
            if plan.dialogue.get("language"):
                recipe["language"] = plan.dialogue["language"]
        if plan.action:
            recipe["action"] = plan.action  # the same rule: present only when the take has an action
        if tier != quality.DEFAULT:
            recipe["quality"] = tier  # the same rule: standard is what every earlier recipe rendered at
        if req.source is not None:
            if not Path(req.source).is_file():
                _delete(req.owned)
                raise ValueError("the source image was not found")
            recipe["source_sha256"] = file_sha256(req.source)  # the same rule: present only for a sourced hero
        extras = {"cast_name": req.cast_name, "auto_approve": req.auto_approve}
        label = f"{plan.move_id.replace('_', ' ')}: {req.subject.strip()[:48]}"
        backend = self.backend()
        take = self._new_take("direct", label, recipe | extras, recipe, backend)
        if backend.locked:
            _delete(req.owned)  # Replay never reads the upload
            return self._replaying(take, backend)
        if req.owned:
            self._owned[take["id"]] = tuple(req.owned)
        return self._spawn(take, self._run_direct(take["id"], req, rig, plan, seed, backend))

    async def start_reshoot(self, req: ReshootRequest) -> dict[str, Any]:
        for path in (req.source, req.reference):
            if not Path(path).is_file():
                raise ValueError(f"file not found: {Path(path).name}")
        compile_reshoot_prompt(req.prompt, req.background)  # validates before anything is created
        if req.motion:
            require_safe(req.motion)
        if req.face_only and not req.face_refs:
            raise ValueError("swapping only the face needs a Cast: a face is only taken from a Cast, where consent is recorded")
        seed = req.seed if req.seed is not None else secrets.randbelow(2**31)
        recipe = {
            "kind": "reshoot", "prompt": req.prompt.strip(), "background": (req.background or "").strip(),
            "motion": (req.motion or "").strip(), "seed": seed,
            "source_sha256": file_sha256(req.source), "reference_sha256": file_sha256(req.reference),
        }
        if req.face_only:  # only when set, so earlier re-shoot recipes keep their fingerprint
            recipe["face_only"] = True
            recipe["face_refs"] = [file_sha256(p) for p in req.face_refs]
        label = f"re-shoot: {req.prompt.strip()[:48]}"
        backend = self.backend()
        take = self._new_take("reshoot", label, recipe | {"reference_name": req.reference_name}, recipe, backend)
        if backend.locked:
            _delete(req.owned)  # Replay never reads the upload
            return self._replaying(take, backend)
        self._owned[take["id"]] = tuple(req.owned)
        return self._spawn(take, self._run_reshoot(take["id"], req, seed, backend))

    def finished_take(self, take_id: str) -> tuple[dict[str, Any], Path]:
        """A finished take by id, from this install's ledger or a recorded shelf: its take.json and its folder."""
        if not isinstance(take_id, str) or not TAKE_ID.match(take_id):
            raise ValueError("that is not a take id")
        for root in (self.ledger.root, *self.shelves):
            folder = Path(root) / take_id
            try:
                take = json.loads((folder / "take.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if take.get("status") == "succeeded" and (folder / "take.mp4").is_file():
                return take, folder
        raise ValueError(f"{take_id} is not a finished take with a video")

    @staticmethod
    def take_still(take: dict[str, Any], folder: Path) -> Path:
        """The still a finished take stands for: a Direct take's first approved still, else its poster."""
        try:
            anchors = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))["inputs"].get("anchors") or []
        except (OSError, ValueError, KeyError, TypeError):
            anchors = []
        candidates = [anchors[0].get("file")] if anchors and isinstance(anchors[0], dict) else []
        for name in [*candidates, "poster.png"]:
            if not isinstance(name, str):
                continue
            path = (folder / name).resolve()
            if folder.resolve() in path.parents and path.is_file():
                return path
        raise ValueError(f"{take.get('id', 'that take')} has no still to start from")

    @staticmethod
    def still_in(folder: Path, name: str) -> Path:
        """A still inside a take folder, by its relative path; never a path outside it."""
        path = (folder / name).resolve()
        if folder.resolve() not in path.parents or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} \
                or not path.is_file():
            raise ValueError("that still is not in the take")
        return path

    async def start_edit(self, req: EditRequest) -> dict[str, Any]:
        """One still changed by words (Qwen-Image 2.1), with a Cast's references when a face or a person goes in."""
        try:
            prompt = compile_edit_prompt(req.preset, req.detail)  # validates the preset and the words
            if EDITS[req.preset].needs_cast and not req.cast_refs:
                raise ValueError("pick a Cast: a face or a person is only taken from a Cast, where consent is recorded")
            if (req.source is None) == (req.take is None):
                raise ValueError("edit one still: an upload or a take")
            take = None
            if req.take is not None:
                take, folder = self.finished_take(req.take)
                still = self.still_in(folder, req.still) if req.still else self.take_still(take, folder)
            else:
                still = Path(req.source)
                if not still.is_file():
                    raise ValueError("the source image was not found")
        except ValueError:
            _delete(req.owned)
            raise
        seed = req.seed if req.seed is not None else secrets.randbelow(2**31)
        recipe: dict[str, Any] = {
            "kind": "edit", "preset": req.preset, "detail": " ".join((req.detail or "").split()),
            "source_sha256": file_sha256(still), "seed": seed, "cast_refs": [file_sha256(p) for p in req.cast_refs],
        }
        if req.take is not None:
            recipe["take"] = req.take
            if req.still:
                recipe["still"] = still.relative_to(folder.resolve()).as_posix()
        label = f"{EDITS[req.preset].label.lower()}: {describe_take(take)[:40] if take else 'your image'}"
        backend = self.backend()
        record = self._new_take("edit", label, recipe | {"cast_name": req.cast_name}, recipe, backend)
        if backend.locked:
            _delete(req.owned)  # Replay never reads the upload
            return self._replaying(record, backend)
        if req.owned:
            self._owned[record["id"]] = tuple(req.owned)
        return self._spawn(record, self._run_edit(record["id"], req, prompt, still, seed, backend))

    async def start_shots(self, req: ShotsRequest) -> dict[str, Any]:
        """One still re-shot as a board of nine setups (Qwen-Image edits), each checked like an anchor."""
        try:
            if (req.source is None) == (req.take is None):
                raise ValueError("start the board from one image: an upload or a take")
            tier = quality.check(req.quality)
            take = None
            if req.take is not None:
                take, folder = self.finished_take(req.take)
                still = self.take_still(take, folder)
            else:
                still = Path(req.source)
                if not still.is_file():
                    raise ValueError("the source image was not found")
        except ValueError:
            _delete(req.owned)
            raise
        seed = req.seed if req.seed is not None else secrets.randbelow(2**31)
        recipe: dict[str, Any] = {
            "kind": "shots", "source_sha256": file_sha256(still), "board": [a for a, _ in SHOTS_BOARD],
            "seed": seed, "cast_refs": [file_sha256(p) for p in req.cast_refs],
        }
        if req.take is not None:
            recipe["take"] = req.take
        if tier != quality.DEFAULT:
            recipe["quality"] = tier
        label = f"shots: {describe_take(take)[:48]}" if take else "shots: your image"
        backend = self.backend()
        record = self._new_take("shots", label, recipe | {"cast_name": req.cast_name}, recipe, backend)
        if backend.locked:
            _delete(req.owned)  # Replay never reads the upload
            return self._replaying(record, backend)
        if req.owned:
            self._owned[record["id"]] = tuple(req.owned)
        return self._spawn(record, self._run_shots(record["id"], req, still, seed, tier, backend))

    async def start_transition(self, req: TransitionRequest) -> dict[str, Any]:
        """Bridge two finished takes: one LTX 2.5 render from the first's last frame to the second's first frame."""
        if req.style not in TRANSITIONS:
            raise ValueError(f"unknown transition style: {req.style!r}")
        if req.seconds not in TRANSITION_SECONDS:
            raise ValueError(f"a transition lasts {', '.join(map(str, TRANSITION_SECONDS))} seconds")
        if req.first == req.second:
            raise ValueError("pick two different takes")
        first, first_dir = self.finished_take(req.first)
        second, second_dir = self.finished_take(req.second)
        prompt = compile_transition_prompt(req.style, describe_take(first), describe_take(second), req.idea)  # validates first
        seed = req.seed if req.seed is not None else secrets.randbelow(2**31)
        recipe = {"kind": "transition", "first": req.first, "second": req.second, "style": req.style,
                  "seconds": req.seconds, "seed": seed}
        if transition_idea(req.idea):  # only when set, so recorded transitions keep their fingerprint
            recipe["idea"] = transition_idea(req.idea)
        label = f"{TRANSITIONS[req.style].label.lower()}: {describe_take(first)[:28]} to {describe_take(second)[:28]}"
        backend = self.backend()
        take = self._new_take("transition", label, recipe, recipe, backend)
        if backend.locked:
            return self._replaying(take, backend)
        return self._spawn(take, self._run_transition(take["id"], req, prompt, first_dir, second_dir, seed, backend))

    async def start_extend(self, req: ExtendRequest) -> dict[str, Any]:
        """Continue a finished take from its last frame: one LTX 2.5 image-to-video render, then join original + extension."""
        if req.seconds not in EXTEND_SECONDS:
            raise ValueError(f"an extension lasts {', '.join(map(str, EXTEND_SECONDS))} seconds")
        take, take_dir = self.finished_take(req.take)
        shot, shot_dir = self._extended_shot(take, take_dir)
        prompt = compile_extend_prompt(self._continuing_words(shot, shot_dir))  # validates first
        seed = req.seed if req.seed is not None else secrets.randbelow(2**31)
        recipe = {"kind": "extend", "take": req.take, "seconds": req.seconds, "seed": seed}
        label = f"extend: {describe_take(shot)[:48]}"
        backend = self.backend()
        record = self._new_take("extend", label, recipe, recipe, backend)
        if backend.locked:
            return self._replaying(record, backend)
        return self._spawn(record, self._run_extend(record["id"], req, prompt, take_dir, seed, backend))

    def _extended_shot(self, take: dict[str, Any], folder: Path) -> tuple[dict[str, Any], Path]:
        """The shot an extension continues: an extension of an extension (or of an upscale) goes back to the take they came from."""
        seen: set[str] = set()
        while take.get("kind") in ("extend", "upscale") and take.get("id") not in seen:
            seen.add(take.get("id"))
            try:
                take, folder = self.finished_take((take.get("recipe") or {}).get("take"))
            except ValueError:
                break
        return take, folder

    @staticmethod
    def _continuing_words(take: dict[str, Any], folder: Path) -> str:
        """The shot in words for its extension: a Direct take's subject, look, move and sound, without what happens once in
        it (the spoken line, the action, an effect or a transformation), so the extension never replays them."""
        recipe = take.get("recipe") or {}
        if take.get("kind") == "direct" and recipe.get("subject"):
            with contextlib.suppress(TypeError, ValueError):  # a recipe this version cannot read keeps the receipt's prompt
                rig = CameraRig(**dict(recipe.get("rig") or {}, effect="none"))
                # the extension continues the take as delivered: a mirrored or reversed move keeps its own words here, not
                # the twin's it was rendered with (they would send the camera the other way)
                return compile_prompt(rig, str(recipe["subject"]), recipe.get("audio"), as_delivered=True)
        try:
            receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            receipt = {}
        return (receipt.get("inputs") or {}).get("final_prompt") or describe_take(take)

    async def start_upscale(self, req: UpscaleRequest) -> dict[str, Any]:
        """Enlarge a finished take: Real-ESRGAN x4plus (the official video-upscale graph), resized to 2K or 4K."""
        if req.target not in UPSCALE_TARGETS:
            raise ValueError(f"unknown upscale target: {req.target!r} (one of {', '.join(UPSCALE_TARGETS)})")
        source, folder = self.finished_take(req.take)
        if source.get("kind") == "upscale":
            raise ValueError("that take is already an upscale: upscale the take it came from instead (a second pass "
                             "would run the 4x model on frames that are already large)")
        width, height = await self._take_size(source, folder)
        if max(width, height) >= UPSCALE_TARGETS[req.target]:
            raise ValueError(f"that take is already {width}x{height}: pick a size larger than it")
        try:
            info = await asyncio.to_thread(video.probe, folder / "take.mp4")
        except video.VideoError:
            raise ValueError(f"{req.take}: its video cannot be read") from None
        frames = max(1, round((info.duration_s or 0) * (info.fps or 24)))
        peak = frames * (UPSCALE_MODEL_SCALE * width) * (UPSCALE_MODEL_SCALE * height) * 3 * 4 * 2
        if peak > upscale_max_bytes():  # the graph upscales every frame in one batch: past this it takes the server down
            raise ValueError(f"that take is too long to upscale in one pass: {frames} frames at {width}x{height} would need "
                             f"about {peak / 2**30:.0f} GB of memory; upscale a shorter or Draft take")
        size = upscale_size(width, height, req.target)
        recipe = {"kind": "upscale", "take": req.take, "target": req.target}
        label = f"upscale {req.target.upper()}: {describe_take(source)[:44]}"
        backend = self.backend()
        take = self._new_take("upscale", label, recipe, recipe, backend)
        if backend.locked:
            return self._replaying(take, backend)
        # the model enlarges 4x: a target above that needs a plain enlargement after it, and 'area' does not interpolate
        method = "bicubic" if UPSCALE_TARGETS[req.target] > UPSCALE_MODEL_SCALE * max(width, height) else "area"
        return self._spawn(take, self._run_upscale(take["id"], req, folder, size, method, backend))

    async def _take_size(self, take: dict[str, Any], folder: Path) -> tuple[int, int]:
        """A finished take's frame size: what its take.json recorded, else what its video says."""
        recorded = take.get("size")
        if isinstance(recorded, list) and len(recorded) == 2 and all(isinstance(v, int) and v > 0 for v in recorded):
            return recorded[0], recorded[1]
        try:
            info = await asyncio.to_thread(video.probe, folder / "take.mp4")
        except video.VideoError:
            raise ValueError(f"{take.get('id', 'that take')}: its video cannot be read") from None
        return info.width, info.height

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
            return self._replaying(take, backend)
        return self._spawn(take, self._run_portrait(take["id"], prompt, req.count, seed, backend))

    def _replaying(self, take: dict[str, Any], backend: Backend) -> dict[str, Any]:
        """A take Replay will play back: marked from the first snapshot, so the screen never says it is rendering."""
        take = self.ledger.update(take["id"], replay=True)
        return self._spawn(take, self._replay(take["id"], backend))

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
        return self._replaying(take, backend)

    def estimate_direct(self, *, quality_tier: str, movement: str, duration_seconds: int, prompt_only: bool = False,
                        effect: str = "none", angle: str = ANGLE_DEFAULT,
                        orientation: str = "landscape", source: bool = False, limit: int = 8) -> dict[str, Any]:
        """How long a shot like this took here: the median of this install's own finished renders of the same shape
        (tier, mode, number of stills and shots) on the backend in use. Render time only, approvals not counted; null
        when nothing comparable was measured. Never a figure from somewhere else."""
        tier = quality.check(quality_tier)
        backend = self.backend()
        try:
            wanted = compile_shot(CameraRig(movement=movement, duration_seconds=int(duration_seconds), effect=effect, angle=angle),
                                  "x", None,
                                  prompt_only=prompt_only)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"cannot estimate that shot: {exc}") from None
        shape = (tier, wanted.mode, sum(a.role != "repeat_hero" for a in wanted.anchors) - (1 if source else 0) + (1 if wanted.angle else 0),
                 len(wanted.segments), tuple(s.template for s in wanted.segments), orientation)  # a sourced hero is no render
        samples: list[float] = []
        for take in self.ledger.list(kind="direct", limit=400):
            if take.get("status") != "succeeded" or take.get("replay") or (take.get("backend") or {}).get("label") != backend.label:
                continue
            recipe = take.get("recipe") or {}
            try:
                plan = compile_shot(CameraRig(**recipe.get("rig", {})), recipe.get("subject") or "x", recipe.get("audio"),
                                    prompt_only=bool(recipe.get("prompt_only")), line=recipe.get("line"),
                                    delivery=recipe.get("delivery") or "natural", language=recipe.get("language"),
                                    action=recipe.get("action"))
            except (ValueError, TypeError):
                continue
            stills = sum(a.role != "repeat_hero" for a in plan.anchors) - (1 if recipe.get("source_sha256") else 0) + (1 if plan.angle else 0)
            have = (recipe.get("quality", quality.DEFAULT), plan.mode, stills, len(plan.segments),
                    tuple(s.template for s in plan.segments), recipe.get("orientation", "landscape"))
            if have != shape:
                continue
            seconds = _render_seconds(self.ledger.take_dir(take["id"]))
            if seconds is not None:
                samples.append(seconds)
            if len(samples) >= limit:
                break
        if not samples:
            return {"seconds": None, "low": None, "high": None, "samples": 0, "backend": backend.label,
                    "basis": "render time, approvals not counted"}
        ordered = sorted(samples)
        middle = len(ordered) // 2
        median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
        return {"seconds": round(median, 1), "low": round(ordered[0], 1), "high": round(ordered[-1], 1),
                "samples": len(samples), "backend": backend.label, "basis": "render time, approvals not counted"}

    def approve(self, take_id: str, reroll: list[int] | None = None) -> None:
        future = self._approvals.get(take_id)
        if future is None or future.done():
            raise ValueError("this take is not waiting for approval")
        chosen = sorted(set(reroll or []))
        recipe = self.ledger.read(take_id).get("recipe", {})
        # the photo itself is never re-rolled; an angled still made from it is (re-roll 0 re-shoots the angle)
        if 0 in chosen and recipe.get("source_sha256") and not (recipe.get("rig") or {}).get("angle"):
            raise ValueError("the hero is your photo and is not re-rolled; re-roll the anchors, or cancel and pick another image")
        future.set_result(chosen)

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
        faces = (report or {}).get("faces_in_candidate") or 0
        doubled = faces > 1 and len(ctx.refs) > 0  # a second face in a one-character still: the edit duplicated the person
        if (report and (report["status"] == "drift" or doubled) and ctx.identity_retry
                and values.get("seed") is not None):
            retry = dict(values, seed=values["seed"] + IDENTITY_RETRY_SEED_STEP)
            second, _ = await self._run(ctx, f"{stage}_retry", template_name, retry)
            candidate = second.files["image"].path
            retry_report = await self._identity(ctx, f"{stage}_retry", candidate)
            if retry_report:
                retry_faces = retry_report.get("faces_in_candidate") or 0
                better_score = (retry_report["score"] or -1) > (report["score"] or -1)
                fewer_faces = doubled and 0 < retry_faces < faces and retry_report["status"] == "pass"
                if better_score or fewer_faces:
                    ctx.identity[stage] = dict(retry_report, retried=True)
                    return candidate
            ctx.identity[stage] = dict(report, retried=True)
        return image

    def _gate(self) -> Any:
        return self.gate() if callable(self.gate) else self.gate

    async def _check_shot(self, ctx: _Ctx, stage: str, clip: Path) -> None:
        """Report-only identity check on a rendered shot: the best of its first, middle and last frames, because a
        face turned away mid-clip is not a lost identity (re-rolling a video is too costly)."""
        gate = self._gate()
        if gate is None or not ctx.refs:
            return
        reports: list[dict[str, Any]] = []
        for at in ("first", "mid", "last"):
            frame = clip.with_name("identity_frame.png" if at == "mid" else f"identity_frame_{at}.png")
            try:
                await asyncio.to_thread(video.extract_frame, clip, frame, at)
            except video.VideoError:
                continue  # no frame, no verdict from it
            report = (await asyncio.to_thread(gate.check, ctx.refs, frame)).to_dict()
            reports.append(dict(report, frame=at))
        if not reports:
            return  # no frame, no verdict: the take itself is fine
        rank = {"pass": 2, "drift": 1}
        best = max(reports, key=lambda r: (rank.get(r["status"], 0), r.get("score") or -1))
        best["frames_checked"] = len(reports)
        ctx.identity[stage] = best
        self.bus.publish(ctx.take_id, {"type": "identity", "stage": stage, "report": best})

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
        edits = [a for a in plan.anchors if a.role in {"edit", "transform"}]
        roles = {a.index: a.role for a in plan.anchors}
        if plan.angle:
            roles[0] = "angle"  # the first still shown for approval is the hero re-shot from the angle
        ctx = _Ctx(take_id, "direct", total_stages=1 + (1 if plan.angle else 0) + len(edits) + len(plan.segments) + 1,
                   refs=list(req.cast_refs), identity_retry=req.identity_retry, backend=backend)
        # a transformation that changes the face on purpose (a gold statue, forty years) is not checked for identity
        face_changes = bool(plan.transformation) and not TRANSFORMATIONS[plan.transformation].keeps_identity
        stage_of = lambda a: f"{'transform' if a.role == 'transform' else 'anchor'}_{a.index}"  # noqa: E731
        tier = quality.check(req.quality)
        vw, vh = quality.video_size(tier, req.orientation)
        sw, sh = quality.still_size(tier, req.orientation)
        still_steps = quality.steps(tier)
        rw, rh = vw, vh  # the size LTX renders at
        frame = (vw // 32 * 32, vh // 32 * 32)  # the frame LTX makes at this tier (its sizes are multiples of 32)
        if plan.roll:  # shot larger, then turned and cropped back to that frame (ROLLS): sharp, nothing upscaled
            rw, rh = video.roll_render_size(frame, plan.roll, cap=quality.video_size("fine", req.orientation), multiple=64)
            sw, sh = video.roll_render_size((sw, sh), plan.roll, cap=quality.still_size("fine", req.orientation))
        elif plan.reframe:  # a window moves over the picture as it plays: render at the largest size the template allows
            rw, rh = quality.video_size("fine", req.orientation)
        made_after = bool(plan.roll or plan.mirror or plan.reframe or plan.reverse)  # the delivered frame is made after the render
        hero_prompt = compile_still_prompt(rig, req.subject, one_still=plan.mode != "keyframed", action=req.action)
        if req.cast_refs:
            hero_prompt += " Keep the person's face and identity exactly as in the reference images."

        async def make_hero(seed_value: int) -> Path:
            if req.cast_refs:
                values = {"prompt": hero_prompt, "seed": seed_value, "base_image": req.cast_refs[0],
                          "refs": req.cast_refs[1:9], "custom_size": True, "width": sw, "height": sh, "steps": still_steps}
                return await self._still(ctx, "hero", "qwen21_edit", values)
            values = {"prompt": hero_prompt, "seed": seed_value, "width": sw, "height": sh, "steps": still_steps}
            return await self._still(ctx, "hero", "qwen21_t2i", values, check=False)

        async def make_anchor(a: AnchorSpec, seed_value: int, hero: Path) -> Path:
            # The hero still already carries the cast's identity. Handing the edit the reference portraits as
            # well made Qwen compose a second person on the first real render, so an anchor is edited from
            # the hero alone, with the prompt holding the subject count. A transformation's end state keeps the
            # framing but is allowed to change the scene (or the face), so its keep-sentence says so.
            if a.role == "transform" and getattr(TRANSFORMATIONS.get(plan.transformation or ""), "reframes", False):
                # the end state widens the view (the set revealed around the scene): the subject and set stay, the framing may not
                keep = "Keep the same subject, pose and set at the centre; the view may widen, and add only what the instruction says."
                if a.check_identity:
                    keep += " The person's face and identity stay exactly the same."
            elif a.role == "transform":  # the end state may change the scene, and the face only when the effect is about the face
                keep = "Keep the same framing, pose and setting; change only what the instruction says, and add no one and nothing else."
                if a.check_identity:
                    keep += " The person's face and identity stay exactly the same."
            elif plan.rig.movement in ("arc_left", "arc_right") and a.edit_prompt:
                # the arc's end still: the same place seen from 45 degrees round, so "the same setting" must not pin the view
                keep = "Keep the same person, clothes, light and place, the place now seen from the new angle; add no one and nothing else."
            else:
                keep = "Keep exactly the same subject and setting as in the picture; add no one and nothing else."
            prompt = f"{(a.edit_prompt or '').strip().rstrip('.。')}. {keep}"
            values: dict[str, Any] = {"prompt": prompt, "seed": seed_value, "base_image": hero, "steps": still_steps}
            stage = stage_of(a)
            # a widened view puts a crew around the person: a second face is expected there, and the largest face may be
            # a crew member's, so that still is not checked (or re-rolled); the shot is, from its first, middle and last frames
            reframed = a.role == "transform" and getattr(TRANSFORMATIONS.get(plan.transformation or ""), "reframes", False)
            if not a.check_identity:
                ctx.skipped[stage] = TRANSFORMATIONS[plan.transformation].skip_reason
            elif reframed:
                ctx.skipped[stage] = ("the view widens to reveal a crew around the person, so the face check cannot tell "
                                      "them apart on this still; the shot is still checked")
            return await self._still(ctx, stage, "qwen21_edit", values, check=a.check_identity and not reframed)

        async def make_angle(source: Path, seed_value: int) -> Path:
            # the hero re-shot from the chosen angle becomes the shot's first still; it is checked like an anchor
            # (against the cast, or the photo), and re-rolled once the same way
            values: dict[str, Any] = {"prompt": plan.angle["directive"], "seed": seed_value, "base_image": source, "steps": still_steps}
            return await self._still(ctx, "angle", "qwen21_edit", values)

        self._stage(ctx, "hero")
        source_info: dict[str, Any] | None = None
        if req.source is not None:
            # the person's own still is the hero: fitted to the still size so the anchors edited from it and the
            # LTX frames share one aspect; nothing was rendered for it, so it lives in inputs/, not runs/
            hero_png = self.ledger.take_dir(take_id) / "inputs" / "hero.png"
            hero_png.parent.mkdir(parents=True, exist_ok=True)
            source_info = await asyncio.to_thread(_fit_source, req.source, hero_png, (sw, sh))
            source_info["identity_reference"] = "cast" if req.cast_refs else "photo"
            anchors: dict[int, Path] = {0: hero_png}
            if req.cast_refs:
                await self._identity(ctx, "hero", hero_png)  # is the photo that character? reported, never re-rolled
            else:
                ctx.refs = [hero_png]  # the anchors and the shot are checked as "the same person as your photo"
        else:
            anchors = {0: await make_hero(seed)}
        self._stage(ctx, "hero", "done")
        source_still = anchors[0]  # the hero as shot (or the photo): what an angle re-shoots, and what a re-roll starts from
        if plan.angle:
            self._stage(ctx, "angle")
            anchors[0] = await make_angle(source_still, seed + 500)
            self._stage(ctx, "angle", "done")
        for a in plan.anchors:
            if a.role in {"edit", "transform"}:
                self._stage(ctx, stage_of(a))
                anchors[a.index] = await make_anchor(a, seed + a.index, anchors[0])
                self._stage(ctx, stage_of(a), "done")
            elif a.role == "repeat_hero":
                anchors[a.index] = anchors[0]
        if not req.auto_approve:  # the stills are the cheap part: look before paying for the video
            attempt = 0
            while True:
                attempt += 1
                reroll = await self._await_approval(take_id, ctx, anchors, roles)
                if not reroll:
                    break
                if 0 in reroll:
                    if plan.angle:  # the first still is the angled one: re-shot from the hero, never the hero itself
                        anchors[0] = await make_angle(source_still, seed + 500 + 1000 * attempt)
                    elif req.source is None:  # a sourced hero is the photo itself: approve() refuses 0
                        anchors[0] = await make_hero(seed + 1000 * attempt)
                for a in edits:
                    if a.index in reroll or 0 in reroll:
                        anchors[a.index] = await make_anchor(a, seed + a.index + 1000 * attempt, anchors[0])
                for a in plan.anchors:
                    if a.role == "repeat_hero":
                        anchors[a.index] = anchors[0]

        clips: list[Path] = []
        # a mirrored move renders its twin on the flipped stills (MIRRORS); the stills shown and kept stay as made
        frames_in = {i: self._mirrored(p) for i, p in anchors.items()} if plan.mirror else anchors
        for seg in plan.segments:
            self._stage(ctx, f"shoot_{seg.index + 1}")
            values = {"prompt": plan.prompt, "seed": seed + 31 * seg.index, "duration": seg.seconds,
                      "width": rw, "height": rh, "first_frame": frames_in[seg.start_anchor]}
            if seg.end_anchor is not None:
                values["last_frame"] = frames_in[seg.end_anchor]
            if seg.mids:  # one pass: the middle stills are guided inside the shot at their frames
                values["mids"] = [
                    {"image": frames_in[a], "frame_idx": frame,
                     **({"strength": rig_module.MID_GUIDE_STRENGTH} if rig_module.MID_GUIDE_STRENGTH is not None else {})}
                    for a, frame in seg.mids
                ]
            result, _ = await self._run(ctx, f"shoot_{seg.index + 1}", seg.template, values)
            clip = result.files["video"].path
            clips.append(clip)
            if face_changes:
                ctx.skipped[f"shoot_{seg.index + 1}"] = TRANSFORMATIONS[plan.transformation].skip_reason
            elif not made_after:  # a turned, flipped or zoomed shot is checked on the frame delivered (below)
                await self._check_shot(ctx, f"shoot_{seg.index + 1}", clip)
            self._stage(ctx, f"shoot_{seg.index + 1}", "done")

        self._stage(ctx, "finish")
        take_dir = self.ledger.take_dir(take_id)
        final = take_dir / "take.mp4"
        if len(clips) == 1:
            shutil.copyfile(clips[0], final)
        else:
            await asyncio.to_thread(video.concat, clips, final, crossfade_s=0.0, lufs=-14.0)
        reversal: dict[str, Any] = {}
        rolled: dict[str, Any] = {}
        mirrored: dict[str, Any] = {}
        reframed: dict[str, Any] = {}
        if plan.reverse:  # the reverse rendered (REVERSES), played backwards first, so what follows runs in delivered time
            reversal = dict(await asyncio.to_thread(video.reverse, final, final), rendered_as=plan.reverse)
        if plan.roll:  # the level render (kept in runs/) turned in code and cropped to the tier's frame
            rolled = await asyncio.to_thread(video.roll, final, final, plan.roll, frame)
        if plan.mirror:  # the twin rendered on the flipped stills, flipped back: the camera goes the other way
            mirrored = dict(await asyncio.to_thread(video.mirror, final, final), rendered_as=plan.mirror)
        if plan.reframe:  # the window moved over the render (REFRAMES), scaled to the tier's frame
            path, tracking = None, {}
            if plan.reframe.get("track") == "face":  # TRACKED: the zoom holds the face at its first size
                path, tracking = await self._face_path(final)
            reframed = await asyncio.to_thread(video.reframe, final, final, frame, zoom=tuple(plan.reframe["zoom"]),
                                               height=tuple(plan.reframe["height"]), how=plan.reframe["how"], path=path)
            reframed.update(tracking)
        if made_after and not face_changes:
            await self._check_shot(ctx, "shoot_1", final)  # the face is checked on the frame that is delivered
        stills = {i: p for i, p in anchors.items()}
        await self._seal_and_finish(ctx, final, recipe_inputs={
            "subject": req.subject.strip(), "rig": asdict(rig), "move": plan.move_id,
            "mode": plan.mode, "final_prompt": plan.prompt,
            "seed": seed, "orientation": req.orientation, "audio": req.audio, "quality": tier,
            # how the video was made: one entry per LTX render, with the stills guided inside a single pass
            "segments": [{"index": s.index, "template": s.template, "seconds": s.seconds, "first": s.start_anchor,
                          "last": s.end_anchor,
                          "guides": [{"anchor": a, "frame_idx": f,
                                      **({"strength": rig_module.MID_GUIDE_STRENGTH} if rig_module.MID_GUIDE_STRENGTH is not None else {})}
                                     for a, f in s.mids]}
                         for s in plan.segments],
            **({"transformation": plan.transformation} if plan.transformation else {}),
            **({"dialogue": plan.dialogue} if plan.dialogue else {}),
            **({"action": plan.action} if plan.action else {}),
            **({"angle": dict(plan.angle, source_file=str(source_still.relative_to(take_dir)).replace("\\", "/"))}
               if plan.angle else {}),
            **({"reversed": reversal} if reversal else {}),
            **({"roll": rolled} if rolled else {}),
            **({"mirror": mirrored} if mirrored else {}),
            **({"reframe": reframed} if reframed else {}),
            "anchors": [{"index": i, "file": str(p.relative_to(take_dir)).replace("\\", "/")}
                        for i, p in sorted(stills.items())],
            "cast": {"name": req.cast_name, "refs": [file_sha256(p) for p in req.cast_refs]},
            **({"source": source_info} if source_info else {}),
        }, notes=list(plan.notes) + (["The hero still is the person's own image; nothing was rendered for it."]
                                      if source_info else [])
           + ([f"The turn keeps the centre {round(100 * rolled['crop'][0] / rolled['rendered'][0])}% of the width of "
               "your photo's frame: anything near its edges is cropped."] if source_info and rolled else [])
           + ([f"{reframed['reason'][0].upper()}{reframed['reason'][1:]}."] if reframed.get("reason") else []))

    async def _face_path(self, clip: Path) -> tuple[list[tuple[float, float, float, float]] | None, dict[str, Any]]:
        """The window path that holds the face at its first size in a render (video.face_zoom_path), and what the
        receipt says about it. The path is None, with the reason, when no face detector is set up, the frames cannot
        be read or too few of them show a face: the move's fixed curve is used then."""
        made: dict[str, Any] = {"track": "face", "tracked": False}
        gate = self._gate()
        detect = getattr(gate, "faces", None)
        if detect is None or getattr(gate, "available", True) is False:
            made["reason"] = "no face detector was available, so the zoom followed the fixed curve"
            return None, made
        try:
            info = await asyncio.to_thread(video.probe, clip)
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch:
                frames = await asyncio.to_thread(video.sample_frames, clip, Path(scratch), FACE_TRACK_FPS)
                boxes = await asyncio.to_thread(lambda: [_largest_face(detect(image)) for _, image in frames])
        except video.VideoError:
            log.warning("could not sample %s for the face", clip.name, exc_info=True)
            made["reason"] = "the render's frames could not be read, so the zoom followed the fixed curve"
            return None, made
        samples = [(t, box) for (t, _), box in zip(frames, boxes, strict=True)]
        found = [box for _, box in samples if box]
        made.update(found=len(found), samples=len(samples))
        if found:
            made["face_height_px"] = [found[0][3], found[-1][3]]  # as detected, at the first and last frame that has one
        path = video.face_zoom_path(samples, (info.width, info.height))
        if path is None:
            made["reason"] = (f"a face was found in {len(found)} of {len(samples)} frames, too few to follow, so the zoom "
                              "followed the fixed curve")
            return None, made
        made["tracked"] = True
        made["path"] = [[t, z] for t, z, _, _ in path]  # the zoom at each keyframe, so a take that did not hold can be read
        return path, made

    @staticmethod
    def _mirrored(still: Path) -> Path:
        """The still flipped left to right, beside it (made once): what a mirrored move hands LTX."""
        out = still.with_name(f"{still.stem}_mirrored{still.suffix}")
        if not out.exists():
            with Image.open(still) as image:
                ImageOps.mirror(image).save(out)
        return out

    async def _await_approval(self, take_id: str, ctx: _Ctx, anchors: dict[int, Path],
                              roles: dict[int, str] | None = None) -> list[int]:
        take_dir = self.ledger.take_dir(take_id)
        roles = roles or {}
        shown = [{"index": i, "file": str(p.relative_to(take_dir)).replace("\\", "/"),
                  "role": roles.get(i, "hero" if i == 0 else "edit")}
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
        ctx = _Ctx(take_id, "reshoot", total_stages=4 if req.face_only else 3, backend=backend)
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
        if req.face_only:
            # keep the clip's look and swap only the face: the first frame gets the Cast's face (one Qwen edit), and that
            # frame is the reference Wan Animate re-performs the clip from, so the clothes and the set stay
            self._stage(ctx, "face")
            first = inputs / "source_first.png"
            await asyncio.to_thread(video.extract_frame, source, first, "first")
            ctx.refs = list(req.face_refs)
            reference = await self._still(ctx, "face", "qwen21_edit", {
                "prompt": FACE_SWAP, "seed": seed, "base_image": first, "refs": list(req.face_refs)[:9],
                "steps": quality.steps(quality.DEFAULT)})
            self._stage(ctx, "face", "done")
        self._stage(ctx, "motion")
        # the template works at a fixed portrait size and centre-crops; give a landscape clip a landscape frame
        orientation = "landscape" if info.width > info.height * 1.15 else "portrait"
        width, height = RESHOOT_SIZES[orientation]
        background = req.background
        if req.face_only and not (background or "").strip():  # the swapped first frame already holds the clip's own set
            background = "the same setting as in the reference image, unchanged"
        caption = compile_reshoot_prompt(req.prompt, background)
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
            **({"face_only": {"refs": [file_sha256(p) for p in req.face_refs],
                              "reference": str(reference.relative_to(take_dir)).replace("\\", "/")}} if req.face_only else {}),
        }, notes=list(req.notes) + (["Face only: the clip's first frame got the Cast's face (one Qwen-Image 2.1 edit) and "
                                     "Wan Animate 2 re-performed the clip from that frame."] if req.face_only else []))

    # -- Edit with words ---------------------------------------------------------------------------
    async def _run_edit(self, take_id: str, req: EditRequest, prompt: str, still: Path, seed: int,
                        backend: Backend) -> None:
        swap = EDITS[req.preset].needs_cast
        ctx = _Ctx(take_id, "edit", total_stages=3, refs=list(req.cast_refs), backend=backend)
        take_dir = self.ledger.take_dir(take_id)
        inputs = take_dir / "inputs"
        inputs.mkdir(exist_ok=True)
        self._stage(ctx, "source")
        source = inputs / "source.png"
        await asyncio.to_thread(_normalise_image, still, source)  # the edit keeps the picture's own shape: no crop
        if not swap:
            ctx.refs = [source]  # a remove, an outfit or a light keeps the person: checked against the picture itself
        self._stage(ctx, "source", "done")
        self._stage(ctx, "edit")
        values: dict[str, Any] = {"prompt": prompt, "seed": seed, "base_image": source, "steps": quality.steps(quality.DEFAULT)}
        if swap:
            values["refs"] = list(req.cast_refs)[:9]
        after = await self._still(ctx, "edit", "qwen21_edit", values)
        self._stage(ctx, "edit", "done")
        self._stage(ctx, "finish")
        with Image.open(after) as img:
            size = (img.width // 2 * 2, img.height // 2 * 2)
        final = take_dir / "take.mp4"  # before, then after: the take plays the change (no video model runs)
        await asyncio.to_thread(video.stills_clip, [source, after], final, size=size, seconds_each=1.2)
        rel = str(after.relative_to(take_dir)).replace("\\", "/")
        self.ledger.update(take_id, edit={"preset": req.preset, "before": "inputs/source.png", "after": rel})
        await self._seal_and_finish(ctx, final, recipe_inputs={
            "preset": req.preset, "detail": recipe_detail(req.detail), "final_prompt": prompt, "seed": seed,
            "before": "inputs/source.png", "after": rel,
            "cast": {"name": req.cast_name, "refs": [file_sha256(p) for p in req.cast_refs]},
            "identity_reference": "cast" if swap else "picture",
        }, notes=["One Qwen-Image 2.1 edit of one still. The take plays the still before and after, 1.2 s each: no "
                  "video model ran."])

    # -- Shots: one still, nine setups ------------------------------------------------------------
    async def _run_shots(self, take_id: str, req: ShotsRequest, still: Path, seed: int, tier: str,
                         backend: Backend) -> None:
        board = list(SHOTS_BOARD)
        ctx = _Ctx(take_id, "shots", total_stages=len(board) + 2, refs=list(req.cast_refs), backend=backend)
        take_dir = self.ledger.take_dir(take_id)
        inputs = take_dir / "inputs"
        inputs.mkdir(exist_ok=True)
        self._stage(ctx, "source")
        with Image.open(still) as img:
            upright = ImageOps.exif_transpose(img)
            orientation = "portrait" if upright.height > upright.width * 1.15 else "landscape"
        size = quality.still_size(tier, orientation)
        source = inputs / "source.png"
        source_info = await asyncio.to_thread(_fit_source, still, source, size)
        if not req.cast_refs:
            ctx.refs = [source]  # every setup is checked as the same person as the image
        self._stage(ctx, "source", "done")
        steps = quality.steps(tier)
        shots: list[dict[str, Any]] = []
        for index, (angle, label) in enumerate(board, start=1):
            stage = f"shot_{index}"
            self._stage(ctx, stage)
            image = await self._still(ctx, stage, "qwen21_edit", {
                "prompt": angle_directive(angle), "seed": seed + index, "base_image": source, "steps": steps})
            report = ctx.identity.get(stage) or {}
            shots.append({"index": index, "angle": angle, "label": label,
                          "file": str(image.relative_to(take_dir)).replace("\\", "/"),
                          "identity": {k: report.get(k) for k in ("status", "score")} if report else None})
            self.ledger.update(take_id, shots=list(shots))  # the board fills in as it renders: the stage snapshot carries it
            self._stage(ctx, stage, "done")
        self._stage(ctx, "finish")
        await asyncio.to_thread(_contact_sheet, [take_dir / s["file"] for s in shots], take_dir / "board.jpg")
        final = take_dir / "take.mp4"
        await asyncio.to_thread(video.stills_clip, [take_dir / s["file"] for s in shots], final,
                                size=size, seconds_each=SHOTS_SECONDS_EACH)
        self.ledger.update(take_id, shots=shots, board="board.jpg")
        await self._seal_and_finish(ctx, final, recipe_inputs={
            "seed": seed, "quality": tier, "orientation": orientation, "source": source_info,
            "cast": {"name": req.cast_name, "refs": [file_sha256(p) for p in req.cast_refs]},
            "identity_reference": "cast" if req.cast_refs else "image",
            "shots": [{k: s[k] for k in ("index", "angle", "label", "file")} | {"directive": angle_directive(s["angle"])}
                      for s in shots],
            "board": "board.jpg",
        }, notes=["Nine Qwen-Image 2.1 edits of one still, one per camera position; "
                  + (f"each was checked against {'the cast' if req.cast_refs else 'the image'}."
                     if any(r.get("status") in {"pass", "drift"} for r in ctx.identity.values())
                     else "the face check was not available here, so none was checked.")
                  + f" The take plays the nine stills in order, {SHOTS_SECONDS_EACH} s each: no video model ran."])

    # -- Transition between two takes -------------------------------------------------------------
    async def _run_transition(self, take_id: str, req: TransitionRequest, prompt: str, first_dir: Path,
                              second_dir: Path, seed: int, backend: Backend) -> None:
        ctx = _Ctx(take_id, "transition", total_stages=3, backend=backend)
        take_dir = self.ledger.take_dir(take_id)
        inputs = take_dir / "inputs"
        inputs.mkdir(exist_ok=True)
        self._stage(ctx, "prepare")
        first_video, second_video = first_dir / "take.mp4", second_dir / "take.mp4"
        leave, land = inputs / "first_last_frame.png", inputs / "second_first_frame.png"
        await asyncio.to_thread(video.extract_frame, first_video, leave, "last")
        await asyncio.to_thread(video.extract_frame, second_video, land, "first")
        # the bridge keeps the first take's shape, so the join letterboxes nothing (and its size is the take's own
        # whenever that fits the template)
        info = await asyncio.to_thread(video.probe, first_video)
        width, height = bridge_size(info.width, info.height)
        for frame in (leave, land):  # a take of another shape lands letterboxed, never squashed (the join pads it alike)
            await asyncio.to_thread(_letterbox, frame, (width, height))
        self._stage(ctx, "prepare", "done")
        self._stage(ctx, "bridge")
        values = {"prompt": prompt, "seed": seed, "duration": req.seconds, "width": width, "height": height,
                  "first_frame": leave, "last_frame": land}
        result, _ = await self._run(ctx, "bridge", "ltx25_flf2v", values)
        bridge = result.files["video"].path
        ctx.skipped["bridge"] = "a transition joins two finished takes; each keeps its own identity result"
        self._stage(ctx, "bridge", "done")
        self._stage(ctx, "finish")
        final = take_dir / "take.mp4"
        await asyncio.to_thread(video.concat, [first_video, bridge, second_video], final,
                                crossfade_s=TRANSITION_JOIN_FADE, lufs=-14.0)
        idea = transition_idea(req.idea)
        await self._seal_and_finish(ctx, final, recipe_inputs={
            "style": req.style, "seconds": req.seconds, "seed": seed, "final_prompt": prompt, "frame": [width, height],
            **({"idea": idea} if idea else {}),
            "first": {"take": req.first, "sha256": file_sha256(first_video), "frame": "inputs/first_last_frame.png"},
            "second": {"take": req.second, "sha256": file_sha256(second_video), "frame": "inputs/second_first_frame.png"},
            "join": {"order": ["first", "bridge", "second"], "crossfade_s": TRANSITION_JOIN_FADE},
        }, notes=["The bridge is one LTX 2.5 render from the first take's last frame to the second take's first frame; "
                  "the take plays the first take, the bridge and the second take, joined."])

    # -- Extend a finished take ------------------------------------------------------------------
    async def _run_extend(self, take_id: str, req: ExtendRequest, prompt: str, source_dir: Path,
                          seed: int, backend: Backend) -> None:
        ctx = _Ctx(take_id, "extend", total_stages=3, backend=backend)
        take_dir = self.ledger.take_dir(take_id)
        inputs = take_dir / "inputs"
        inputs.mkdir(exist_ok=True)
        self._stage(ctx, "prepare")
        source_video = source_dir / "take.mp4"
        last_frame = inputs / "last_frame.png"
        await asyncio.to_thread(video.extract_frame, source_video, last_frame, "last")
        # the extension keeps the original take's shape, so the join letterboxes nothing
        info = await asyncio.to_thread(video.probe, source_video)
        width, height = bridge_size(info.width, info.height)
        self._stage(ctx, "prepare", "done")
        self._stage(ctx, "extend")
        values = {"prompt": prompt, "seed": seed, "duration": req.seconds, "width": width, "height": height,
                  "first_frame": last_frame}
        result, _ = await self._run(ctx, "extend", "ltx25_i2v", values)
        extension = result.files["video"].path
        ctx.skipped["extend"] = "an extension continues a finished take; that take keeps its own identity result"
        self._stage(ctx, "extend", "done")
        self._stage(ctx, "finish")
        final = take_dir / "take.mp4"
        await asyncio.to_thread(video.concat, [source_video, extension], final,
                                crossfade_s=TRANSITION_JOIN_FADE, lufs=-14.0)
        await self._seal_and_finish(ctx, final, recipe_inputs={
            "take": {"id": req.take, "sha256": file_sha256(source_video), "frame": "inputs/last_frame.png"},
            "seconds": req.seconds, "seed": seed, "final_prompt": prompt, "frame": [width, height],
        }, notes=[f"The extension is one LTX 2.5 image-to-video render from the take's last frame, "
                  f"adding {req.seconds} seconds; the take plays the original take then the extension, joined."])

    # -- Upscale: one Real-ESRGAN pass over a finished take --------------------------------------------------------
    async def _run_upscale(self, take_id: str, req: UpscaleRequest, source_dir: Path, size: tuple[int, int],
                           method: str, backend: Backend) -> None:
        ctx = _Ctx(take_id, "upscale", total_stages=2, backend=backend)
        take_dir = self.ledger.take_dir(take_id)
        source = source_dir / "take.mp4"
        digest = await asyncio.to_thread(file_sha256, source)
        self._stage(ctx, "upscale")
        values = {"video": source, "width": size[0], "height": size[1], "upscale_method": method}
        result, _ = await self._run(ctx, "upscale", "esrgan_upscale", values)
        ctx.skipped["upscale"] = ("an upscale has no cast or photo to check against; the take it enlarges keeps its own "
                                  "identity result")
        self._stage(ctx, "upscale", "done")
        self._stage(ctx, "finish")
        final = take_dir / "take.mp4"
        shutil.copyfile(result.files["video"].path, final)
        await self._seal_and_finish(ctx, final, recipe_inputs={
            "take": {"id": req.take, "sha256": digest}, "target": req.target, "size": list(size),
        }, notes=[f"Upscaled with Real-ESRGAN x4plus (open weights), the model of ComfyUI's own Video Upscale graph, then "
                  f"resized to {size[0]}x{size[1]}. Each frame is enlarged on its own: the model redraws fine detail from "
                  "that frame's pixels as a GAN upscaler does, and nothing beyond that is invented. The motion and the "
                  "sound are the take's own."])

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
                      "refs_used": len(ctx.refs), "reports": ctx.identity,
                      **({"skipped": dict(ctx.skipped)} if ctx.skipped else {})},
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
            anchors=recorded.get("anchors", []),
            **({"shots": recorded["shots"], "board": recorded.get("board")} if recorded.get("shots") else {}),
            **({"edit": recorded["edit"]} if recorded.get("edit") else {}))
        self.bus.publish(take_id, {"type": "take", "take": updated})
        self.bus.publish(take_id, {"type": "end", "status": "succeeded"})


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _copy_recorded(source: Path, target: Path) -> None:
    """Copy what the UI shows (final media, receipt, stills, inputs) and the graphs that ran; skip
    the heavy per-segment video."""
    for name in ("take.mp4", "poster.png", "receipt.json", "take.mp4.receipt.json", "board.jpg"):
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


def _render_seconds(take_dir: Path) -> float | None:
    """The sum of a take's model runs (`runs/*/run.json` timings), or None when it has no measured run."""
    total, found = 0.0, False
    for run_json in take_dir.glob("runs/*/run.json"):
        try:
            seconds = (json.loads(run_json.read_text(encoding="utf-8")).get("timings") or {}).get("total_s")
        except (OSError, ValueError):
            continue
        if isinstance(seconds, (int, float)):
            total += float(seconds)
            found = True
    return total if found else None


def _delete(paths: tuple[Path, ...] | list[Path]) -> None:
    for path in paths:
        with contextlib.suppress(OSError):
            Path(path).unlink(missing_ok=True)


def _largest_face(faces: list[Any]) -> tuple[int, ...] | None:
    """The box (x, y, w, h) of the first face a detector lists (FaceGate.faces lists the largest first), or None."""
    return tuple(int(v) for v in faces[0].box) if faces else None


def _embed_in_png(image: Path, sealed: dict[str, Any]) -> None:
    """Write the sealed receipt into a PNG in place (through a temporary file)."""
    temporary = image.with_name(image.stem + ".embedded.png")
    receipts.embed_png(image, temporary, sealed)
    replace_file(temporary, image)


def _fit_source(src: Path, dest: Path, size: tuple[int, int]) -> dict[str, Any]:
    """The person's still as a hero: upright, RGB, centre-cropped to the still's aspect and scaled to its size.

    Returns what the receipt records about it: the upload's hash, its original size, the crop taken and the size kept.
    """
    digest = file_sha256(src)
    target_w, target_h = size
    try:
        with Image.open(src) as img:
            if img.width * img.height > 48_000_000:  # a tiny file can claim a gigantic canvas
                raise ValueError(f"{Path(src).name} has far too many pixels")
            img = ImageOps.exif_transpose(img).convert("RGB")
            original = [img.width, img.height]
            scale = max(target_w / img.width, target_h / img.height)
            crop_w, crop_h = round(target_w / scale), round(target_h / scale)
            left, top = (img.width - crop_w) // 2, (img.height - crop_h) // 2
            fitted = img.crop((left, top, left + crop_w, top + crop_h)).resize((target_w, target_h), Image.LANCZOS)
            fitted.save(dest, "PNG")
    except Image.DecompressionBombError:
        raise ValueError(f"{Path(src).name} has far too many pixels") from None
    except (OSError, SyntaxError) as exc:
        raise ValueError(f"{Path(src).name} is not an image that can be read: {exc}") from None
    return {"sha256": digest, "original_size": original, "crop": [left, top, crop_w, crop_h], "size": [target_w, target_h]}


def _letterbox(path: Path, size: tuple[int, int]) -> None:
    """Fit an image inside `size` keeping its aspect, padded with black, in place (a frame for a bridge of another shape)."""
    with Image.open(path) as img:
        img = img.convert("RGB")
        if (img.width, img.height) == size:
            return
        scale = min(size[0] / img.width, size[1] / img.height)
        fitted = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    canvas = Image.new("RGB", size, (0, 0, 0))
    canvas.paste(fitted, ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2))
    canvas.save(path, "PNG")


def _contact_sheet(images: list[Path], dest: Path, columns: int = 3, tile_width: int = 448) -> None:
    """The board as one JPEG: the stills in reading order on a dark ground, no text (the interface labels them)."""
    tiles = []
    for path in images:
        with Image.open(path) as img:
            img = img.convert("RGB")
            height = round(img.height * tile_width / img.width)
            tiles.append(img.resize((tile_width, height), Image.LANCZOS))
    gap = 8
    tile_h = max(t.height for t in tiles)
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_width + (columns + 1) * gap, rows * tile_h + (rows + 1) * gap), (13, 12, 11))
    for i, tile in enumerate(tiles):
        x = gap + (i % columns) * (tile_width + gap)
        y = gap + (i // columns) * (tile_h + gap)
        sheet.paste(tile, (x, y))
    sheet.save(dest, "JPEG", quality=86)


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
