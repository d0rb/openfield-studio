"""OpenField Studio over MCP: Claude (or any MCP client) directs takes, approves stills, edits and cuts movies.

`openfield mcp` speaks the Model Context Protocol on stdin/stdout (JSON-RPC 2.0, one message per line) and drives a
running studio through its HTTP API (`openfield serve`, or `openfield demo` for Replay). Nothing new is installed:
httpx and Pillow are already dependencies. Every render goes through the same pipeline, approval gate, open-weights
audit and receipts as the app, and Replay still refuses a recipe that was never rendered.

The tools show the model what it is working with: the stills waiting for approval come back as images, and a finished
take comes back as a six-frame strip, so the model can check that the action happened before it builds on the take.
"""

from __future__ import annotations

import base64
import io
import json
import re
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from PIL import Image

from . import __version__
from .engine import rig as rigs
from .engine import video

SERVER_NAME = "openfield-studio"
DEFAULT_URL = "http://127.0.0.1:8877"
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")  # newest first
TERMINAL = frozenset({"succeeded", "failed", "canceled", "cancelled"})  # the ledger writes "canceled"
WAIT_DEFAULT_S, WAIT_MAX_S = 50, 110  # a client may time a call out; a long render is waited for in rounds
STILL_PX, STRIP_FRAME_PX = 448, 256
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
VIDEO_SUFFIXES = (".mp4", ".mov", ".webm", ".mkv")
TAKE_PATTERN = r"^tk_\d{8}_\d{6}_[0-9a-f]{4}$"
CAST_PATTERN = r"^ca_[0-9a-f]{8}$"
FILE_PATTERN = r"^(?!.*\.\.)[A-Za-z0-9_][A-Za-z0-9_.-]*(/[A-Za-z0-9_][A-Za-z0-9_.-]*)*$"  # a path inside a take
MAX_IMAGE_MB, MAX_PHOTO_MB, MAX_VIDEO_MB = 20, 12, 200  # the studio's own upload limits


def seg(part: str) -> str:
    """One URL path segment, quoted: an id never becomes a different route."""
    return quote(part, safe="")


def file_url(path: str) -> str:
    """A file inside a take, every segment quoted."""
    return "/".join(seg(x) for x in path.split("/"))

INSTRUCTIONS = """OpenField Studio renders real video takes with open-weights models through ComfyUI: Qwen-Image 2.1 paints \
the stills, LTX 2.5 turns them into video with synced sound and speech in one pass, Wan Animate 2 re-shoots a filmed clip \
with a new character. Every take is a recipe plus a checksummed receipt.

How to work with it:
1. Call studio_status first. On Replay the studio renders nothing: it plays recorded takes (replay_take) and refuses a \
recipe that was never rendered. On a live GPU box every render spends the owner's money: plan first, explore at quality "draft". This \
server also enforces a hard render budget per session (studio_status shows what is left); it is a limit, not advice.
2. list_options shows the moves, effects, transitions and edits, each marked reliable when it held on a real render \
here. Prefer reliable ones. plan_shot shows the exact prompts the models will receive, for free.
3. Write a shot like a director (call read_guide before the first shot): `subject` is what \
the first frame shows (who, wearing what, where, light, framing); `action` is what visibly happens, in present tense with \
the end state named ("he draws the katana fully out of its scabbard and raises it overhead", not "grips his katana"); \
the camera move is the `move` field, never words in the subject.
4. Stills first: direct_shot renders the stills first and waits at awaiting_approval. wait_for_take shows them to you: check \
one subject, the framing, natural eyes and hands, the face of the Cast. Then approve_stills, re-rolling bad ones by index.
5. Check every finished take before you use it: wait_for_take returns a six-frame strip. Did the action happen? Did the \
camera do the move? Did anything appear, vanish or morph? If not, render again with a new seed or a sharper action. \
Never re-submit a render because a wait timed out: the take is still running; call wait_for_take again.
6. Faces come only from the Cast, where consent is recorded: create_character makes a fictional one, add_character keeps it.
7. A movie: 2-8 finished takes, bridged with transition (push is the most reliable style) and joined by make_movie, which \
crossfades and matches loudness. Give the person the page link of every take you make."""

GUIDE = """# Writing shots for OpenField Studio

The models: **Qwen-Image 2.1** paints the stills (the first frame, and the anchor stills of a keyframed move); \
**LTX 2.5** renders the video between them with sound and speech in the same pass; **Wan Animate 2** re-shoots a filmed \
clip with a new character. LTX 2.5 runs distilled at CFG 1, so there is no negative prompt: say what you want, not what \
you do not want.

## subject: the first frame (the last, on a move played backwards)
- Describe what the camera sees when the shot starts: who (age, build, hair, wardrobe), where, the light and time of \
day, the mood. One clear subject. 20-60 words in plain sentences.
- Through object and pedestal down are rendered as their reverse and played backwards (list_options marks them \
`reversed`): there the still is where the shot ends, so describe that end state, and give them no action, line or effect.
- Put the framing in the subject itself when it matters. "A tiny distant figure in the middle of a vast wheat field" \
gives a wide shot; "her face fills the frame" gives a close-up. A framing word elsewhere loses to the subject text.
- With a Cast character keep the face large: a medium-wide shot or closer (a face under about 100 pixels drifts from \
the reference). Let the camera move carry the push or pull.
- No camera directions in the subject (the `move` field does that) and no "cinematic, 8k, masterpiece" filler; the \
studio adds the camera body, lens, aperture and lighting from the look fields.

## action: what happens during the shot
- Present tense, concrete visible verbs, in the order they happen, with the end state named: "she lifts the lid, steam \
rises, and she smiles at the camera" or "he draws the katana fully out of its scabbard and raises it overhead". A hand \
that grips a sword is not a draw: name the motion all the way to its end.
- One main beat per 5 seconds, two at most. Physical, readable motion beats vague emotion.
- Action needs a one-still move (mode `prompt_only` in list_options: static, the crash zooms, handheld, pans, \
trucks...) or `quick: true`. A keyframed move (mode `keyframed`: dolly in and out, the arcs, the half and full orbits, crane up...) \
pins its first and last stills to the same moment, so the subject can barely move.

## move, speed and seconds
- Pick a move id from list_options; reliable moves held on real renders here. Keyframed moves render several stills that you \
approve; prompt-only moves render one. Speed slow/steady/fast. 5 seconds is the usual length (2-10 allowed).
- Crash zooms, whip pans and snorricam are fast by nature; do not ask for slow.

## sound and speech
- `line`: the exact words spoken (up to 200 characters), `delivery`: natural, calm, whisper, tender, urgent, shout, \
radio or announcer, `language` for a line that is not English. LTX renders the voice and the lips together.
- `audio`: the soundscape in a few concrete words ("gulls, harbour wind, rope creaking"), or pick `soundscape`/`score`.

## effects
- Weather effects (rain, lightning, dust, time freeze, slow motion) add a sentence to the shot.
- Transformations (ignite, freeze, gold, bloom, night, age, snowfall, vanish, clones, comic, painting, melt, flood, bts) \
edit the END still: you approve the end state, and LTX renders the change between the two.

## transitions
- Bridge two finished takes. Pair compatible frames: wide to wide, close to close; an eye macro cannot morph into a \
landscape. `idea` says how A becomes B in one sentence ("the camera dives off the rooftop into the avenue below"). \
push is the most reliable style; keep whips to 2 seconds.

## edits with words (one still, no video model)
- face_swap / character_swap need a Cast; outfit, remove and custom need words ("a red leather jacket"); relight takes \
a light (left, right, back, top, golden, blue, neon, candle) or your words.

## checking a take
- Stills: one subject, the framing you asked for, natural eyes and hands, the face matches the Cast, no text.
- Video strip: the action visibly completes; the camera does the named move; nothing appears, vanishes or morphs; eyes \
stay natural; the same person from first frame to last. If not, render again with a new seed or a sharper action, \
and say what you changed.
"""


class StudioError(Exception):
    """A refusal or failure from the studio, worded for the model (never a traceback)."""


