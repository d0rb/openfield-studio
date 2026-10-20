"""Camera rig, the 35-move table and the shot compiler.

A move is compiled into a `ShotPlan`: one natural-language video prompt, an anchor plan (the
stills a keyframed move needs) and the video segments to render. Nothing here talks to ComfyUI.

Move modes (how honestly we can promise the move):
  keyframed     two or more stills define the move; LTX first-last-frame renders each pair
  prompt_only   one approved still, image-to-video, the move lives in the prompt
  experimental  prompt_only and unverified; shown under "More" in the UI
`featured` moves are promoted in the UI; `VALIDATED` lists the ones with a real, checked render.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from .safety import require_safe

SENSORS = {
    "modern_digital": "a clean modern digital cinema camera",
    "35mm_film": "35mm film with fine organic grain",
    "8mm_film": "8mm film with heavy grain, gate weave and soft edges",
    "dv_camcorder": "a 2000s DV camcorder with a soft interlaced video look",
}
LENSES = {
    "clean_sharp": "a clean, sharp spherical lens",
    "anamorphic": "an anamorphic lens with oval bokeh and horizontal flares",
    "vintage_anamorphic": "a vintage anamorphic lens with soft edges, flares and gentle falloff",
    "warm_vintage": "a warm vintage prime lens with soft contrast",
    "halation_vintage": "a vintage lens with red halation around the highlights",
}
APERTURES = {
    "f1.4": "wide open at f/1.4 with very shallow depth of field",
    "f4": "at f/4 with moderate depth of field",
    "f11": "stopped down to f/11 with deep focus",
}
LIGHTING = {
    "auto": "natural, motivated lighting",
    "soft_cross": "soft cross lighting that sculpts the subject",
    "overhead_fall": "a single overhead light falling from above",
    "contre_jour": "strong backlight (contre-jour) with a glowing rim",
    "window": "soft window light from one side",
    "practicals": "practical lights in the scene making warm pools of light",
    "silhouette": "a silhouette against a bright background",
}
SPEEDS = {"slow": "slowly", "steady": "at a steady pace", "fast": "quickly"}

GROUPS = {
    "lock": "Lock & aim",
    "dolly": "Dolly & push",
    "zoom": "Zoom & focus",
    "orbit": "Orbit & arc",
    "track": "Track & truck",
    "crane": "Crane & altitude",
    "story": "Handheld & story",
}

NEGATIVE_PROMPT = (
    "blurry, out of focus, distorted, warped or melting faces, extra limbs, jittery motion, "
    "flicker, morphing objects, text, subtitles, watermark, logo, low quality"
)
# Moves that have a real, checked render in the showcase. Updated by hand after rendering.
VALIDATED: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Pose:
    """Camera pose in rig space: subject at the origin, camera starts at z=-1 facing +z."""

    x: float = 0.0
    y: float = 0.0
    z: float = -1.0
    yaw: float = 0.0
    pitch: float = 0.0
    fov: float = 40.0


@dataclass(frozen=True)
class Move:
    id: str
    label: str
    group: str
    mode: str
    anchors: int
    phrase: str
    hold: str
    keys: tuple[Pose, ...]
    edits: tuple[str, ...] = ()
    featured: bool = False

    @property
    def validated(self) -> bool:
        return self.id in VALIDATED

    def path(self, samples: int = 24) -> list[Pose]:
        """Dense camera path for the UI preview, linearly interpolated between key poses."""
        if len(self.keys) == 1:
            return [self.keys[0]] * 2
        out: list[Pose] = []
        spans = len(self.keys) - 1
        for i in range(samples):
            t = i / (samples - 1) * spans
            a = min(int(t), spans - 1)
            f = t - a
            p, q = self.keys[a], self.keys[a + 1]
            out.append(Pose(*(getattr(p, k) + (getattr(q, k) - getattr(p, k)) * f for k in _POSE_KEYS)))
        return out

    def describe(self) -> dict[str, Any]:
        data = asdict(self)
        data["validated"] = self.validated
        data["group_label"] = GROUPS[self.group]
        data["path"] = [asdict(p) for p in self.path()]
        data["keys"] = [asdict(p) for p in self.keys]
        return data


_POSE_KEYS = ("x", "y", "z", "yaw", "pitch", "fov")


def _orbit(degrees: float, steps: int = 9) -> tuple[Pose, ...]:
    poses = []
    for i in range(steps):
        a = math.radians(degrees * i / (steps - 1))
        poses.append(Pose(x=math.sin(a), z=-math.cos(a), yaw=-math.degrees(a)))
    return tuple(poses)


def _line(dx: float = 0.0, dy: float = 0.0, dz: float = 0.0, pitch: float = 0.0) -> tuple[Pose, ...]:
    return (Pose(), Pose(x=dx, y=dy, z=-1.0 + dz, pitch=pitch))


def _turn(yaw: float = 0.0, pitch: float = 0.0) -> tuple[Pose, ...]:
    return (Pose(), Pose(yaw=yaw, pitch=pitch))


def _zoom(factor: float) -> tuple[Pose, ...]:
    return (Pose(), Pose(fov=40.0 / factor))


def _m(
    mid: str, label: str, group: str, mode: str, anchors: int, phrase: str, hold: str,
    keys: tuple[Pose, ...], edits: tuple[str, ...] = (), featured: bool = False,
) -> Move:
    # a full orbit returns to the hero frame, so its last anchor needs no edit
    expected = anchors - 2 if mid == "orbit_360" else anchors - 1
    if mode == "keyframed" and len(edits) != expected:
        raise ValueError(f"{mid}: keyframed move needs {expected} anchor edits, got {len(edits)}")
    return Move(mid, label, group, mode, anchors, phrase, hold, keys, edits, featured)


_SAME = "Same scene, subject, wardrobe, lighting and style as the reference. "
_FIXED = "fixed focal length, no zoom"

_MOVES: tuple[Move, ...] = (
    # --- lock & aim
    _m("static", "Static", "lock", "prompt_only", 1,
       "The camera is locked off on a tripod; only the subject moves.",
       "no camera movement, no zoom, no drift", (Pose(),), featured=True),
    _m("pan_left", "Pan left", "lock", "keyframed", 2,
       "The camera pans smoothly to the left on a fixed tripod, revealing more of the scene.",
       "pure rotation, camera position fixed, no tilt, no zoom", _turn(yaw=-35),
       (_SAME + "The camera has panned about 35 degrees to the left from the same position.",)),
    _m("pan_right", "Pan right", "lock", "keyframed", 2,
       "The camera pans smoothly to the right on a fixed tripod, revealing more of the scene.",
       "pure rotation, camera position fixed, no tilt, no zoom", _turn(yaw=35),
       (_SAME + "The camera has panned about 35 degrees to the right from the same position.",)),
    _m("tilt_up", "Tilt up", "lock", "keyframed", 2,
       "The camera tilts up smoothly on a fixed tripod.",
       "pure rotation, camera position fixed, no pan, no zoom", _turn(pitch=25),
       (_SAME + "The camera has tilted up about 25 degrees from the same position.",)),
    _m("tilt_down", "Tilt down", "lock", "keyframed", 2,
       "The camera tilts down smoothly on a fixed tripod.",
       "pure rotation, camera position fixed, no pan, no zoom", _turn(pitch=-25),
       (_SAME + "The camera has tilted down about 25 degrees from the same position.",)),
    _m("whip_pan", "Whip pan", "lock", "experimental", 1,
       "A fast whip pan: the camera swings sideways, motion blur streaks across the frame, then settles.",
       "one decisive swing, then a steady frame", _turn(yaw=60)),
    # --- dolly & push
    _m("dolly_in", "Dolly in", "dolly", "keyframed", 2,
       "The camera dollies in toward the subject on a smooth track, parallax shifting in the background.",
       f"physical camera travel, {_FIXED}, constant lens height", _line(dz=0.55),
       (_SAME + "The camera is now much closer to the subject, about half the original distance, "
        "framing tighter at the same angle and focal length.",), featured=True),
    _m("dolly_out", "Dolly out", "dolly", "keyframed", 2,
       "The camera dollies out, pulling back from the subject on a smooth track and revealing the setting.",
       f"physical camera travel, {_FIXED}, constant lens height", _line(dz=-0.8),
       (_SAME + "The camera has pulled back to nearly twice the distance, the subject smaller in frame "
        "with more of the environment visible, same angle and focal length.",), featured=True),
    _m("push_in", "Push in", "dolly", "keyframed", 2,
       "A slow, subtle push-in toward the point of interest.",
       f"small physical move, {_FIXED}", _line(dz=0.25),
       (_SAME + "The camera has moved slightly closer, framing a little tighter.",)),
    _m("pull_out", "Pull out", "dolly", "keyframed", 2,
       "A slow, subtle pull-out away from the point of interest.",
       f"small physical move, {_FIXED}", _line(dz=-0.3),
       (_SAME + "The camera has moved slightly farther away, framing a little wider.",)),
    _m("vertigo", "Vertigo", "dolly", "experimental", 1,
       "A dolly-zoom (vertigo effect): the camera moves back while zooming in so the subject keeps its "
       "size and the background appears to stretch.",
       "subject size constant while the background perspective changes",
       (Pose(), Pose(z=-1.6, fov=25.0))),
    # --- zoom & focus
    _m("optical_zoom_in", "Zoom in", "zoom", "keyframed", 2,
       "The lens zooms in optically from a locked tripod; the subject grows larger.",
       "locked tripod, zero camera travel, zero parallax, optical lens change only", _zoom(2.0),
       (_SAME + "Same viewpoint and perspective, framed tighter as if zoomed in 2x, no parallax change.",),
       featured=True),
    _m("optical_zoom_out", "Zoom out", "zoom", "keyframed", 2,
       "The lens zooms out optically from a locked tripod, revealing more of the frame.",
       "locked tripod, zero camera travel, zero parallax, optical lens change only", _zoom(0.6),
       (_SAME + "Same viewpoint and perspective, framed wider as if zoomed out, no parallax change.",)),
    _m("rack_focus", "Rack focus", "zoom", "experimental", 1,
       "Focus pulls from the foreground to the subject; the sharp plane shifts and the bokeh changes.",
       "camera still, only the focus plane moves", (Pose(),)),
    # --- orbit & arc
    _m("orbit_90", "Orbit 90", "orbit", "keyframed", 2,
       "The camera orbits 90 degrees around the subject at constant distance, the subject staying "
       "centred while the background rotates behind it.",
       "constant radius, constant height, subject remains centred, no subject spin", _orbit(90),
       (_SAME + "The camera has orbited 90 degrees around the subject to its right, seeing it in profile "
        "at the same distance and height, the subject centred.",), featured=True),
    _m("orbit_180", "Orbit 180", "orbit", "keyframed", 3,
       "The camera orbits 180 degrees around the subject at constant distance, the subject staying "
       "centred while the background rotates behind it.",
       "constant radius, constant height, subject remains centred, no subject spin", _orbit(180),
       (_SAME + "The camera has orbited 90 degrees around the subject to its right, seeing it in profile.",
        _SAME + "The camera has orbited 180 degrees around the subject, now seeing it from behind."),
       featured=True),
    _m("orbit_360", "Orbit 360", "orbit", "keyframed", 5,
       "The camera makes a full 360 degree orbit around the subject at constant distance, the subject "
       "staying centred while the background rotates behind it.",
       "constant radius, constant height, subject remains centred, no subject spin", _orbit(360, 17),
       (_SAME + "The camera has orbited 90 degrees around the subject to its right, seeing it in profile.",
        _SAME + "The camera has orbited 180 degrees around the subject, now seeing it from behind.",
        _SAME + "The camera has orbited 270 degrees around the subject, seeing its left profile.")),
    _m("arc_left", "Arc left", "orbit", "keyframed", 2,
       "The camera arcs to the left around the subject, a gentle curved move of about 40 degrees.",
       "constant distance, subject remains in frame, no zoom", _orbit(-40, 5),
       (_SAME + "The camera has arced about 40 degrees to the left around the subject at the same distance.",),
       featured=True),
    _m("arc_right", "Arc right", "orbit", "keyframed", 2,
       "The camera arcs to the right around the subject, a gentle curved move of about 40 degrees.",
       "constant distance, subject remains in frame, no zoom", _orbit(40, 5),
       (_SAME + "The camera has arced about 40 degrees to the right around the subject at the same distance.",),
       featured=True),
    # --- track & truck
    _m("track_left", "Track left", "track", "keyframed", 2,
       "The camera tracks sideways to the left, parallel to the subject at constant distance, the "
       "background sliding behind it.",
       f"lateral travel only, constant distance, {_FIXED}", _line(dx=-0.7),
       (_SAME + "The camera has moved sideways to the left by about one subject-width, parallel to "
        "the subject, same distance and angle.",), featured=True),
    _m("track_right", "Track right", "track", "keyframed", 2,
       "The camera tracks sideways to the right, parallel to the subject at constant distance, the "
       "background sliding behind it.",
       f"lateral travel only, constant distance, {_FIXED}", _line(dx=0.7),
       (_SAME + "The camera has moved sideways to the right by about one subject-width, parallel to "
        "the subject, same distance and angle.",), featured=True),
    _m("truck_left", "Truck left", "track", "keyframed", 2,
       "The camera trucks left without rotating, sliding past the scene.",
       f"lateral travel, no rotation, {_FIXED}", _line(dx=-0.5),
       (_SAME + "The camera has slid left without rotating, the subject now toward the right of frame.",)),
    _m("truck_right", "Truck right", "track", "keyframed", 2,
       "The camera trucks right without rotating, sliding past the scene.",
       f"lateral travel, no rotation, {_FIXED}", _line(dx=0.5),
       (_SAME + "The camera has slid right without rotating, the subject now toward the left of frame.",)),
    # --- crane & altitude
    _m("crane_up", "Crane up", "crane", "keyframed", 2,
       "The camera cranes upward and tilts down slightly to keep the subject framed, rising smoothly.",
       f"vertical travel with a slight tilt, {_FIXED}", _line(dy=0.8, dz=-0.2, pitch=-20),
       (_SAME + "The camera is now raised about two metres higher, looking down at a steeper angle "
        "with more of the ground visible.",), featured=True),
    _m("crane_down", "Crane down", "crane", "keyframed", 2,
       "The camera cranes downward from a high vantage toward the subject, settling at eye level.",
       f"vertical travel with a slight tilt, {_FIXED}", (Pose(y=0.8, z=-1.2, pitch=-20), Pose()),
       (_SAME + "The camera is now lower, at eye level, close to the subject.",), featured=True),
    _m("pedestal_up", "Pedestal up", "crane", "keyframed", 2,
       "The camera rises straight up without tilting, the frame lifting away from the subject.",
       f"pure vertical travel, no tilt, {_FIXED}", _line(dy=0.5),
       (_SAME + "The camera has risen straight up without tilting, the subject lower in frame.",)),
    _m("pedestal_down", "Pedestal down", "crane", "keyframed", 2,
       "The camera sinks straight down without tilting, the subject rising in the frame.",
       f"pure vertical travel, no tilt, {_FIXED}", _line(dy=-0.4),
       (_SAME + "The camera has dropped straight down without tilting, the subject higher in frame.",)),
    _m("top_down", "Top down", "crane", "experimental", 1,
       "An overhead top-down view looking straight down at the scene.",
       "camera directly above, perpendicular to the ground", (Pose(y=1.0, z=0.0, pitch=-90),)),
    _m("low_angle", "Low angle", "crane", "experimental", 1,
       "A low-angle shot from near the ground looking up at the subject, making it feel imposing.",
       "camera near the floor, tilted up, no movement", (Pose(y=-0.4, pitch=20),)),
    _m("helicopter", "Helicopter", "crane", "experimental", 1,
       "An aerial helicopter shot: the camera flies in a wide sweeping arc, rising and circling.",
       "large smooth arc, gradual rise, steady horizon", (*_orbit(120, 7),)),
    # --- handheld & story
    _m("handheld", "Handheld", "story", "prompt_only", 1,
       "Handheld camera with natural, subtle shake and small reframing, a documentary feel.",
       "gentle shake only, no large camera moves", (Pose(),)),
    _m("fpv_drone", "FPV drone", "story", "experimental", 1,
       "An FPV drone flight: fast dives and swoops through the scene with sharp banked turns.",
       "continuous fast flight, no cuts", (*_orbit(200, 9),)),
    _m("robot_arm", "Robot arm", "story", "experimental", 1,
       "A robotic motion-control arm: a precise, repeatable compound move, perfectly smooth.",
       "mechanically smooth path, no shake", (Pose(), Pose(x=0.4, y=0.2, z=-0.8, yaw=-15))),
    _m("over_shoulder", "Over the shoulder", "story", "prompt_only", 1,
       "An over-the-shoulder shot from just behind a person, looking toward the subject.",
       "foreground shoulder softly out of focus, no camera movement", (Pose(x=0.2, y=0.1, z=-1.1),)),
    _m("reveal", "Reveal", "story", "experimental", 1,
       "The camera moves past a foreground element to reveal the subject.",
       "foreground wipes across the lens, then the subject is revealed", _line(dx=0.5, dz=0.2)),
)

MOVES: dict[str, Move] = {m.id: m for m in _MOVES}
assert len(MOVES) == 35, f"expected 35 moves, found {len(MOVES)}"


def get_move(move_id: str) -> Move:
    try:
        return MOVES[move_id]
    except KeyError:
        raise ValueError(f"unsupported movement: {move_id}") from None


# One shot, in seconds. The LTX workflows' duration slots cap at the same number (a test keeps them equal),
# so a rig that passes here can never be refused by a template after the stills are already paid for.
MIN_DURATION_SECONDS = 2
MAX_DURATION_SECONDS = 10
MIN_FOCAL_MM = 8
MAX_FOCAL_MM = 200


@dataclass(frozen=True)
class CameraRig:
    sensor: str = "modern_digital"
    lens: str = "clean_sharp"
    focal_length_mm: int = 35
    aperture: str = "f4"
    lighting: str = "soft_cross"
    movement: str = "dolly_in"
    duration_seconds: int = 5
    speed: str = "steady"

    def validate(self) -> None:
        for value, table, name in (
            (self.sensor, SENSORS, "sensor"), (self.lens, LENSES, "lens"),
            (self.aperture, APERTURES, "aperture"), (self.lighting, LIGHTING, "lighting"),
            (self.speed, SPEEDS, "speed"),
        ):
            if value not in table:
                raise ValueError(f"unsupported {name}: {value}")
        get_move(self.movement)
        if not MIN_FOCAL_MM <= self.focal_length_mm <= MAX_FOCAL_MM:
            raise ValueError(f"focal_length_mm must be between {MIN_FOCAL_MM} and {MAX_FOCAL_MM}")
        if not MIN_DURATION_SECONDS <= self.duration_seconds <= MAX_DURATION_SECONDS:
            raise ValueError(
                f"duration_seconds must be between {MIN_DURATION_SECONDS} and {MAX_DURATION_SECONDS}")


@dataclass(frozen=True)
class AnchorSpec:
    index: int
    role: str  # "hero" | "edit" | "repeat_hero"
    edit_prompt: str | None = None


@dataclass(frozen=True)
class SegmentSpec:
    index: int
    start_anchor: int
    end_anchor: int | None
    seconds: int
    template: str  # "ltx25_flf2v" | "ltx25_i2v"


@dataclass(frozen=True)
class ShotPlan:
    rig: CameraRig
    move_id: str
    mode: str
    prompt: str
    negative: str
    anchors: tuple[AnchorSpec, ...]
    segments: tuple[SegmentSpec, ...]
    total_seconds: int
    notes: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _focal_word(mm: int) -> str:
    for limit, word in ((24, "ultra-wide"), (35, "wide"), (70, "natural"), (135, "short telephoto")):
        if mm < limit:
            return word
    return "telephoto"


def compile_prompt(rig: CameraRig, subject: str, audio: str | None = None) -> str:
    """One flowing paragraph in the style LTX responds to: scene, look, camera, constraint, sound."""
    rig.validate()
    move = get_move(rig.movement)
    look = (
        f"Shot on {SENSORS[rig.sensor]} with {LENSES[rig.lens]}, {rig.focal_length_mm}mm "
        f"({_focal_word(rig.focal_length_mm)}), {APERTURES[rig.aperture]}; {LIGHTING[rig.lighting]}."
    )
    move_text = move.phrase if move.id in {"static", "handheld", "whip_pan"} else (
        f"{move.phrase.rstrip('.')}, moving {SPEEDS[rig.speed]}."
    )
    parts = [subject.strip().rstrip(".") + ".", look, move_text, f"Constraint: {move.hold}."]
    if audio and audio.strip():
        parts.append(f"Sound: {audio.strip().rstrip('.')}.")
    return " ".join(parts)


def compile_still_prompt(rig: CameraRig, subject: str) -> str:
    """Prompt for the hero still: the rig's look, with no motion words."""
    rig.validate()
    look = (
        f"Photographed on {SENSORS[rig.sensor]} with {LENSES[rig.lens]}, {rig.focal_length_mm}mm "
        f"({_focal_word(rig.focal_length_mm)}), {APERTURES[rig.aperture]}; {LIGHTING[rig.lighting]}."
    )
    return f"{subject.strip().rstrip('.')}. {look} Cinematic still frame, no text, no watermark."


def compile_portrait_prompt(description: str) -> str:
    """A plain head-and-shoulders portrait: the clearest reference image for the identity check."""
    description = " ".join(description.split()).rstrip(".")
    if not 3 <= len(description) <= 400:
        raise ValueError("describe the character in 3 to 400 characters")
    require_safe(description)
    return (f"A photographic head-and-shoulders portrait of {description}. The face is fully visible and "
            "evenly lit, looking toward the camera with a relaxed neutral expression, in sharp focus, "
            "against a plain, softly out-of-focus background. Natural skin texture, realistic proportions. "
            "No text, no watermark.")


def compile_reshoot_prompt(character: str, background: str | None = None) -> str:
    """The two-part caption Wan Animate 2 is prompted with: who the character is, and the setting."""
    character = " ".join(character.split()).rstrip(".")
    background = " ".join((background or "").split()).rstrip(".") or "a plain, softly lit studio backdrop"
    if not 3 <= len(character) <= 400 or len(background) > 400:
        raise ValueError("describe the new character in 3 to 400 characters (and the background in at most 400)")
    require_safe(character, background)
    return f"Character Description: {character}\nBackground description: {background}"


def compile_shot(rig: CameraRig, subject: str, audio: str | None = None, *,
                 prompt_only: bool = False) -> ShotPlan:
    """Turn a rig and a subject into prompts, an anchor plan and the segments to render.

    `prompt_only` renders a keyframed move from one still and a camera instruction instead of planning
    anchor stills: cheaper, with no approvals, and the baseline keyframing is compared against.
    """
    rig.validate()
    require_safe(subject, audio)
    move = get_move(rig.movement)
    notes: list[str] = []
    anchors = [AnchorSpec(0, "hero")]
    segments: list[SegmentSpec] = []
    mode = move.mode
    if prompt_only and mode == "keyframed":
        mode = "prompt_only"
        notes.append("quick mode: one still and a camera instruction, no anchor stills")
    if mode == "keyframed":
        for i in range(1, move.anchors):
            if move.id == "orbit_360" and i == move.anchors - 1:
                anchors.append(AnchorSpec(i, "repeat_hero"))
            else:
                anchors.append(AnchorSpec(i, "edit", move.edits[i - 1]))
        count = move.anchors - 1
        per = max(2, round(rig.duration_seconds / count))
        total = per * count
        if total != rig.duration_seconds:
            notes.append(f"duration {rig.duration_seconds}s becomes {total}s ({count} segments of {per}s)")
        segments = [SegmentSpec(i, i, i + 1, per, "ltx25_flf2v") for i in range(count)]
    else:
        total = rig.duration_seconds
        segments = [SegmentSpec(0, 0, None, total, "ltx25_i2v")]
    if move.mode == "experimental":
        notes.append("experimental move: prompt-only, not validated with a real render")
    return ShotPlan(
        rig=rig, move_id=move.id, mode=mode,
        prompt=compile_prompt(rig, subject, audio), negative=NEGATIVE_PROMPT,
        anchors=tuple(anchors), segments=tuple(segments), total_seconds=total, notes=tuple(notes),
    )


def catalog() -> dict[str, Any]:
    """Everything the UI needs to render the rig console and the Move Pad."""
    return {
        "groups": [{"id": gid, "label": label} for gid, label in GROUPS.items()],
        "moves": [m.describe() for m in MOVES.values()],
        "options": {
            "sensor": list(SENSORS), "lens": list(LENSES), "aperture": list(APERTURES),
            "lighting": list(LIGHTING), "speed": list(SPEEDS),
        },
        "defaults": asdict(CameraRig()),
        "limits": {"duration_seconds": [MIN_DURATION_SECONDS, MAX_DURATION_SECONDS],
                   "focal_length_mm": [MIN_FOCAL_MM, MAX_FOCAL_MM]},
    }