class ArgError(Exception):
    """The arguments do not fit the tool's schema."""


DEFAULT_MAX_RENDERS = 20  # a hard cap per MCP session; `openfield mcp --max-renders N` changes it
HINTS = (  # what to do next after a refusal, so the model recovers instead of retrying the same call
    ("plays recorded", "Next: list_takes(where='recorded') shows what Replay can play; replay_take plays one."),
    ("never rendered", "Next: list_takes(where='recorded') shows what Replay can play; replay_take plays one."),
    ("not waiting for approval", "Next: wait_for_take(take_id) shows where the take is."),
    ("no such take", "Next: list_takes shows the take ids in this studio."),
    ("is not finished", "Next: wait_for_take until it has succeeded, then try again."),
    ("no such cast", "Next: list_cast shows the cast ids."),
)


def with_hint(message: str) -> str:
    low = message.lower()
    hint = next((h for key, h in HINTS if key in low), None)
    return f"{message}\n{hint}" if hint and hint not in message else message


# -- the studio's HTTP API ---------------------------------------------------------------------------------------
def _problem(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:300]}"
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        detail = body.get("detail")
        if isinstance(detail, list):  # FastAPI's validation errors
            return "; ".join(f"{'.'.join(str(p) for p in d.get('loc', [])[1:])}: {d.get('msg')}" for d in detail[:4])
        if detail:
            return str(detail)
    return f"HTTP {response.status_code}"


class Studio:
    """A running OpenField Studio, reached over HTTP. `client` replaces the network (tests pass a TestClient)."""

    def __init__(self, base_url: str = DEFAULT_URL, *, client: httpx.Client | None = None, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self._shared = client
        self._local = threading.local()  # one connection pool per worker thread
        self._timeout = timeout
        self.budget: dict[str, Any] | None = None  # the session's render budget, set by the Server

    @property
    def http(self) -> httpx.Client:
        if self._shared is not None:
            return self._shared
        client = getattr(self._local, "client", None)
        if client is None:
            client = self._local.client = httpx.Client(base_url=self.base_url, timeout=self._timeout)
        return client

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise StudioError(f"OpenField Studio is not answering at {self.base_url} ({type(exc).__name__}). Start it "
                              "with `openfield serve` (or `openfield demo` for Replay), or point --url at it.") from None
        if response.status_code >= 400:
            raise StudioError(_problem(response))
        return response

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params={k: v for k, v in params.items() if v is not None}).json()

    def post(self, path: str, body: Any = None, *, data: dict[str, Any] | None = None,
             files: list[tuple[str, tuple[str, bytes, str]]] | None = None) -> Any:
        if files is not None or data is not None:
            response = self.request("POST", path, data=data or {}, files=files or None)
        else:
            response = self.request("POST", path, json=body if body is not None else {})
        return response.json() if response.content else {}

    def media(self, take_id: str, file: str) -> bytes:
        return self.request("GET", f"/api/takes/{seg(take_id)}/media/{file_url(file)}").content

    def thumb(self, take_id: str, file: str, px: int = 0) -> bytes:
        """A still as a small JPEG: made by the studio (?w=), or here when an older studio sends the full image."""
        px = px or STILL_PX
        response = self.request("GET", f"/api/takes/{seg(take_id)}/media/{file_url(file)}", params={"w": px})
        if response.headers.get("content-type", "").startswith("image/jpeg") and len(response.content) < 400_000:
            return response.content
        return thumbnail(response.content, px)

    def strip(self, take: dict[str, Any]) -> bytes:
        """Six frames of a take: the studio's strip.jpg, or made here from the video when the studio has none."""
        try:
            return self.request("GET", f"/api/takes/{seg(take['id'])}/strip.jpg", params={"w": STRIP_FRAME_PX}).content
        except StudioError as exc:
            if str(exc) not in ("Not Found", "Method Not Allowed"):  # the take has no video, or the strip failed
                raise
            return contact_strip(self.media(take["id"], "take.mp4"), take.get("seconds"))  # an older studio

    def page(self, take_id: str) -> str:
        return f"{self.base_url}/#/takes/{seg(take_id)}"

    def media_url(self, take_id: str, file: str) -> str:
        return f"{self.base_url}/api/takes/{seg(take_id)}/media/{file_url(file)}"


# -- content blocks ----------------------------------------------------------------------------------------------
def text(value: Any) -> dict[str, Any]:
    return {"type": "text", "text": value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=1)}


def image(data: bytes, mime: str = "image/jpeg") -> dict[str, Any]:
    return {"type": "image", "data": base64.b64encode(data).decode("ascii"), "mimeType": mime}


def thumbnail(data: bytes, px: int = STILL_PX) -> bytes:
    with Image.open(io.BytesIO(data)) as im:
        rgb = im.convert("RGB")
    rgb.thumbnail((px, px))
    out = io.BytesIO()
    rgb.save(out, "JPEG", quality=80)
    return out.getvalue()


def contact_strip(mp4: bytes, seconds: float | None = None, frames: int = 6) -> bytes:
    """Six frames of a clip, evenly spread, in a 3 x 2 grid: enough to see whether the action happened."""
    with tempfile.TemporaryDirectory(prefix="of-mcp-") as tmp:
        src = Path(tmp) / "take.mp4"
        src.write_bytes(mp4)
        length = seconds or video.probe(src).duration_s or 1.0
        tiles = []
        for i in range(frames):
            at = length * (i + 0.5) / frames
            png = video.extract_frame(src, Path(tmp) / f"f{i}.png", at)
            with Image.open(png) as im:
                tile = im.convert("RGB")
            tile.thumbnail((STRIP_FRAME_PX, STRIP_FRAME_PX))
            tiles.append(tile)
    w, h = tiles[0].size
    cols = 3
    sheet = Image.new("RGB", (w * cols, h * ((len(tiles) + cols - 1) // cols)), "black")
    for i, tile in enumerate(tiles):
        sheet.paste(tile, ((i % cols) * w, (i // cols) * h))
    out = io.BytesIO()
    sheet.save(out, "JPEG", quality=78)
    return out.getvalue()


# -- tools -------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    schema: dict[str, Any]
    run: Callable[[Studio, dict[str, Any]], list[dict[str, Any]]]
    read_only: bool = False
    renders: bool = False  # spends GPU time on a live backend
    destructive: bool = False  # replaces a file or stops someone's render

    def listing(self) -> dict[str, Any]:
        return {"name": self.name, "title": self.title, "description": self.description, "inputSchema": self.schema,
                "annotations": {"title": self.title, "readOnlyHint": self.read_only, "destructiveHint": self.destructive,
                                "idempotentHint": self.read_only, "openWorldHint": self.renders}}


TOOLS: dict[str, Tool] = {}


def tool(name: str, title: str, description: str, properties: dict[str, Any] | None = None,
         required: tuple[str, ...] = (), *, read_only: bool = False, renders: bool = False,
         destructive: bool = False) -> Callable:
    def register(fn: Callable[[Studio, dict[str, Any]], list[dict[str, Any]]]) -> Callable:
        schema = {"type": "object", "properties": properties or {}, "required": list(required),
                  "additionalProperties": False}
        TOOLS[name] = Tool(name, title, description, schema, fn, read_only, renders, destructive)
        return fn
    return register


def _str(desc: str, *, max_len: int | None = None, enum: list[str] | None = None, min_len: int | None = None,
         pattern: str | None = None) -> dict:
    prop: dict[str, Any] = {"type": "string", "description": desc}
    if pattern:
        prop["pattern"] = pattern
    if max_len:
        prop["maxLength"] = max_len
    if min_len:
        prop["minLength"] = min_len
    if enum:
        prop["enum"] = enum
    return prop


def _int(desc: str, lo: int | None = None, hi: int | None = None) -> dict:
    prop: dict[str, Any] = {"type": "integer", "description": desc}
    if lo is not None:
        prop["minimum"] = lo
    if hi is not None:
        prop["maximum"] = hi
    return prop


def _num(desc: str, lo: float, hi: float) -> dict:
    return {"type": "number", "description": desc, "minimum": lo, "maximum": hi}


def _bool(desc: str) -> dict:
    return {"type": "boolean", "description": desc}


TAKE_ID = _str("A take id, like tk_20261023_095051_b57e.", max_len=40, pattern=TAKE_PATTERN)
CAST_ID = _str("A Cast id from list_cast, like ca_38fd9d28.", max_len=11, pattern=CAST_PATTERN)
SEED = _int("A fixed seed, to repeat a render exactly; leave it out for a new one.", 0, 2**31 - 1)
CATALOG = rigs.catalog()
MOVE_IDS = [m["id"] for m in CATALOG["moves"]]
OPTIONS = CATALOG["options"]

SHOT = {
    "subject": _str("What the first frame shows: who (look, wardrobe), where, light, time of day, framing. 20-60 words; "
                    "no camera directions here.", min_len=3, max_len=800),
    "action": _str("What visibly happens during the shot, present tense, end state named (\"she lifts the lid and "
                   "steam rises\"). Rendered by the video model only.", max_len=rigs.ACTION_MAX),
    "move": _str("The camera move id (list_options section moves); reliable ones held on real renders here. Default dolly_in.",
                 enum=MOVE_IDS),
    "seconds": _int("Length in seconds; 5 is the usual length.", *CATALOG["limits"]["duration_seconds"]),
    "speed": _str("How fast the camera moves.", enum=list(OPTIONS["speed"])),
    "effect": _str("A weather effect (a sentence) or a transformation (the end still is edited and you approve it).",
                   enum=list(OPTIONS["effect"])),
    "quality": _str("draft = quick look (the least GPU time), standard = the default, fine = slow and sharp.",
                    enum=["draft", "standard", "fine"]),
    "orientation": _str("landscape (16:9) or portrait (9:16).", enum=["landscape", "portrait"]),
    "quick": _bool("One still and the move in words, even for a keyframed move: gives an action room to happen."),
    "cast_id": {**CAST_ID, "description": "A Cast character (list_cast) whose face the stills keep; checked by the "
                                          "local face check."},
    "line": _str("The exact words a character speaks; LTX renders voice and lips together.", max_len=rigs.LINE_MAX),
    "delivery": _str("How the line is spoken.", enum=[d["id"] for d in CATALOG["dialogue"]["deliveries"]]),
    "language": _str("The language of the line, when it is not English (e.g. Spanish).", max_len=rigs.LANGUAGE_MAX),
    "audio": _str("The soundscape in a few concrete words (\"gulls, harbour wind\").", max_len=400),
    "angle": _str("Re-shoot the first still from another angle: azimuth/elevation/distance, e.g. back_left/low/wide "
                  "(list_options section angles). Default front/eye/medium.", max_len=40),
    "sensor": _str("Camera body look.", enum=list(OPTIONS["sensor"])),
    "lens": _str("Lens character.", enum=list(OPTIONS["lens"])),
    "focal_length_mm": _int("Focal length in mm.", *CATALOG["limits"]["focal_length_mm"]),
    "aperture": _str("Aperture: f1.4 shallow focus, f11 deep.", enum=list(OPTIONS["aperture"])),
    "lighting": _str("Lighting setup.", enum=list(OPTIONS["lighting"])),
    "grade": _str("Colour grade.", enum=list(OPTIONS["grade"])),
    "score": _str("Music under the shot.", enum=list(OPTIONS["score"])),
    "soundscape": _str("Ambient sound bed.", enum=list(OPTIONS["soundscape"])),
    "seed": SEED,
}
RIG_FIELDS = {"move": "movement", "seconds": "duration_seconds", "speed": "speed", "effect": "effect", "angle": "angle",
              "sensor": "sensor", "lens": "lens", "focal_length_mm": "focal_length_mm", "aperture": "aperture",
              "lighting": "lighting", "grade": "grade", "score": "score", "soundscape": "soundscape"}
BODY_FIELDS = ("subject", "action", "cast_id", "line", "delivery", "language", "audio", "seed", "orientation", "quality")


def direct_body(args: dict[str, Any]) -> dict[str, Any]:
    body = {k: args[k] for k in BODY_FIELDS if args.get(k) is not None}
    body["rig"] = {RIG_FIELDS[k]: args[k] for k in RIG_FIELDS if args.get(k) is not None}
    if args.get("quick"):
        body["prompt_only"] = True
    return body


def _local(path: str, what: str) -> Path:
    """A path on this computer: absolute, and never a network share (opening one would send the user's credentials)."""
    if path.startswith(("\\\\", "//")):
        raise ArgError(f"{what}: network paths are not used; copy the file to this computer first")
    p = Path(path).expanduser()
    if not p.is_absolute():
        raise ArgError(f"{what}: give an absolute path (got {path!r})")
    return p


def _file(path: str, suffixes: tuple[str, ...], what: str, max_mb: int = MAX_IMAGE_MB) -> tuple[str, bytes, str]:
    p = _local(path, what)
    if not p.is_file():
        raise ArgError(f"{what}: no such file: {p}")
    if p.suffix.lower() not in suffixes:
        raise ArgError(f"{what}: expected one of {', '.join(suffixes)}")
    if p.stat().st_size > max_mb * 1024 * 1024:
        raise ArgError(f"{what}: larger than the studio's {max_mb} MB limit")
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
            ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".mkv": "video/x-matroska"}
    return p.name, p.read_bytes(), mime.get(p.suffix.lower(), "application/octet-stream")


def started(studio: Studio, take: dict[str, Any], then: str = "Call wait_for_take with this id.") -> list[dict]:
    return [text({"take_id": take["id"], "kind": take.get("kind"), "status": take.get("status"),
                  "label": take.get("label"), "page": studio.page(take["id"]), "next": then})]


@tool("studio_status", "Studio status",
      "Where renders go and what is proven. Call this first: on Replay the studio renders nothing (it plays recorded "
      "takes and refuses a recipe never rendered); on a live GPU box every render costs the owner money.",
      read_only=True)
def t_status(studio: Studio, _: dict[str, Any]) -> list[dict]:
    s = studio.get("/api/status")
    cat = studio.get("/api/moves")
    backend = s.get("backend", {})
    moves = cat.get("moves", [])
    effects = [e for e in cat.get("effects", []) if e.get("id") != "none"]
    return [text({
        "studio": studio.base_url, "version": s.get("version"), "backend": backend.get("label"),
        "kind": backend.get("kind"), "can_render": not backend.get("locked", False), "health": backend.get("health"),
        "recorded_takes": s.get("recorded_takes"), "face_check": (s.get("face_check") or {}).get("available"),
        "render_budget": studio.budget,
        "reliable": {"moves": f"{sum(1 for m in moves if m.get('validated'))}/{len(moves)}",
                   "effects": f"{sum(1 for e in effects if e.get('tested'))}/{len(effects)}",
                   "transitions": [t["id"] for t in cat.get("transitions", {}).get("styles", []) if t.get("tested")],
                   "edits": [p["id"] for p in cat.get("edits", {}).get("presets", []) if p.get("tested")],
                   "quality": cat.get("quality_tested")},
        "note": ("Replay: recorded takes only. A recipe that was never rendered is refused; list_takes(where='recorded') "
                 "shows what can be played and replay_take plays one." if backend.get("locked") else
                 "Live: renders run on this backend and spend GPU time. Plan first; explore at draft."),
    })]


def options_view(cat: dict[str, Any], section: str = "all") -> dict[str, Any]:
    groups = {g["id"]: g["label"] for g in cat.get("groups", [])}
    view: dict[str, Any] = {}

    def want(name: str) -> bool:
        return section in ("all", name)

    if want("moves"):
        view["moves"] = [{"id": m["id"], "label": m["label"], "group": groups.get(m["group"], m["group"]),
                          "mode": m["mode"], "stills": m["anchors"], "reliable": bool(m.get("validated"))}
                         for m in cat.get("moves", [])]
        view["move_modes"] = {"keyframed": "several stills you approve pin the camera path; the subject barely moves",
                              "prompt_only": "one still, the move in words: room for action",
                              "experimental": "in words, not yet reliable"}
    if want("effects"):
        view["effects"] = [{"id": e["id"], "label": e["label"], "kind": e.get("kind"), "reliable": e.get("tested")}
                           for e in cat.get("effects", []) if e.get("id") != "none"]
    if want("look"):
        view["look"] = {**{k: v for k, v in cat.get("options", {}).items() if k != "effect"},
                        "focal_length_mm": cat.get("limits", {}).get("focal_length_mm"), "defaults": cat.get("defaults")}
    if want("dialogue"):
        view["dialogue"] = cat.get("dialogue")
    if want("edits"):
        view["edits"] = cat.get("edits")
    if want("transitions"):
        view["transitions"] = cat.get("transitions")
    if want("angles"):
        a = cat.get("angles", {})
        view["angles"] = {"format": "azimuth/elevation/distance", "default": a.get("default"),
                          "azimuths": [x["id"] for x in a.get("azimuths", [])],
                          "elevations": [x["id"] for x in a.get("elevations", [])],
                          "distances": [x["id"] for x in a.get("distances", [])], "reliable": a.get("tested")}
    if want("takes"):
        view["takes"] = {"extend": cat.get("extend"), "upscale": cat.get("upscale"),
                         "shots_board": [b.get("label") for b in (cat.get("shots") or {}).get("board", [])],
                         "quality": [{k: q.get(k) for k in ("id", "label", "what")} | {"reliable": q.get("tested")} for q in cat.get("quality", [])]}
    if want("limits"):
        view["limits"] = {**cat.get("limits", {}), "action_max": cat.get("action_max")}
    return view


SECTIONS = ["all", "moves", "effects", "look", "dialogue", "edits", "transitions", "angles", "takes", "limits"]


@tool("list_options", "List options",
      "The studio's catalog, compact: camera moves (with mode and a reliable flag), effects, look (sensor, lens, lighting, "
      "grade, music), dialogue deliveries, edit presets, transition styles, angles, extend/upscale/quality. Reliable means "
      "it held on a real render here; prefer reliable ones.",
      {"section": _str("One section, or all.", enum=SECTIONS)}, read_only=True)
def t_options(studio: Studio, a: dict[str, Any]) -> list[dict]:
    return [text(options_view(studio.get("/api/moves"), a.get("section", "all")))]


@tool("read_guide", "Read the prompting guide",
      "How to write shots for these models: subject (the first frame), action (what visibly happens), moves, sound and "
      "speech, effects, transitions, edits, and how to check a take. Read it before the first shot.", read_only=True)
def t_guide(_studio: Studio, _a: dict[str, Any]) -> list[dict]:
    return [text(GUIDE)]


@tool("list_cast", "List cast",
      "The characters, products and places whose look the stills keep. Faces come only from here, because consent is "
      "recorded with each one.", read_only=True)
def t_cast(studio: Studio, _: dict[str, Any]) -> list[dict]:
    return [text([{"cast_id": c["id"], "name": c["name"], "kind": c.get("kind"), "consent": c.get("consent"),
                   "refs": len(c.get("refs", []))} for c in studio.get("/api/cast")])]


@tool("create_character", "Create a character",
      "Paint 1-4 portrait candidates of a fictional character from words (Qwen-Image 2.1). Then wait_for_take shows "
      "them; keep one with add_character(from_take, candidate, name).",
      {"description": _str("Who they are: age, look, hair, wardrobe, mood, e.g. 'a weathered fisherwoman in her "
                           "sixties, silver braid, yellow oilskin'.", min_len=3, max_len=400),
       "count": _int("How many candidates.", 1, 4), "seed": SEED}, ("description",), renders=True)
def t_create_character(studio: Studio, a: dict[str, Any]) -> list[dict]:
    take = studio.post("/api/cast/generate", {k: a[k] for k in ("description", "count", "seed") if k in a})
    return started(studio, take, "Call wait_for_take to see the candidates, then add_character with the one you keep.")


@tool("add_character", "Add a character",
      "Keep a character in the Cast: either a candidate of a create_character take (from_take + candidate), or 1-8 "
      "photos from disk with the consent that covers them.",
      {"name": _str("The character's name.", min_len=1, max_len=40),
       "from_take": TAKE_ID, "candidate": _int("The candidate number shown by wait_for_take (1-based).", 1, 4),
       "photos": {"type": "array", "items": {"type": "string"}, "maxItems": 8,
                  "description": "Absolute paths of photos (png, jpg, webp) of one person, product or place."},
       "consent": _str("For photos: mine (photos of me), consented (they agreed), fictional (AI-made or invented).",
                       enum=["mine", "consented", "fictional"]),
       "kind": _str("What the photos show.", enum=["character", "product", "wardrobe", "location"])}, ("name",))
def t_add_character(studio: Studio, a: dict[str, Any]) -> list[dict]:
    if a.get("from_take"):
        if not a.get("candidate"):
            raise ArgError("from_take needs the candidate number")
        cast = studio.post("/api/cast/from-take", {"take_id": a["from_take"], "candidate": a["candidate"],
                                                   "name": a["name"]})
    elif a.get("photos"):
        if not a.get("consent"):
            raise ArgError("photos need consent: mine, consented or fictional")
        files = [("files", _file(p, IMAGE_SUFFIXES, "photos", MAX_PHOTO_MB)) for p in a["photos"]]
        cast = studio.post("/api/cast", data={"name": a["name"], "kind": a.get("kind", "character"),
                                              "consent": a["consent"]}, files=files)
    else:
        raise ArgError("give from_take + candidate, or photos + consent")
    return [text({"cast_id": cast["id"], "name": cast["name"], "consent": cast.get("consent_text"),
                  "next": "Pass cast_id to direct_shot, edit_take or reshoot_video."})]


@tool("plan_shot", "Plan a shot",
      "Free and instant: compile a shot without rendering. Shows the exact video prompt, the still prompt, how many "
      "stills and passes it takes, notes (e.g. when a keyframed move will freeze the action) and the measured time on "
      "this backend. Use it to check your words before direct_shot.", SHOT, ("subject",), read_only=True)
def t_plan(studio: Studio, a: dict[str, Any]) -> list[dict]:
    body = direct_body(a)
    planned = studio.post("/api/direct/plan", body)
    plan = planned.get("plan", {})
    rig = plan.get("rig", {})
    estimate = studio.get("/api/direct/estimate", quality=body.get("quality", "standard"),
                          movement=rig.get("movement"), duration_seconds=rig.get("duration_seconds"),
                          prompt_only=bool(body.get("prompt_only")), orientation=body.get("orientation", "landscape"),
                          effect=rig.get("effect"), angle=rig.get("angle"))
    return [text({"mode": plan.get("mode"), "stills": len(plan.get("anchors", [])),
                  "passes": len(plan.get("segments", [])), "seconds": plan.get("total_seconds"),
                  "video_prompt": plan.get("prompt"), "still_prompt": planned.get("still_prompt"),
                  "anchor_edits": [x.get("edit_prompt") for x in plan.get("anchors", []) if x.get("edit_prompt")],
                  "notes": plan.get("notes"), "templates": planned.get("templates"),
                  "measured_render_s": estimate.get("seconds"), "measured_basis": estimate.get("basis")})]


@tool("direct_shot", "Direct a shot",
      "Render one shot: Qwen-Image 2.1 paints the still(s), then (after you approve them) LTX 2.5 renders the video with "
      "sound. Returns a take id at once; the take stops at awaiting_approval unless auto_approve. Use from_image to "
      "start from a picture on disk instead of a painted still.",
      {**SHOT, "from_image": _str("Absolute path of an image to use as the first frame (png, jpg, webp).", max_len=400),
       "auto_approve": _bool("Skip the still review (only when re-rendering a recipe you already checked).")},
      ("subject",), renders=True)
def t_direct(studio: Studio, a: dict[str, Any]) -> list[dict]:
    body = direct_body(a)
    if a.get("auto_approve"):
        body["auto_approve"] = True
    if a.get("from_image"):
        source = _file(a["from_image"], IMAGE_SUFFIXES, "from_image")
        take = studio.post("/api/takes/direct/from-image", data={"request": json.dumps(body)}, files=[("source", source)])
    else:
        take = studio.post("/api/takes/direct", body)
    return started(studio, take, "Call wait_for_take: it shows the stills to approve, then the finished take.")


def _strip(studio: Studio, take: dict[str, Any]) -> list[dict]:
    try:
        return [image(studio.strip(take))]
    except Exception as exc:  # a strip is a convenience: never fail the call over it
        return [text(f"(no strip: {type(exc).__name__})")]


def take_view(studio: Studio, take: dict[str, Any], show: bool = True) -> list[dict]:
    status = take.get("status")
    tid = take["id"]
    head = {"take_id": tid, "kind": take.get("kind"), "status": status, "stage": take.get("stage"),
            "progress": take.get("progress"), "label": take.get("label"), "page": studio.page(tid)}
    blocks: list[dict] = []
    if status == "awaiting_approval":
        anchors = take.get("anchors") or []
        identity = take.get("identity") or {}
        head["next"] = ("Look at every still. approve_stills(take_id) to render the video, or approve_stills(take_id, "
                        "reroll=[indices]) to paint the bad ones again.")
        blocks.append(text(head))
        for a in anchors:
            check = identity.get("hero" if a.get("index") == 0 else f"anchor_{a.get('index')}") or {}
            score = f", face check {check.get('status')} {check.get('score'):.2f}" if check.get("score") is not None else ""
            blocks.append(text(f"still {a.get('index')} ({a.get('role')}{score})"))
            if show:
                try:
                    blocks.append(image(studio.thumb(tid, a["file"])))
                except StudioError as exc:
                    blocks.append(text(f"(could not load: {exc})"))
        return blocks
    if status == "succeeded":
        head.update({"seconds": take.get("seconds"), "size": take.get("size"), "notes": take.get("notes") or None})
        candidates = take.get("candidates") or []
        if candidates:
            head["next"] = "Keep one with add_character(from_take=take_id, candidate=N, name=...)."
            blocks.append(text(head))
            for n, file in enumerate(candidates, 1):
                blocks.append(text(f"candidate {n}"))
                if show:
                    blocks.append(image(studio.thumb(tid, file)))
            return blocks
        if any(o.get("file") == "take.mp4" for o in take.get("outputs") or []):
            head["video"] = studio.media_url(tid, "take.mp4")
            head["next"] = ("Check the strip: did the action happen, did the camera move as named, did anything morph? "
                            "Then build on it (edit_take, transition, extend_take, dub_take, upscale_take, make_movie) "
                            "or save_take.")
            blocks.append(text(head))
            if show:
                blocks += _strip(studio, take)
            return blocks
    if status == "failed":
        head["error"] = take.get("error")
    elif status not in TERMINAL:
        head["next"] = "Still rendering. Call wait_for_take again; never re-submit a running render."
        head["poll_after_s"] = 10
    blocks.insert(0, text(head))
    return blocks


@tool("wait_for_take", "Wait for a take",
      "Wait until a take needs you or is done (up to timeout_s, then report progress). Awaiting approval: shows each "
      "still as an image. Finished: a six-frame strip of the video (or the portrait candidates). Failed: the reason.",
      {"take_id": TAKE_ID, "timeout_s": _int("Seconds to wait before reporting progress.", 0, WAIT_MAX_S),
       "show_images": _bool("Return the stills or the strip as images (default true).")},
      ("take_id",), read_only=True)
def t_wait(studio: Studio, a: dict[str, Any]) -> list[dict]:
    deadline = time.monotonic() + a.get("timeout_s", WAIT_DEFAULT_S)
    while True:
        take = studio.get(f"/api/takes/{seg(a['take_id'])}")
        if take.get("status") in TERMINAL | {"awaiting_approval"} or time.monotonic() >= deadline:
            return take_view(studio, take, a.get("show_images", True))
        time.sleep(1.5)


@tool("approve_stills", "Approve stills",
      "Answer a take that is awaiting approval: with no reroll the video renders from these stills; reroll lists the "
      "still indices to paint again (a new review follows).",
      {"take_id": TAKE_ID, "reroll": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 7}, "maxItems": 8,
                                      "description": "Still indices to paint again; empty approves."}},
      ("take_id",), renders=True)
def t_approve(studio: Studio, a: dict[str, Any]) -> list[dict]:
    take = studio.post(f"/api/takes/{seg(a['take_id'])}/approve", {"reroll": a.get("reroll", [])})
    what = "repainting those stills" if a.get("reroll") else "rendering the video"
    return started(studio, take, f"Approved; {what}. Call wait_for_take.")


@tool("edit_take", "Edit with words",
      "Change one still of a finished take with words (Qwen-Image 2.1 edit; no video model runs): face_swap or "
      "character_swap put a Cast in; outfit, remove and custom need words; relight takes a light or words. The new take "
      "plays the still before and after.",
      {"take_id": TAKE_ID, "preset": _str("The edit.", enum=[p["id"] for p in CATALOG["edits"]["presets"]]),
       "detail": _str("The words: what to change, the outfit, what to remove, or the light (left, right, back, top, "
                      "golden, blue, neon, candle).", max_len=rigs.EDIT_DETAIL_MAX),
       "cast_id": {**CAST_ID, "description": "The Cast put in, for face_swap and character_swap."},
       "still": _str("Which still of the take, by its path in the take (default: its first approved still).",
                     max_len=200, pattern=FILE_PATTERN), "seed": SEED}, ("take_id", "preset"), renders=True)
def t_edit(studio: Studio, a: dict[str, Any]) -> list[dict]:
    body = {"preset": a["preset"], "take": a["take_id"]}
    body.update({k: a[k] for k in ("detail", "cast_id", "still", "seed") if a.get(k) is not None})
    return started(studio, studio.post("/api/takes/edit", data={"request": json.dumps(body)}))


@tool("shots_board", "Shots board",
      "Re-shoot one still as a board of nine camera setups (wide, three-quarters, close-up, low, high...) with the same "
      "face: from a finished take or an image on disk.",
      {"take_id": TAKE_ID, "image": _str("Absolute path of an image instead of a take.", max_len=400),
       "cast_id": {**CAST_ID, "description": "Check the face against this Cast."},
       "quality": _str("Still quality.", enum=["draft", "standard", "fine"]), "seed": SEED}, renders=True)
def t_shots(studio: Studio, a: dict[str, Any]) -> list[dict]:
    body = {k: v for k, v in {"take": a.get("take_id"), "cast_id": a.get("cast_id"), "quality": a.get("quality"),
                              "seed": a.get("seed")}.items() if v is not None}
    files = [("source", _file(a["image"], IMAGE_SUFFIXES, "image"))] if a.get("image") else None
    if not files and not body.get("take"):
        raise ArgError("give take_id or image")
    return started(studio, studio.post("/api/takes/shots", data={"request": json.dumps(body)}, files=files))


@tool("transition", "Transition",
      "Render a bridge between two finished takes with LTX 2.5 (the last frame of the first to the first frame of the "
      "second). Pair compatible frames (wide to wide); say how A becomes B in idea. push is the most reliable style.",
      {"first": TAKE_ID, "second": TAKE_ID,
       "style": _str("The bridge.", enum=[s["id"] for s in CATALOG["transitions"]["styles"]]),
       "seconds": _int("Length; whips want 2.", min(rigs.TRANSITION_SECONDS), max(rigs.TRANSITION_SECONDS)),
       "idea": _str("How A becomes B, one sentence (\"the camera dives off the rooftop into the avenue below\").",
                    max_len=rigs.TRANSITION_IDEA_MAX), "seed": SEED}, ("first", "second"), renders=True)
def t_transition(studio: Studio, a: dict[str, Any]) -> list[dict]:
    body = {k: a[k] for k in ("first", "second", "style", "seconds", "idea", "seed") if a.get(k) is not None}
    return started(studio, studio.post("/api/takes/transition", body))


@tool("extend_take", "Extend a take",
      "Continue a finished take from its last frame with LTX 2.5; the new take plays the original, then the extension.",
      {"take_id": TAKE_ID, "seconds": _int("Seconds to add.", min(rigs.EXTEND_SECONDS), max(rigs.EXTEND_SECONDS)),
       "seed": SEED}, ("take_id",), renders=True)
def t_extend(studio: Studio, a: dict[str, Any]) -> list[dict]:
    body = {"take": a["take_id"], **{k: a[k] for k in ("seconds", "seed") if a.get(k) is not None}}
    return started(studio, studio.post("/api/takes/extend", body))


def hero_still(take: dict[str, Any], receipt: dict[str, Any]) -> str:
    """Where a dub starts: the hero before any angle, else the first approved still, else the poster."""
    inputs = receipt.get("inputs") or {}
    angle = inputs.get("angle") or {}
    anchors = inputs.get("anchors") or []
    if angle.get("source_file"):
        return angle["source_file"]
    if anchors and isinstance(anchors[0], dict) and anchors[0].get("file"):
        return anchors[0]["file"]
    return next((o["file"] for o in take.get("outputs") or [] if o.get("role") == "poster"), "poster.png")


@tool("dub_take", "Dub a take",
      "Re-render a talking take speaking a new line in another language: the same still, rig and seed, so the voice "
      "and the lips are rendered together (the picture moves anew).",
      {"take_id": TAKE_ID, "language": _str("The new language, e.g. Spanish.", min_len=2, max_len=rigs.LANGUAGE_MAX),
       "line": _str("The line, written in that language.", min_len=1, max_len=rigs.LINE_MAX)},
      ("take_id", "language", "line"), renders=True)
def t_dub(studio: Studio, a: dict[str, Any]) -> list[dict]:
    take = studio.get(f"/api/takes/{seg(a['take_id'])}")
    recipe = take.get("recipe") or {}
    if take.get("kind") != "direct" or not recipe.get("line"):
        raise ArgError("only a finished Direct take with a spoken line can be dubbed")
    receipt = json.loads(studio.media(take["id"], "receipt.json"))
    still = hero_still(take, receipt)
    body = {"subject": recipe["subject"], "rig": recipe.get("rig") or {}, "orientation": recipe.get("orientation",
            "landscape"), "auto_approve": True, "line": a["line"].strip(), "language": a["language"].strip(),
            "delivery": recipe.get("delivery") or "natural"}
    body.update({k: recipe[k] for k in ("seed", "audio", "action", "quality") if recipe.get(k) is not None})
    if recipe.get("prompt_only"):
        body["prompt_only"] = True
    kind = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(Path(still).suffix.lower(), "image/png")
    source = (Path(still).name, studio.media(take["id"], still), kind)
    made = studio.post("/api/takes/direct/from-image", data={"request": json.dumps(body)}, files=[("source", source)])
    return started(studio, made)


@tool("upscale_take", "Upscale a take",
      "Enlarge a finished take with Real-ESRGAN x4 through the official video-upscale graph, then resize to the target. "
      "Nothing is invented; 2k is the usual target.",
      {"take_id": TAKE_ID, "target": _str("The size.", enum=[t["id"] for t in CATALOG["upscale"]["targets"]])},
      ("take_id",), renders=True)
def t_upscale(studio: Studio, a: dict[str, Any]) -> list[dict]:
    return started(studio, studio.post("/api/takes/upscale", {"take": a["take_id"], "target": a.get("target", "2k")}))


@tool("reshoot_video", "Re-shoot a video",
      "Wan Animate 2: replace the person in a filmed clip with a Cast character or a reference image, keeping the "
      "motion. face_only swaps just the face (needs a Cast).",
      {"video": _str("Absolute path of the clip (mp4, mov, webm), one person, a few seconds.", max_len=400),
       "prompt": _str("Who the new character is and what they wear.", min_len=3, max_len=800),
       "cast_id": {**CAST_ID, "description": "The Cast put in."},
       "reference": _str("Absolute path of a reference image instead of a Cast.", max_len=400),
       "face_only": _bool("Swap only the face (needs cast_id)."),
       "background": _str("Optional: the background caption.", max_len=400),
       "motion": _str("Optional: the motion caption.", max_len=400), "seed": SEED},
      ("video", "prompt"), renders=True)
def t_reshoot(studio: Studio, a: dict[str, Any]) -> list[dict]:
    data = {"prompt": a["prompt"], "face_only": "true" if a.get("face_only") else "false"}
    data.update({k: str(a[k]) for k in ("cast_id", "background", "motion", "seed") if a.get(k) is not None})
    files = [("source", _file(a["video"], VIDEO_SUFFIXES, "video", MAX_VIDEO_MB))]
    if a.get("reference"):
        files.append(("reference", _file(a["reference"], IMAGE_SUFFIXES, "reference")))
    elif not a.get("cast_id"):
        raise ArgError("give cast_id or reference")
    return started(studio, studio.post("/api/takes/reshoot", data=data, files=files))


@tool("make_movie", "Make a movie",
      "Join 2-8 finished takes, in order, into one movie with crossfades and matched loudness (a new take with its own "
      "receipt that lists every source). Put transition takes between shots for rendered bridges.",
      {"take_ids": {"type": "array", "items": {"type": "string", "pattern": TAKE_PATTERN}, "minItems": 2, "maxItems": 8,
                    "description": "The takes in playing order."},
       "crossfade_s": _num("Crossfade between clips in seconds (0 = hard cut).", 0.0, 2.0)}, ("take_ids",))
def t_movie(studio: Studio, a: dict[str, Any]) -> list[dict]:
    take = studio.post("/api/exports/reel", {"take_ids": a["take_ids"], "crossfade_s": a.get("crossfade_s", 0.5)})
    return take_view(studio, take)


@tool("export_vertical", "Export 9:16",
      "Crop a finished take to a vertical 9:16 video for Reels, Shorts and TikTok; focus_x chooses what stays in frame.",
      {"take_id": TAKE_ID, "focus_x": _num("0 = keep the left, 0.5 = centre, 1 = keep the right.", 0.0, 1.0)},
      ("take_id",))
def t_vertical(studio: Studio, a: dict[str, Any]) -> list[dict]:
    take = studio.post(f"/api/takes/{seg(a['take_id'])}/export/vertical", {"focus_x": a.get("focus_x", 0.5)})
    return take_view(studio, take)


@tool("list_takes", "List takes",
      "Recent takes in this studio (where=studio), or the recorded takes Replay can play (where=recorded).",
      {"where": _str("studio or recorded.", enum=["studio", "recorded"]),
       "kind": _str("Only this kind.", enum=["direct", "reshoot", "edit", "shots", "transition", "extend", "upscale",
                                             "portrait", "export"]),
       "limit": _int("At most this many.", 1, 200)}, read_only=True)
def t_takes(studio: Studio, a: dict[str, Any]) -> list[dict]:
    limit = a.get("limit", 30)
    if a.get("where") == "recorded":
        rows = [r for r in studio.get("/api/replay/recorded") if not a.get("kind") or r.get("kind") == a["kind"]]
        return [text([{"take_id": r.get("id"), "kind": r.get("kind"), "label": r.get("label"),
                       "subject": (r.get("recipe") or {}).get("subject"),
                       "move": ((r.get("recipe") or {}).get("rig") or {}).get("movement")} for r in rows[:limit]])]
    rows = studio.get("/api/takes", kind=a.get("kind"), limit=limit)
    return [text([{"take_id": t["id"], "kind": t.get("kind"), "status": t.get("status"), "label": t.get("label"),
                   "seconds": t.get("seconds"), "created_at": t.get("created_at")} for t in rows])]


@tool("replay_take", "Replay a recorded take",
      "On Replay: play a recorded take into this studio as a new take, free (nothing renders). The new take then works "
      "with wait_for_take, get_receipt, make_movie, export_vertical and save_take. list_takes(where='recorded') lists "
      "what can be replayed.", {"take_id": TAKE_ID}, ("take_id",))
def t_replay(studio: Studio, a: dict[str, Any]) -> list[dict]:
    take = studio.post("/api/replay/recreate", {"id": a["take_id"]})
    return started(studio, take, "Call wait_for_take with this id; it finishes in seconds.")


@tool("get_receipt", "Get a receipt",
      "A take's receipt: whether its checksum holds, the exact model files and licences, the open-weights audit, the "
      "graph hashes, the backend and render time, and a recipe link that recreates it.",
      {"take_id": TAKE_ID}, ("take_id",), read_only=True)
def t_receipt(studio: Studio, a: dict[str, Any]) -> list[dict]:
    view = studio.get(f"/api/takes/{seg(a['take_id'])}/receipt")
    r = view.get("receipt") or {}
    workflow = r.get("workflow") or {}
    return [text({"take_id": a["take_id"], "checksum_holds": view.get("verified"), "kind": (r.get("take") or {}).get("kind"),
                  "models": [{"role": m.get("role"), "file": m.get("file"), "license": m.get("license"),
                              "open_weights": m.get("open_weights")} for m in r.get("models") or []],
                  "audit": r.get("audit"), "template": workflow.get("template"),
                  "graphs": [{"stage": x.get("stage"), "sha256": x.get("workflow_sha256")} for x in workflow.get("runs") or []],
                  "backend": r.get("backend"), "identity": (r.get("identity") or {}).get("status"),
                  "prompt": (r.get("inputs") or {}).get("final_prompt"), "recipe_link": view.get("recipe_link"),
                  "disclosure": r.get("disclosure")})]


@tool("save_take", "Save a take",
      "Download a finished take's video (or another of its files) to a path on this computer.",
      {"take_id": TAKE_ID, "path": _str("Absolute path to write, e.g. C:/Users/me/Videos/scene.mp4.", max_len=400),
       "file": _str("Which file of the take (default take.mp4).", max_len=200, pattern=FILE_PATTERN),
       "overwrite": _bool("Replace an existing file.")}, ("take_id", "path"), destructive=True)
def t_save(studio: Studio, a: dict[str, Any]) -> list[dict]:
    target = _local(a["path"], "path")
    source = a.get("file", "take.mp4")
    if target.suffix.lower() != Path(source).suffix.lower():
        raise ArgError(f"path: save a {Path(source).suffix} file under a {Path(source).suffix} name")
    if target.exists() and not a.get("overwrite"):
        raise ArgError(f"{target} exists; pass overwrite=true to replace it")
    data = studio.media(a["take_id"], source)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return [text({"saved": str(target), "bytes": len(data)})]


@tool("cancel_take", "Cancel a take", "Stop a take that is rendering or waiting for approval.",
      {"take_id": TAKE_ID}, ("take_id",), destructive=True)
def t_cancel(studio: Studio, a: dict[str, Any]) -> list[dict]:
    take = studio.post(f"/api/takes/{seg(a['take_id'])}/cancel")
    return [text({"take_id": take["id"], "status": take.get("status")})]


# -- prompts and resources ---------------------------------------------------------------------------------------
PROMPTS: dict[str, dict[str, Any]] = {
    "make_a_movie": {
        "title": "Make a short movie",
        "description": "Plan, render, check and cut a short movie from an idea.",
        "arguments": [{"name": "idea", "description": "What the movie is about.", "required": True},
                      {"name": "shots", "description": "How many shots (2-6, default 3).", "required": False},
                      {"name": "format", "description": "landscape or vertical (default landscape).", "required": False}],
        "template": (
            "Make a short movie with OpenField Studio: {idea}\n\n"
            "1. studio_status, then read openfield://guide/prompting and list_options(section='moves').\n"
            "2. Write a shot list of {shots} shots: for each, subject (the first frame), action (what visibly happens, "
            "end state named), a reliable move that suits it (one-still moves for action beats), and a line if someone "
            "speaks. Keep one look across shots (same sensor, lens, grade). Show me the list before rendering.\n"
            "3. For a recurring person: create_character, look at the candidates, add_character, and pass cast_id.\n"
            "4. plan_shot each shot and fix any note that warns the action will freeze.\n"
            "5. direct_shot each shot (orientation {orientation}); wait_for_take; look at the stills and approve or "
            "re-roll; wait again and check the strip: action done, camera move right, nothing morphing, eyes natural. "
            "Re-render any shot that fails, with a new seed or sharper action.\n"
            "6. Bridge shots that should flow with transition (style push, an idea sentence); then make_movie in "
            "order with crossfade_s 0.4.\n"
            "7. Give me the movie's page link and video link, every take id, and what you re-rendered and why."),
    },
    "direct_a_shot": {
        "title": "Direct one shot",
        "description": "Turn an idea into one checked take.",
        "arguments": [{"name": "idea", "description": "The shot you want.", "required": True}],
        "template": (
            "Direct this shot with OpenField Studio: {idea}\n\n"
            "Read openfield://guide/prompting. Split the idea into subject (the first frame), action (what visibly "
            "happens, end state named) and a reliable move. plan_shot it and read the prompts and notes; then "
            "direct_shot, approve the stills only after looking at them, and check the finished strip before you call "
            "it done. Report the page link."),
    },
    "check_a_take": {
        "title": "Check a take",
        "description": "Judge a finished take the way the studio's own examples are judged.",
        "arguments": [{"name": "take_id", "description": "The take to check.", "required": True}],
        "template": (
            "wait_for_take {take_id} and judge the strip strictly: (1) every action in the recipe visibly happens to "
            "its end; (2) the camera does the named move; (3) nothing appears, vanishes or morphs; (4) eyes and hands "
            "look natural; (5) the same person throughout. get_receipt for the recipe. Say HOLD or FAIL per point, and "
            "for a FAIL the change you would render next."),
    },
}

RESOURCES = {
    "openfield://guide/prompting": {"name": "prompting-guide", "title": "Writing shots for OpenField Studio",
                                    "description": "How to write subject, action, moves, sound and transitions.",
                                    "mimeType": "text/markdown"},
    "openfield://catalog": {"name": "catalog", "title": "The studio's catalog",
                            "description": "Moves, effects, look, dialogue, edits, transitions, angles (compact JSON).",
                            "mimeType": "application/json"},
}


def render_prompt(name: str, args: dict[str, Any]) -> dict[str, Any]:
    spec = PROMPTS.get(name)
    if spec is None:
        raise RpcError(-32602, f"unknown prompt: {name}")
    missing = [x["name"] for x in spec["arguments"] if x.get("required") and not args.get(x["name"])]
    if missing:
        raise RpcError(-32602, f"missing argument(s): {', '.join(missing)}")
    values = {"shots": "3", "format": "landscape", **{k: str(v) for k, v in args.items()}}
    values["orientation"] = "portrait" if values.get("format") == "vertical" else "landscape"
    return {"description": spec["description"],
            "messages": [{"role": "user", "content": {"type": "text", "text": spec["template"].format(**values)}}]}


# -- JSON-RPC ----------------------------------------------------------------------------------------------------
class RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def check_args(schema: dict[str, Any], args: Any) -> dict[str, Any]:
    """The arguments against the tool's schema (types, enums, bounds, required, unknown keys), with plain messages."""
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ArgError("arguments must be an object")
    props = schema.get("properties", {})
    unknown = sorted(set(args) - set(props))
    if unknown:
        raise ArgError(f"unknown argument(s): {', '.join(unknown)}; this tool takes {', '.join(props) or 'none'}")
    missing = [k for k in schema.get("required", []) if args.get(k) in (None, "", [])]
    if missing:
        raise ArgError(f"missing: {', '.join(missing)}")
    kinds = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list}
    for key, value in args.items():
        prop = props[key]
        want = prop.get("type")
        if value is None:
            continue
        ok = isinstance(value, kinds[want]) and not (want in ("integer", "number") and isinstance(value, bool))
        if not ok:
            raise ArgError(f"{key}: expected {want}")
        if "enum" in prop and value not in prop["enum"]:
            raise ArgError(f"{key}: {value!r} is not one of {', '.join(map(str, prop['enum'][:60]))}")
        if want in ("integer", "number"):
            if "minimum" in prop and value < prop["minimum"] or "maximum" in prop and value > prop["maximum"]:
                raise ArgError(f"{key}: must be between {prop.get('minimum')} and {prop.get('maximum')}")
        if want == "string":
            if len(value) > prop.get("maxLength", 10**6) or len(value.strip()) < prop.get("minLength", 0):
                raise ArgError(f"{key}: length must be {prop.get('minLength', 0)}-{prop.get('maxLength')}")
            if "pattern" in prop and not re.fullmatch(prop["pattern"], value):
                raise ArgError(f"{key}: {value!r} is not a valid {key.replace('_', ' ')}")
        if want == "array":
            if len(value) > prop.get("maxItems", 10**6) or len(value) < prop.get("minItems", 0):
                raise ArgError(f"{key}: give {prop.get('minItems', 0)}-{prop.get('maxItems')} items")
            items = prop.get("items") or {}
            item = items.get("type")
            if item and not all(isinstance(v, kinds[item]) and not isinstance(v, bool) for v in value):
                raise ArgError(f"{key}: every item must be a {item}")
            if items.get("pattern") and not all(re.fullmatch(items["pattern"], v) for v in value):
                raise ArgError(f"{key}: every item must match {items['pattern']}")
            lo, hi = items.get("minimum"), items.get("maximum")
            if any((lo is not None and v < lo) or (hi is not None and v > hi) for v in value):
                raise ArgError(f"{key}: every item must be between {lo} and {hi}")
    return args


class Server:
    """The MCP methods, transport-free: `handle(message)` answers one JSON-RPC message (or None for a notification)."""

    def __init__(self, studio: Studio, max_renders: int = DEFAULT_MAX_RENDERS, budget_file: Path | None = None):
        self.studio = studio
        self.max_renders = max_renders
        self.budget_file = Path(budget_file) if budget_file else None
        self.renders_used = self._read_used()
        self._lock = threading.Lock()
        self._sync_budget()

    def _read_used(self) -> int:
        """Renders already started by earlier processes of the same chat (an agent that starts its tools anew each turn)."""
        if not self.budget_file:
            return 0
        try:
            return max(0, int(json.loads(self.budget_file.read_text(encoding="utf-8")).get("used", 0)))
        except (OSError, ValueError, TypeError, AttributeError):
            return 0

    def _sync_budget(self) -> None:
        if self.budget_file:
            try:
                self.budget_file.write_text(json.dumps({"used": self.renders_used, "max": self.max_renders}), encoding="utf-8")
            except OSError:
                pass
        self.studio.budget = {"used": self.renders_used, "max": self.max_renders,
                              "left": max(self.max_renders - self.renders_used, 0),
                              "counts": "each render a live backend starts; Replay renders nothing and is free"}

    def _live(self) -> bool:
        try:
            return not self.studio.get("/api/status").get("backend", {}).get("locked", False)
        except StudioError:
            return True  # unknown: count it (the call itself will say what is wrong)

    def call_tool(self, name: str, args: Any) -> dict[str, Any]:
        spec = TOOLS.get(name)
        if spec is None:
            raise RpcError(-32602, f"unknown tool: {name}")
        try:
            args = check_args(spec.schema, args)
            spends = spec.renders and not (name == "approve_stills" and not args.get("reroll")) and self._live()
            if spends:
                with self._lock:
                    if self.renders_used >= self.max_renders:
                        return {"content": [text(
                            f"This session's render budget is spent ({self.max_renders} renders). Nothing was started. "
                            "Plan and review with the free tools; the person can allow more with "
                            "`openfield mcp --max-renders N`.")], "isError": True}
                    self.renders_used += 1  # held before the call, so two parallel calls cannot both pass
                    self._sync_budget()
            try:
                content = spec.run(self.studio, args)
            except BaseException:
                if spends:
                    with self._lock:
                        self.renders_used -= 1  # refused or failed to start: nothing was rendered
                        self._sync_budget()
                raise
            return {"content": content, "isError": False}
        except (ArgError, StudioError) as exc:
            return {"content": [text(with_hint(str(exc)))], "isError": True}
        except Exception as exc:  # anything else is a bug here, reported to the model, not a dead server
            return {"content": [text(f"{type(exc).__name__}: {exc}")], "isError": True}

    def dispatch(self, method: str, params: dict[str, Any]) -> Any:
        if method == "initialize":
            asked = params.get("protocolVersion")
            return {"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                    "capabilities": {"tools": {"listChanged": False}, "prompts": {"listChanged": False},
                                     "resources": {"listChanged": False, "subscribe": False}},
                    "serverInfo": {"name": SERVER_NAME, "title": "OpenField Studio", "version": __version__},
                    "instructions": INSTRUCTIONS}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [t.listing() for t in TOOLS.values()]}
        if method == "tools/call":
            return self.call_tool(params.get("name", ""), params.get("arguments"))
        if method == "prompts/list":
            return {"prompts": [{"name": n, "title": p["title"], "description": p["description"],
                                 "arguments": p["arguments"]} for n, p in PROMPTS.items()]}
        if method == "prompts/get":
            return render_prompt(params.get("name", ""), params.get("arguments") or {})
        if method == "resources/list":
            return {"resources": [{"uri": uri, **meta} for uri, meta in RESOURCES.items()]}
        if method == "resources/read":
            uri = params.get("uri", "")
            if uri == "openfield://guide/prompting":
                return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": GUIDE}]}
            if uri == "openfield://catalog":
                try:
                    cat = self.studio.get("/api/moves")
                except StudioError:
                    cat = CATALOG  # the studio is down: the catalog this code ships with
                return {"contents": [{"uri": uri, "mimeType": "application/json",
                                      "text": json.dumps(options_view(cat), ensure_ascii=False)}]}
            raise RpcError(-32002, f"resource not found: {uri}")
        if method in ("logging/setLevel", "resources/subscribe", "resources/unsubscribe"):
            return {}
        raise RpcError(-32601, f"method not found: {method}")

    def handle(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
        if "method" not in message:
            return None  # a response to something we never ask for
        if "id" not in message:
            return None  # a notification: initialized, cancelled, progress
        try:
            params = message.get("params") or {}
            if not isinstance(params, dict):
                raise RpcError(-32602, "params must be an object")
            return {"jsonrpc": "2.0", "id": message["id"], "result": self.dispatch(message["method"], params)}
        except RpcError as exc:
            return {"jsonrpc": "2.0", "id": message["id"], "error": {"code": exc.code, "message": exc.message}}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"}}


QUICK = frozenset({"initialize", "ping", "tools/list", "prompts/list", "prompts/get", "resources/list",
                   "logging/setLevel", "resources/subscribe", "resources/unsubscribe"})


def serve_stdio(server: Server, stdin: Any = None, stdout: Any = None, workers: int = 8) -> None:
    """Newline-delimited JSON-RPC on stdin/stdout. Quick methods answer on the reader thread; tool calls run in threads,
    so a ping is answered during a long wait. When the client goes away, calls not yet started are dropped (a render
    must never start for nobody)."""
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    lock = threading.Lock()

    def send(reply: dict[str, Any] | None) -> None:
        if reply is None:
            return
        data = json.dumps(reply, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        with lock:
            stdout.write(data)
            stdout.flush()

    def answer(message: Any) -> None:
        if isinstance(message, list):  # a batch (2025-03-26)
            replies = [r for r in (server.handle(m) for m in message) if r is not None]
            if replies:
                with lock:
                    stdout.write(json.dumps(replies, ensure_ascii=False).encode("utf-8") + b"\n")
                    stdout.flush()
            return
        send(server.handle(message))

    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mcp")
    try:
        for raw in iter(stdin.readline, b""):
            line = raw.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
                continue
            if isinstance(message, dict) and message.get("method") in QUICK:
                answer(message)
            else:
                pool.submit(answer, message)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)  # running calls finish; queued ones never start


def main(url: str = DEFAULT_URL, max_renders: int = DEFAULT_MAX_RENDERS, budget_file: Path | None = None) -> int:
    serve_stdio(Server(Studio(url), max_renders=max_renders, budget_file=budget_file))
    return 0
