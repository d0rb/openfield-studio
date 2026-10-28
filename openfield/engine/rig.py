"""Camera rig, the 49-move table and the shot compiler.

A move is compiled into a `ShotPlan`: one natural-language video prompt, an anchor plan (the
stills a keyframed move needs) and the video segments to render. Nothing here talks to ComfyUI.

Move modes (how honestly we can promise the move):
  keyframed     two or more stills define the move; LTX first-last-frame renders each pair
  prompt_only   one approved still, image-to-video, the move lives in the prompt
  experimental  prompt_only, with a phrase that is still a hypothesis; the plan says so, and it lives under "More"
A move of either mode is labelled tested only once it is in VALIDATED.
`featured` moves are promoted in the UI; `VALIDATED` lists the ones with a real, checked render.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from . import quality
from .safety import GARMENT, WORD, WORN, require_safe

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
# Effect presets: one sentence added to the LTX shot prompt. Prompt-only, so a preset is "experimental" until a real
# render of it has been checked by eye (VALIDATED_EFFECTS), the same rule the moves follow.
EFFECTS = {
    "none": "",
    "rain": "Heavy rain falls across the whole frame, drops streaking through the lamplight and beading on hair and cloth, wet ground catching the reflections.",
    "lightning": "A flash of lightning lights the whole scene for an instant, then the glow fades.",
    "time_freeze": "The world slows and freezes mid-motion while the camera keeps moving.",
    "dust": "Dust and embers drift through the beams of light.",
    "fog": "A low fog rolls in from the distance and drifts across the ground, softening the far trees and hills into "
           "layers of grey while the subject stays clear and sharp in the foreground.",
    "slow_motion": "Filmed in slow motion at a very high frame rate: every movement drifts, hair, cloth and droplets float through the air.",
}
VALIDATED_EFFECTS: frozenset[str] = frozenset({"age", "bloom", "bts", "clones", "comic", "dust", "flood", "fog", "freeze", "gold", "ignite", "lightning", "melt", "night", "painting", "rain", "ruin", "slow_motion", "snowfall", "time_freeze", "vanish"})  # checked by eye: Oct 21 (rain, lightning, dust), Oct 22 (bloom, freeze, gold, ignite, night), Oct 23 (the ten session-6 transformations and slow motion), Oct 24 (fog, with new positive words: the wolf stays clear), Oct 25 (ruin: the hall decays round the piano and nothing drifts through the frame)
FROM_IMAGE_TESTED = True  # "Start from my image": checked by eye on the Oct 22 render (from-image-mara)

# A line of dialogue: LTX 2.5 writes the speech with the picture when the prompt quotes it (the official prompting
# guide: wrap spoken lines in quotation marks, name the delivery, state the language when it matters). Prompt words
# only, no new node; the flag flips once a render with a spoken line has been checked by ear and eye.
DIALOGUE_TESTED = True  # checked by eye and ear on the Oct 22 renders (dlg-*)
FACE_ONLY_TESTED = True  # Oct 23: v1b-reshoot-face-noor-pier (Noor's face on the pier take) holds by eye, identity 0.84 / 0.77
DUB_TESTED = True  # Oct 23: the Spanish and French dubs of dlg-mara-calm hold by eye, and Whisper hears the lines (v1-dub-mara-*)
LINE_MAX = 200
LANGUAGE_MAX = 40
DELIVERIES = {
    "natural": "in a natural speaking voice",
    "calm": "in a calm, low voice, unhurried",
    "whisper": "in a whisper",
    "tender": "softly, with warmth",
    "urgent": "quickly, with urgency",
    "shout": "shouting",
    "radio": "in a distorted radio voice",
    "announcer": "in an energetic announcer's voice",
}

# What happens in the shot: its own sentence in the video prompt, right after the subject, and never in the hero still's
# prompt, so the first frame shows the moment before the action and the video still has the action to perform.
ACTION_MAX = 300


# Transitions: one LTX 2.5 render from the last frame of one take to the first frame of another (the same
# first-last-frame path the keyframed moves use), played between the two takes. `phrase` opens the bridge's prompt.
# Prompt words only, so a style is untested until a real render of it was checked by eye (TRANSITIONS_TESTED).
@dataclass(frozen=True)
class TransitionStyle:
    label: str
    phrase: str


TRANSITIONS: dict[str, TransitionStyle] = {
    "morph": TransitionStyle(
        "Morph",
        "One continuous shot with no cut: the first scene physically transforms into the second, its shapes stretching, "
        "bending and reshaping into the new forms as the camera keeps moving, the outline of the first figure flowing "
        "into the outline of the second while the colours shift."),
    "whip": TransitionStyle(
        "Whip pan",
        "A whip pan: the camera whips sideways so fast that the whole frame dissolves into streaks of motion blur, and as "
        "the blur clears it settles on the second scene, one continuous camera move with no cut."),
    "push": TransitionStyle(
        "Push through",
        "The camera pushes forward through the first scene and comes out into the second, one continuous forward "
        "move with no cut."),
    "match": TransitionStyle(
        "Match cut",
        "One continuous shot: the main shape at the centre of the frame keeps its place and outline while everything "
        "around it dissolves and re-forms into the second scene, until the shape itself becomes the second scene's."),
}
TRANSITION_DEFAULT = "push"  # the style that held on a real render (Oct 23)
TRANSITION_SECONDS = (2, 3, 4)  # LTX 2.5 renders at least 2 s (49 frames); past 4 s a bridge stops reading as a transition
TRANSITION_JOIN_FADE = 0.12  # seconds of dissolve at each join: the frames there match, so it only smooths the sound
TRANSITION_SCENE_MAX = 240  # characters of each take's description quoted in the bridge prompt
TRANSITION_IDEA_MAX = 240  # characters of the optional idea: how the first shot becomes the second
TRANSITIONS_TESTED: frozenset[str] = frozenset({"push"})  # Oct 23: the push bridge v1c-tr-rooftop-dragon-push holds by eye; morph, whip and match were rendered and still cut at the landing


# Extend: continue a finished take from its last frame with LTX 2.5 image-to-video. The take plays the
# original clip, then the new seconds, joined with a short crossfade.
EXTEND_SECONDS = (3, 5)
EXTEND_TESTED = True  # Oct 23: two extensions (v5-extend-lava, v5-extend-ines-canal) joined without a jump by eye
EXTEND_PROMPT_MAX = 1600  # characters of the shot's own prompt kept in the extension prompt
EXTEND_LEAD = "The same shot continues without a cut from where it ended:"  # opens every extension prompt


def compile_extend_prompt(shot_prompt: str | None) -> str:
    """The extension prompt: the shot continues from where it ended, then the shot's own prompt (bounded)."""
    words = " ".join((shot_prompt or "").split())
    while words.startswith(EXTEND_LEAD):  # an extension's own prompt never nests inside the next one
        words = words[len(EXTEND_LEAD):].lstrip()
    words = words[:EXTEND_PROMPT_MAX].rstrip(" ,;:")
    text = f"{EXTEND_LEAD} {words or 'the scene.'}"
    require_safe(text)
    return text


def _scene_sentence(text: str | None) -> str:
    words = " ".join((text or "").split())[:TRANSITION_SCENE_MAX].rstrip(" ,;:")
    if not words:
        return "the scene."
    return words if words.endswith((".", "!", "?")) else words + "."


def transition_idea(idea: str | None) -> str | None:
    """The optional idea, tidied and checked: 3 to TRANSITION_IDEA_MAX characters; None when not given."""
    words = " ".join((idea or "").split()).rstrip(".")
    if not words:
        return None
    if not 3 <= len(words) <= TRANSITION_IDEA_MAX:
        raise ValueError(f"describe how the shot gets there in 3 to {TRANSITION_IDEA_MAX} characters")
    require_safe(words)
    return words


def compile_transition_prompt(style: str, first: str | None, second: str | None, idea: str | None = None) -> str:
    """The bridge's prompt: the style's motion, the idea of how one shot becomes the other (optional), the shot it
    leaves and the shot it lands on, one unbroken sound."""
    if style not in TRANSITIONS:
        raise ValueError(f"unknown transition style: {style!r}")
    idea = transition_idea(idea)
    how = f"How it gets there: {idea}. " if idea else ""
    text = (f"{TRANSITIONS[style].phrase} {how}It starts on the last moment of the first shot: {_scene_sentence(first)} "
            f"It lands on the opening of the second shot: {_scene_sentence(second)} "
            "The sound carries through the transition without a break.")
    require_safe(text)
    return text


# Upscale: a finished take enlarged by Real-ESRGAN x4plus (the official "Video Upscale: Real-ESRGAN" graph) and resized to
# the target's long side, the take's own shape kept. A GAN upscaler redraws fine detail from each frame; it adds nothing to
# the shot. No video model runs and nothing here is a prompt, so the open question is how it looks on real takes: the flag
# flips once a real render of it was checked by eye (UPSCALE_TESTED), the rule the moves and the bridges follow.
UPSCALE_TARGETS: dict[str, int] = {"2k": 2560, "4k": 3840}  # id -> pixels on the take's long side
UPSCALE_MODEL_SCALE = 4  # RealESRGAN_x4plus always enlarges 4x; the graph's last node lands that on the target
UPSCALE_TESTED = True  # checked by eye against the source: a Draft take to 2K on Oct 23 (v6-upscale-draft-2k) and to 4K
# on Oct 25 (r11-up-4k, 3840 x 2194, the helicopter take)


# Transformations: keyframed effects. The hero still is edited into the END STATE (one Qwen-Image edit, approved like
# any still) and LTX renders the change between the two with sound: the first-last-frame path applied to the scene
# instead of the camera. `phrase` is the motion sentence in the shot prompt, `edit` the instruction for the end-state
# still (the pipeline adds its own keep-the-framing sentence). The same honesty rule as the moves: a transformation is
# tested only once a real render of it was checked by eye (VALIDATED_EFFECTS).
@dataclass(frozen=True)
class Transformation:
    label: str
    phrase: str
    edit: str
    keeps_identity: bool = True  # False: the face is meant to change, so the identity check is skipped on that still and shot
    reframes: bool = False  # True: the end state may widen the framing, so the pipeline keeps the subject and set but not the framing
    skip_reason: str = "the transformation changes the face on purpose"  # what the receipt says when the face check is skipped


TRANSFORMATIONS: dict[str, Transformation] = {
    "ignite": Transformation(
        "Ignite",
        "Flames catch at the edges of the frame and spread across the scene, embers drifting upward and the light turning "
        "orange, until fire fills the shot, the crackle of the fire rising.",
        "Set the scene ablaze: flames spreading across the ground and surfaces, smoke and embers in the air, everything lit by orange firelight."),
    "freeze": Transformation(
        "Freeze",
        "Frost creeps across every surface, ice crystals spreading and thickening until the whole scene is rimed white and "
        "still, the air turning cold and blue, with the faint crackle of forming ice.",
        "Cover the scene in frost and ice: surfaces rimed white, icicles forming, a cold blue light."),
    "gold": Transformation(
        "Gold statue",
        "Gold spreads over the subject from the feet upward, skin and cloth hardening into polished metal until a gold "
        "statue stands where the subject was, with a low metallic hum.",
        "Turn the subject into a solid gold statue of polished metal catching the light, while the setting stays exactly as it is.",
        keeps_identity=False),
    "bloom": Transformation(
        "Bloom",
        "Vines and blossoms sprout and climb across the scene in fast motion, moss spreading and flowers opening until "
        "greenery frames everything, with the rustle of leaves.",
        "Overgrow the scene with vines, moss and flowers climbing every surface and framing the subject."),
    "night": Transformation(
        "Day to night",
        "Daylight drains away as dusk falls and night arrives, lamps and windows flickering on one by one until the scene "
        "is lit only by their glow, with evening sounds settling in.",
        "Change the time of day to night: a dark sky, the scene lit by lamps, windows and practical lights, long shadows."),
    "age": Transformation(
        "Age",
        "Years pass over the person in a smooth time-lapse: hair greys, lines deepen and the posture settles while the "
        "setting stays still, with a slow quiet breath.",
        "Age the person by about forty years: grey hair, deep lines and aged skin, the same clothes and setting.",
        keeps_identity=False),
    "snowfall": Transformation(
        "Snowfall",
        "Snow begins to fall, light at first and then thick, settling on the ground and on the subject's shoulders until "
        "the scene turns white, with the hush of falling snow.",
        "Make it snow: falling snowflakes, snow settled on the ground, on surfaces and on shoulders, a cold overcast light."),
    "ruin": Transformation(
        "Ruin",
        "Decades pass in a time-lapse over the same scene: paint peels, surfaces crack and stain, rust spreads, dust "
        "settles and plants creep into the cracks until it stands weathered and abandoned, the camera holding steady.",
        "Let decades pass over the scene: peeling paint, cracked and weathered surfaces, rust and dust, plants growing in the cracks."),
    "bts": Transformation(
        "Behind the scenes",
        "The camera pulls back and the scene is revealed as a film set: lights on stands, a camera on a dolly track, a boom microphone and a crew at work around the subject, with the murmur of the set.",
        "Widen the view to reveal that this scene is being filmed on a film set: the same subject and set in the centre, surrounded by film lights on stands, a camera on a dolly track, a boom microphone and crew members at work.",
        reframes=True),
    "vanish": Transformation(
        "Vanish",
        "The subject breaks apart into drifting particles that scatter on the wind until they are gone, leaving the scene empty, with a soft rushing sound.",
        "Remove the person from the scene completely, leaving the same empty setting, with a few glowing particles drifting where they stood.",
        keeps_identity=False, skip_reason="the person leaves the frame on purpose"),
    "clones": Transformation(
        "Clones",
        "Copies of the subject step out of them one after another until a crowd of identical people fills the scene, with the shuffle of many footsteps.",
        "Fill the scene with many identical copies of the same person in the same clothes, standing at different distances across the setting.",
        keeps_identity=False, skip_reason="the frame fills with copies of the person on purpose, so there is no single face to check"),
    "comic": Transformation(
        "Comic book",
        "Ink outlines trace every shape and the colours flatten until the scene becomes a hand-drawn comic panel, halftone dots spreading across the frame, with the scratch of a pen.",
        "Redraw the scene as a comic-book panel: bold ink outlines, flat colours and halftone dots, the same composition.",
        keeps_identity=False, skip_reason="the scene is redrawn as a comic panel, so a photographic face check does not apply"),
    "painting": Transformation(
        "Oil painting",
        "Brushstrokes sweep across the scene until it becomes a classical oil painting, thick paint and canvas texture covering every surface, with a soft brushing sound.",
        "Turn the scene into a classical oil painting on canvas: visible brushstrokes, rich colours and the same composition.",
        keeps_identity=False, skip_reason="the scene is repainted in oils, so a photographic face check does not apply"),
    "melt": Transformation(
        "Melt",
        "The setting softens and melts around the subject, surfaces drooping and dripping like warm wax, with a slow, thick dripping sound.",
        "Make the setting melt like warm wax: walls, objects and surfaces drooping and dripping, while the person stays exactly as they are."),
    "flood": Transformation(
        "Flood",
        "Water rises and floods the scene until everything is underwater, light rippling across every surface and bubbles drifting up, the sound turning muffled.",
        "Put the whole scene underwater: blue-green water, rippling light, floating particles and rising bubbles, the same setting and subject."),
}
EFFECT_IDS: tuple[str, ...] = (*EFFECTS, *TRANSFORMATIONS)  # everything `effect` may be set to


# Angles: where the camera stands when the shot starts. The approved hero is re-shot from that position (one Qwen-Image
# edit, approved like any still, as the shot's first frame) and the move runs from there. The grid is the one creators
# know: 8 azimuths x 4 heights x 3 distances. An angle id is "<azimuth>/<height>/<distance>"; the default is the hero as
# shot, which adds nothing to a recipe. The directive carries the English stop and, for a rotation or a height change, the
# Chinese camera instruction from Qwen's own edit examples, so the camera moves rather than the subject turning.
@dataclass(frozen=True)
class AngleStop:
    label: str
    value: float  # degrees for an azimuth or a height, a distance factor for a distance
    phrase: str
    zh: str = ""


AZIMUTHS: dict[str, AngleStop] = {
    "front": AngleStop("Front", 0, "the front view"),
    "front_right": AngleStop("Front-right quarter", 45, "the front-right quarter view, the camera rotated 45 degrees to the right", "将镜头向右旋转45度"),
    "right": AngleStop("Right side", 90, "the right side view, the camera rotated 90 degrees to the right, the subject in profile", "将镜头向右旋转90度"),
    "back_right": AngleStop("Back-right quarter", 135, "the back-right quarter view, the camera rotated 135 degrees to the right", "将镜头向右旋转135度"),
    "back": AngleStop("Back", 180, "the back view, the camera rotated 180 degrees to see the subject from behind", "将镜头旋转180度到背面"),
    "back_left": AngleStop("Back-left quarter", 225, "the back-left quarter view, the camera rotated 135 degrees to the left", "将镜头向左旋转135度"),
    "left": AngleStop("Left side", 270, "the left side view, the camera rotated 90 degrees to the left, the subject in profile", "将镜头向左旋转90度"),
    "front_left": AngleStop("Front-left quarter", 315, "the front-left quarter view, the camera rotated 45 degrees to the left", "将镜头向左旋转45度"),
}
ELEVATIONS: dict[str, AngleStop] = {
    "low": AngleStop("Low angle", -30, "a low-angle shot with the camera below eye level looking up", "切换到低角度"),
    "eye": AngleStop("Eye level", 0, "an eye-level shot"),
    "elevated": AngleStop("Elevated", 30, "an elevated shot with the camera above eye level looking slightly down", "切换到略高于平视的角度"),
    "high": AngleStop("High angle", 60, "a high-angle shot with the camera well above the subject looking steeply down", "切换到俯视视角"),
}
DISTANCES: dict[str, AngleStop] = {
    "close": AngleStop("Close-up", 0.6, "a close-up, nearer than before", "特写"),
    "medium": AngleStop("Medium", 1.0, "a medium shot at the same distance"),
    "wide": AngleStop("Wide", 1.8, "a wide shot from farther away, more of the setting in frame", "远景"),
}
ANGLE_DEFAULT = "front/eye/medium"
ANGLES_TESTED: frozenset[str] = frozenset({"back/elevated/close", "back/elevated/medium", "back/elevated/wide", "back/eye/close", "back/eye/medium", "back/eye/wide", "back/high/close", "back/high/medium", "back/high/wide", "back/low/close", "back/low/medium", "back/low/wide", "back_left/elevated/medium", "back_left/elevated/wide", "back_left/eye/medium", "back_left/eye/wide", "back_left/high/close", "back_left/high/medium", "back_left/high/wide", "back_left/low/medium", "back_left/low/wide", "back_right/elevated/medium", "back_right/elevated/wide", "back_right/eye/medium", "back_right/high/close", "back_right/high/medium", "back_right/high/wide", "back_right/low/medium", "back_right/low/wide", "front/elevated/close", "front/elevated/medium", "front/elevated/wide", "front/eye/close", "front/eye/wide", "front/high/close", "front/high/medium", "front/high/wide", "front/low/close", "front/low/medium", "front_left/eye/medium", "front_right/eye/close", "front_right/eye/medium", "left/elevated/close", "left/elevated/medium", "left/elevated/wide", "left/eye/close", "left/eye/medium", "left/eye/wide", "left/high/close", "left/high/medium", "left/high/wide", "left/low/close", "left/low/medium", "left/low/wide", "right/elevated/close", "right/elevated/medium", "right/elevated/wide", "right/eye/close", "right/eye/medium", "right/high/close", "right/high/medium", "right/high/wide", "right/low/close", "right/low/medium", "right/low/wide"})
# The twelve of Oct 22 were each checked on a still and a take (angle-oskar-*). On Oct 25 (GPU session 9) every other
# position was re-shot as a still from the same hero and checked by eye and by two vision models; those whose still
# reads as its label joined (docs/media/angles-grid.jpg shows them all). The front quarters kept him facing the
# lens and stay out, as do the back-quarter close-ups that read as a profile; back_left/eye/medium was re-shot as a
# still on Oct 25 after its take (a tripod walked in) left the bundle.
_ANGLE_KEEP = ("Move only the camera around the subject: the subject keeps the same pose and facing direction, the same "
               "clothes, light and setting, and nothing new appears.")
_ANGLE_KEEP_ZH = "只移动镜头，主体保持原来的姿势和朝向不变，不新增物体。"


def parse_angle(angle: str) -> tuple[str, str, str]:
    parts = tuple((angle or "").split("/"))
    if len(parts) != 3 or parts[0] not in AZIMUTHS or parts[1] not in ELEVATIONS or parts[2] not in DISTANCES:
        raise ValueError(f"unsupported angle: {angle}")
    return parts  # type: ignore[return-value]


def describe_angle(angle: str) -> str:
    az, el, dist = parse_angle(angle)
    return f"{AZIMUTHS[az].label} · {ELEVATIONS[el].label} · {DISTANCES[dist].label}"


def angle_geometry(angle: str) -> dict[str, float]:
    az, el, dist = parse_angle(angle)
    return {"azimuth_deg": AZIMUTHS[az].value, "elevation_deg": ELEVATIONS[el].value, "distance": DISTANCES[dist].value}


def angle_directive(angle: str) -> str:
    """The edit instruction that re-shoots the hero from an angle: the stop in English, the Chinese camera instruction
    where one exists, and the sentence that keeps the subject from turning instead of the camera."""
    az, el, dist = parse_angle(angle)
    text = f"Re-shoot the same scene from {AZIMUTHS[az].phrase}, {ELEVATIONS[el].phrase}, as {DISTANCES[dist].phrase}. {_ANGLE_KEEP}"
    zh = [stop.zh for stop in (AZIMUTHS[az], ELEVATIONS[el], DISTANCES[dist]) if stop.zh]
    return f"{text} {'，'.join(zh)}。{_ANGLE_KEEP_ZH}" if zh else text


# Shots: one still re-shot as a board of nine setups, each a position the angle dials offer and each one of the
# positions checked by eye on the angle sheet (ANGLES_TESTED). The board as a feature is untested until one has
# rendered and been checked (SHOTS_TESTED). The order reads as a 3 x 3 sheet.
SHOTS_BOARD: tuple[tuple[str, str], ...] = (
    ("front/eye/wide", "Wide"),
    ("front_left/eye/medium", "Three-quarter left"),
    ("front_right/eye/medium", "Three-quarter right"),
    ("front/eye/close", "Close-up"),
    ("left/eye/medium", "Profile left"),
    ("right/eye/medium", "Profile right"),
    ("front/low/medium", "Low angle"),
    ("front/high/medium", "High angle"),
    ("back/eye/medium", "From behind"),
)
SHOTS_SECONDS_EACH = 0.6  # the board's take plays the nine stills in order, this long each (no video model runs)
SHOTS_TESTED = True  # Oct 23: both session-5 boards (v1-shots-noor-mars, v1-shots-tomas-samurai) checked by eye and by two vision models


# Edit with words: one Qwen-Image 2.1 instruction edit of a still, with a Cast's reference images when the edit puts a
# face or a person in. A preset names a common edit; "custom" takes the person's own words. An edit is a prompt
# directive, not a measurement: a preset is untested until a real render of it was checked by eye (EDITS_TESTED).
@dataclass(frozen=True)
class EditPreset:
    label: str
    directive: str  # the instruction; {detail} stands for the person's words where the preset asks for them
    needs_cast: bool = False  # the edit puts a Cast's face or whole person into the still (consent is on the Cast)
    needs_detail: bool = False  # the person says what: the object to remove, the outfit, the light, the edit


FACE_SWAP = ("Replace the face of the person in the first image with the face of the person in the other images: the "
             "same face shape, eyes, nose, mouth, skin tone and age. Keep the hair, the expression, the head angle, the "
             "clothes, the light and everything else in the first image exactly as it is.")
EDITS: dict[str, EditPreset] = {
    "face_swap": EditPreset("Swap the face", FACE_SWAP, needs_cast=True),
    "character_swap": EditPreset(
        "Swap the person",
        "Replace the person in the first image with the person from the other images, in exactly the same pose, place, "
        "framing and light. Keep the setting and every other object unchanged.", needs_cast=True),
    "remove": EditPreset("Remove something", "Remove {detail} from the picture and fill the space naturally with what "
                         "would be behind it. Change nothing else.", needs_detail=True),
    "outfit": EditPreset("Change the outfit", "Dress the person in {detail}. Keep the face, hair, pose, framing, light and "
                         "setting exactly as they are.", needs_detail=True),
    "relight": EditPreset("Relight", "Relight the picture with {detail}. Keep every person, pose, object and the framing "
                          "exactly as they are: change only the light.", needs_detail=True),
    "custom": EditPreset("Your words", "{detail}. Keep everything the instruction does not mention exactly as it is.",
                         needs_detail=True),
}
LIGHTS = {  # the Relight picker: one phrase each (the relight preset also takes words of its own)
    "left": "a strong key light from the left side and a soft fill from the right",
    "right": "a strong key light from the right side and a soft fill from the left",
    "back": "a bright rim light from behind the subject, the face in soft shadow",
    "top": "a hard light from directly above, deep shadows under the brow",
    "golden": "warm, low golden-hour sunlight from the side and long soft shadows",
    "blue": "cool blue-hour light with the practical lights glowing warm",
    "neon": "magenta and cyan neon light from both sides",
    "candle": "a single warm candle light from below, the rest falling into darkness",
}
EDIT_DETAIL_MAX = 160
# an edit can be aimed at a real person's photo, so it never dresses anyone in underwear, swimwear or lingerie, on top of
# the shared guard (which already refuses removing or seeing through clothes); sheer or transparent only said of a garment
_EDIT_NEVER = re.compile(
    r"\b(?:underwear|bras?|panties|knickers|briefs|boxers|thongs?|bikinis?|swimsuits?|swimwear|bathing\s+suits?|"
    r"swim(?:ming)?\s+trunks|speedos?|lingerie|nighties?|negligees?|revealing|skimpy|bodysuits?|catsuits?|"
    r"latex\s+(?:outfits?|suits?|dress(?:es)?|clothes|clothing|tops?|leggings|pants|corsets?|skirts?)|"
    r"(?:only|just|nothing\s+but|in)\s+(?:an?\s+)?(?:\w+\s+){0,2}towels?|wet\s+and\s+clinging|see[- ]through)\b"
    rf"|\b(?:sheer|transparent)\s+(?:{WORD}){{0,2}}(?:{GARMENT}|{WORN})\b"
    rf"|\b(?:{GARMENT}|{WORN})\s+(?:\w+\s+){{0,2}}?(?:sheer|transparent)\b", re.IGNORECASE)
EDIT_NEVER_MESSAGE = ("An edit never puts a person in underwear, swimwear or lingerie, or makes clothes see-through. "
                      "Describe a different change.")
EDITS_TESTED: frozenset[str] = frozenset({"face_swap", "character_swap", "remove", "outfit", "relight", "custom"})  # Oct 23: v1-edit-* checked by eye at full size and by two vision models


def dresses_down(*texts: str | None) -> bool:
    """Whether any text puts a person in underwear, swimwear or lingerie, or makes clothes see-through: refused for an edit,
    and for a Direct take that starts from the person's own image."""
    return any(text and _EDIT_NEVER.search(text) for text in texts)


def compile_edit_prompt(preset: str, detail: str | None = None) -> str:
    """The instruction for one edit: the preset's directive with the person's words (or a light from the picker)."""
    if preset not in EDITS:
        raise ValueError(f"unknown edit: {preset!r}")
    chosen = EDITS[preset]
    words = " ".join((detail or "").split()).strip().rstrip(".")
    if preset == "relight" and words in LIGHTS:
        words = LIGHTS[words]
    if len(words) > EDIT_DETAIL_MAX:
        raise ValueError(f"say it in at most {EDIT_DETAIL_MAX} characters")
    if chosen.needs_detail and not words:
        raise ValueError("say what to change")
    text = chosen.directive.replace("{detail}", words) if chosen.needs_detail else chosen.directive
    if dresses_down(text):  # the whole instruction: "Dress the person in a towel" says it only with the preset's words
        raise ValueError(EDIT_NEVER_MESSAGE)
    require_safe(text)
    return text


def angle_plan(angle: str) -> dict[str, Any] | None:
    """What a non-default angle adds to a shot plan (None at the default): the id, its geometry, the directive, and
    whether a real render of this angle was checked."""
    if angle == ANGLE_DEFAULT:
        parse_angle(angle)
        return None
    return {"id": angle, "label": describe_angle(angle), **angle_geometry(angle),
            "directive": angle_directive(angle), "tested": angle in ANGLES_TESTED}
# Colour grades: one phrase in the look sentence of the still and the shot. A grade is a prompt word like a lens or a
# light: no tested flag, and "none" is left out of recipes so earlier fingerprints hold.
GRADES = {
    "none": "",
    "teal_orange": "graded teal and orange, cool shadows against warm skin and highlights",
    "kodachrome": "a Kodachrome look with saturated reds and blues and dense blacks",
    "bleach_bypass": "a bleach-bypass look, desaturated and high-contrast with silvery highlights",
    "noir_mono": "black-and-white film noir with deep shadows and hard highlights",
    "pastel": "a soft pastel palette with lifted blacks and muted colours",
    "cross_process": "a cross-processed look with shifted greens and cyans and strong contrast",
}

# Score presets: one music phrase in the sound sentence of the shot. Prompt-only, no tested flag, and "none" is left out
# of recipes the same way.
SCORES = {
    "none": "",
    "solo_piano": "a sparse solo piano",
    "strings": "a slow string swell",
    "synth_pulse": "a low pulsing synth",
    "drone": "a low sustained drone, no melody",
    "acoustic_guitar": "a gentle fingerpicked acoustic guitar",
    "no_music": "no music",
}

# Soundscape presets: one room/ambient phrase in the sound sentence of the shot. Prompt-only, no tested flag, and
# "none" is left out of recipes the same way.
SOUNDSCAPES = {
    "none": "",
    "harbour": "waves against a pier, gulls, rigging in the wind",
    "city_night": "distant traffic, a passing tram, wet streets",
    "rain_on_glass": "rain on a window, muffled street below",
    "forest": "wind in trees, birdsong, a creek",
    "interior_quiet": "a quiet room, a clock, the hum of a fridge",
    "silence": "near silence, only the room tone",
}

GROUPS = {
    "lock": "Lock & aim",
    "dolly": "Dolly & push",
    "zoom": "Zoom & focus",
    "orbit": "Orbit & arc",
    "track": "Track & truck",
    "crane": "Crane & altitude",
    "story": "Handheld & story",
}

# There is no negative prompt: LTX 2.5 distilled runs at CFG 1 (the templates' guider has video_cfg 1 / audio_cfg 1), so one
# would never be applied, and the receipt records only what ran.
# Moves that have a real, checked render in the showcase. Updated by hand after rendering.
# Decided by the keyframing experiment (showcase/experiment-keyframing.json, judged blind with scripts/judge_experiment.py)
# on 2026-10-20: these five moves have a real, checked render. Two-still keyframing won dolly_in and crane_up; for arc_left,
# track_right and orbit_90 plain image-to-video won, so those three are prompt-only in the table below (their anchor edits
# are in the git history and in showcase/experiment-keyframing.json's renders, for a future re-test). Every other keyframed move is a hypothesis and says so in the interface.
# Oct 24 (session 7, prompt style 2, Draft renders checked by eye, by two vision models and by measured optical flow):
# push in, pull out, truck right, pedestal up, low angle, over the shoulder, handheld, whip pan, crash zoom out,
# super dolly in (cast-free), pan left, pan right, tilt down joined the 21 tested before. Bullet time left the set the
# same night: a re-check of the Oct 23 take (and two re-renders) showed the dancer moving and the camera still, the
# opposite of the move; the six-frame sheet it was passed on could not show that.
# Oct 25 (session 8): the Dutch angle, now shot level and larger and turned 15 degrees in code (ROLLS). All four renders
# stayed canted from the first frame to the last; the detective in the alley (v9b-dutch-angle-noir) holds clean (a still
# camera by the optical-flow meter, the action played, the face sharp). Two samurai renders drifted in and the subway
# render turned away from the camera; those were not landed.
# Oct 25 (session 9, judged by eye and measured with the optical-flow meter): track left and truck left (mirrors of their
# twins), tilt up and optical zoom out (windows over a still camera's render), crane down (keyframed from a high hero),
# overhead, helicopter, FPV drone, robo arm and reveal held, and bullet time held as an orbit 90 with the time-freeze
# sentence (the camera circled Tomas, frozen mid-strike, to behind his shoulder). Three left the set: arc left (its takes
# stood still or arced right; arc right, made from it, stays out with it), orbit 360 (its takes were the subject turning in
# front of a still camera; one-still renders flew up or rolled) and through object (all four takes pulled back out of the
# opening). Orbit 180 is one still now, proved by r11-orb-180; the measured proof of each move's tile is PROOFS in previews.py.
# October 26 (session 10, the night before the plan's slot): the samurai draw and bullet time re-rendered. None of 12 draws met
# every rule (the draw lasts under 0.7 s in every render); r13-a4-draw-up-624 is the tile and hero: the blade leaves the scabbard,
# rises vertical and clear of the face, eyes found in every sample. r13-b3-bt-from44ee-1167 (from the 44ee still) replaces the
# bullet time whose blade vanished: dx +59 one sign, face within 8%, the blade long until the camera passes behind him.
# Through object and pedestal down (made as their reverse), the tracked dolly zoom and the keyframed arcs: see the lines below.
# Through object held on October 26 as its reverse: a dolly out rendered from a still framed just inside the open door, played
# backwards (r13-c-through-hut-1341: the picture grows 39 to 75 percent a second with no sideways drift, the camera ends inside).
# The dolly zoom held on October 26 with the face tracked: a dolly out is rendered, the face is found four times a second, and a
# window zooms in code to keep it at its first size (r13-c-vertigo-corridor-1361: the face within 5 percent through the take, the
# zoom 1.0 to 1.72, the corridor stretching behind her). A render that pulls back past the 2.2x cap still fails (the pier take).
VALIDATED: frozenset[str] = frozenset({"aerial_pullback", "bullet_time", "crane_down", "crane_up", "crash_zoom_in", "crash_zoom_out", "dolly_in", "dolly_out", "dutch_angle", "eyes_in", "fisheye", "fpv_drone", "handheld", "helicopter", "hyperlapse", "lazy_susan", "loop", "low_angle", "optical_zoom_in", "optical_zoom_out", "orbit_180", "orbit_90", "over_shoulder", "pan_left", "pan_right", "pedestal_up", "pull_out", "push_in", "reveal", "robot_arm", "snorricam", "static", "super_dolly_in", "through_object", "tilt_down", "tilt_up", "top_down", "track_left", "track_right", "truck_left", "truck_right", "vertigo", "whip_pan", "yoyo_zoom"})


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
        data["frozen"] = self.id in HERO_MOMENT  # one still of a frozen moment, circled from the camera as shot
        data["reversed"] = self.id in REVERSES  # rendered as its reverse and played backwards: no action, line or effect
        data["group_label"] = GROUPS[self.group]
        data.update(move_words(self.id))  # the words the model reads for this move, and how a move made in code is made
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


RETURNS = {"orbit_360", "loop"}  # moves whose last still is the hero again: the shot ends where it began


def _m(
    mid: str, label: str, group: str, mode: str, anchors: int, phrase: str, hold: str,
    keys: tuple[Pose, ...], edits: tuple[str, ...] = (), featured: bool = False,
) -> Move:
    # a full orbit returns to the hero frame, so its last anchor needs no edit
    expected = anchors - 2 if mid in RETURNS else anchors - 1
    if mode == "keyframed" and len(edits) != expected:
        raise ValueError(f"{mid}: keyframed move needs {expected} anchor edits, got {len(edits)}")
    return Move(mid, label, group, mode, anchors, phrase, hold, keys, edits, featured)


_SAME = "Same scene, subject, wardrobe, lighting and style as the reference. "
_FIXED = "fixed focal length, no zoom"


def _arc_edit(side: str, zh: str) -> str:
    """The end still of an arc: the camera 45 degrees round the subject, who keeps facing the same way in the scene."""
    return (f"Re-shoot the same scene with the camera moved 45 degrees to the {side} around the subject, at the same "
            "distance and height. The subject does not turn: they still look toward where the camera stood before, so "
            "the new view shows their face at a three-quarter angle and the setting behind them has swung round. "
            f"将镜头{zh}旋转45度，主体在场景中的朝向不变，不要转向镜头。")


_MOVES: tuple[Move, ...] = (
    # --- lock & aim
    _m("static", "Static", "lock", "prompt_only", 1,
       "The camera is locked off on a tripod; only the subject moves.",
       "no camera movement, no zoom, no drift", (Pose(),), featured=True),
    # Pans, tilts, trucks, pedestals, arc right and track left are one-still moves (October 24): drawn as keyframed
    # moves, their end still came out the same as the hero (an edit keeps the subject centred for a turn or a slide
    # in place), and LTX filled the shot with invented motion: the subject turning round, a tripod appearing.
    _m("pan_left", "Pan left", "lock", "prompt_only", 1,
       "The camera pans to the left, swivelling in place so the view sweeps sideways across the landscape.",
       "pure rotation, camera position fixed, no tilt, no zoom", _turn(yaw=-35)),
    _m("pan_right", "Pan right", "lock", "prompt_only", 1,
       "The camera pans to the right, swivelling in place so the view sweeps sideways across the landscape.",
       "pure rotation, camera position fixed, no tilt, no zoom", _turn(yaw=35)),
    _m("tilt_up", "Tilt up", "lock", "prompt_only", 1,
       "The camera tilts upward, swivelling in place from the subject up toward the sky.",
       "pure rotation, camera position fixed, no pan, no zoom", _turn(pitch=25)),
    _m("tilt_down", "Tilt down", "lock", "prompt_only", 1,
       "The camera tilts downward, swivelling in place from the subject down toward the ground.",
       "pure rotation, camera position fixed, no pan, no zoom", _turn(pitch=-25)),
    _m("whip_pan", "Whip pan", "lock", "prompt_only", 1,  # tested Oct 24: experimental no more
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
    # Made, not asked for (October 25): asked for in words it came out a plain pull-out. Now a dolly-out renders (its
    # two stills, larger) and the picture zooms in code as the camera backs away (ZOOMS): the dolly zoom by construction.
    _m("vertigo", "Dolly zoom (vertigo)", "dolly", "keyframed", 2,
       "A dolly-zoom (vertigo effect): the camera moves back while zooming in so the subject keeps its "
       "size and the background appears to stretch.",
       "subject size constant while the background perspective changes",
       (Pose(), Pose(z=-1.6, fov=25.0)),
       (_SAME + "The camera has pulled back to nearly twice the distance, the subject smaller in frame "
        "with more of the environment visible, same angle and focal length.",)),
    # --- zoom & focus
    # made in code since Oct 25 (REFRAMES), like the zoom out: measured, every recorded zoom in barely moved (the
    # picture grew under 1 px/s), and a lens that only narrows is a window that tightens over a still camera's render
    _m("optical_zoom_in", "Zoom in", "zoom", "prompt_only", 1,
       "The lens zooms in optically from a locked tripod; the subject grows larger.",
       "locked tripod, zero camera travel, zero parallax, optical lens change only", _zoom(2.0), featured=True),
    # One still (October 25): as two stills the end frame ghosted. An optical zoom only changes the lens, so it is made
    # in code (REFRAMES): a still camera renders the wide view and the frame widens to it.
    _m("optical_zoom_out", "Zoom out", "zoom", "prompt_only", 1,
       "The lens zooms out optically while the camera stays planted, the frame widening around the subject.",
       "locked tripod, zero camera travel, zero parallax, optical lens change only", _zoom(0.6)),
    # no construction yet: a focus pull made in code needs a depth model or a focus-edit pair of stills
    _m("rack_focus", "Rack focus", "zoom", "experimental", 1,
       "A rack focus: an object close to the lens starts sharp while the subject behind it is soft, then the focus "
       "pulls back until the subject is crisp and the foreground object melts into blur.",
       "camera still, only the focus plane moves", (Pose(),)),
    # --- orbit & arc
    # prompt-only since the 2026-10-20 experiment: the edited anchor turned the subject instead of moving the camera
    _m("orbit_90", "Orbit 90", "orbit", "prompt_only", 1,
       "The camera orbits 90 degrees around the subject at constant distance, the subject staying "
       "centred while the background rotates behind it.",
       "constant radius, constant height, subject remains centred, no subject spin", _orbit(90), featured=True),
    # prompt-only since Oct 25, for the reason orbit_90 is: measured, the three-still orbit held the camera still while
    # the edited stills turned the subject round (0 to 1 px/s of image motion on its takes), and LTX's own orbit from
    # one still circled Oskar to his back, the harbour swinging round behind him (12.8 px/s, r11-orb-180)
    _m("orbit_180", "Orbit 180", "orbit", "prompt_only", 1,
       "The camera orbits 180 degrees around the subject at constant distance, the subject staying "
       "centred while the background rotates behind it.",
       "constant radius, constant height, subject remains centred, no subject spin", _orbit(180), featured=True),
    # no construction yet: an orbit 180 extended from its own last frame dips at the join and invents the face
    _m("orbit_360", "Orbit 360", "orbit", "keyframed", 5,
       "The camera makes a full 360 degree orbit around the subject at constant distance, the subject "
       "staying centred while the background rotates behind it.",
       "constant radius, constant height, subject remains centred, no subject spin", _orbit(360, 17),
       (_SAME + "The camera has orbited 90 degrees around the subject to its right, seeing it in profile.",
        _SAME + "The camera has orbited 180 degrees around the subject, now seeing it from behind.",
        _SAME + "The camera has orbited 270 degrees around the subject, seeing its left profile.")),
    # arc left: prompt-only from the 2026-10-20 experiment (see orbit_90) until 2026-10-26; arc right followed on 2026-10-24 (see the pans).
    # Neither is promoted since Oct 25: measured, arc left's takes stood still or arced right (VALIDATED)
    # Two stills since Oct 26: the words never set the direction, so the end still does. It is the hero re-shot 45
    # degrees round, and its edit ties the subject's facing to the scene: the front-quarter angle edits failed because
    # "the same facing direction" (_ANGLE_KEEP) reads to Qwen as facing the lens, so the subject turned with the camera.
    _m("arc_left", "Arc left", "orbit", "keyframed", 2,
       "The camera arcs to the left around the subject, a gentle curved move of about 45 degrees.",
       "constant distance, subject remains in frame, no zoom", _orbit(-45, 5), (_arc_edit("left", "向左"),)),
    _m("arc_right", "Arc right", "orbit", "keyframed", 2,
       "The camera arcs to the right around the subject, a gentle curved move of about 45 degrees.",
       "constant distance, subject remains in frame, no zoom", _orbit(45, 5), (_arc_edit("right", "向右"),)),
    # --- track & truck
    _m("track_left", "Track left", "track", "prompt_only", 1,
       "The camera tracks sideways to the left, parallel to the subject at constant distance, the "
       "background sliding behind it.",
       f"lateral travel only, constant distance, {_FIXED}", _line(dx=-0.7), featured=True),
    _m("track_right", "Track right", "track", "prompt_only", 1,
       "The camera tracks sideways to the right, parallel to the subject at constant distance, the "
       "background sliding behind it.",
       f"lateral travel only, constant distance, {_FIXED}", _line(dx=0.7), featured=True),
    _m("truck_left", "Truck left", "track", "prompt_only", 1,
       "The camera trucks left without rotating, sliding past the scene.",
       f"lateral travel, no rotation, {_FIXED}", _line(dx=-0.5)),
    _m("truck_right", "Truck right", "track", "prompt_only", 1,
       "The camera trucks right without rotating, sliding past the scene.",
       f"lateral travel, no rotation, {_FIXED}", _line(dx=0.5)),
    # --- crane & altitude
    _m("crane_up", "Crane up", "crane", "keyframed", 2,
       "The camera cranes upward and tilts down slightly to keep the subject framed, rising smoothly.",
       f"vertical travel with a slight tilt, {_FIXED}", _line(dy=0.8, dz=-0.2, pitch=-20),
       (_SAME + "The camera is now raised about two metres higher, looking down at a steeper angle "
        "with more of the ground visible.",), featured=True),
    # Two stills again (October 25), framed this time: the hero is shot from high up (HERO_FRAMING) and the end still
    # lowered to eye level, so LTX travels down between two real views. As one still it drifted, and as two stills from
    # an eye-level hero there was nothing to descend from (October 24).
    _m("crane_down", "Crane down", "crane", "keyframed", 2,
       "The camera cranes downward from a high vantage toward the subject, settling at eye level.",
       f"vertical travel with a slight tilt, {_FIXED}", (Pose(y=0.8, z=-1.2, pitch=-20), Pose()),
       (_SAME + "The camera is now lowered to eye level, looking straight at the subject, the horizon at the middle of the frame.",),
       featured=True),
    _m("pedestal_up", "Pedestal up", "crane", "prompt_only", 1,
       "The camera rises straight up without tilting, the frame lifting away from the subject.",
       f"pure vertical travel, no tilt, {_FIXED}", _line(dy=0.5)),
    # rendered as a pedestal up and played backwards since Oct 26 (REVERSES): asked for in words it rose or tilted
    _m("pedestal_down", "Pedestal down", "crane", "prompt_only", 1,
       "The camera sinks straight down without tilting, the subject rising in the frame.",
       f"pure vertical travel, no tilt, {_FIXED}", _line(dy=-0.4)),
    _m("top_down", "Overhead", "crane", "experimental", 1,
       "A bird's-eye view from directly above: the camera looks straight down at the ground and the subject from the "
       "top, holding high overhead.",
       "camera directly above, perpendicular to the ground", (Pose(y=1.0, z=0.0, pitch=-90),)),
    _m("low_angle", "Low angle", "crane", "prompt_only", 1,  # tested Oct 24: experimental no more
       "A low-angle shot from near the ground looking up at the subject, making it feel imposing.",
       "camera near the floor, tilted up, no movement", (Pose(y=-0.4, pitch=20),)),
    _m("helicopter", "Helicopter", "crane", "experimental", 1,
       "Aerial footage from a helicopter high above: the camera flies forward over the landscape and sweeps in a wide "
       "circle around the subject far below, rising slowly, the horizon level.",
       "large smooth arc, gradual rise, steady horizon", (*_orbit(120, 7),)),
    # --- handheld & story
    _m("handheld", "Handheld", "story", "prompt_only", 1,
       "Handheld camera with natural, subtle shake and small reframing, a documentary feel.",
       "gentle shake only, no large camera moves", (Pose(),)),
    _m("fpv_drone", "FPV drone", "story", "experimental", 1,
       "First-person drone footage: the camera races low and fast toward the subject, then swoops up and over them in "
       "one continuous banking flight.",
       "continuous fast flight, no cuts", (*_orbit(200, 9),)),
    _m("robot_arm", "Robo arm", "story", "experimental", 1,
       "A motion-control shot: the camera glides in one perfectly smooth, precise curve toward the subject, like a "
       "robotic camera arm.",
       "mechanically smooth path, no shake", (Pose(), Pose(x=0.4, y=0.2, z=-0.8, yaw=-15))),
    _m("over_shoulder", "Over the shoulder", "story", "prompt_only", 1,
       "An over-the-shoulder shot from just behind a person, looking toward the subject.",
       "foreground shoulder softly out of focus, no camera movement", (Pose(x=0.2, y=0.1, z=-1.1),)),
    _m("reveal", "Reveal", "story", "experimental", 1,
       "The camera slides sideways past a dark object close to the lens, a pillar, a branch or a door frame, and the "
       "subject is revealed beyond it.",
       "foreground wipes across the lens, then the subject is revealed", _line(dx=0.5, dz=0.2)),
    # --- signature moves: the names creators know from the viral presets; prompt-only, tested one by one as real
    # renders are checked (VALIDATED). Their tempo is in the phrase, so compile_prompt adds no speed to them.
    _m("crash_zoom_in", "Crash zoom in", "zoom", "prompt_only", 1,
       "A crash zoom: the lens snaps in on the subject in a fraction of a second and holds, a sudden punch of attention.",
       "one abrupt zoom, locked tripod, then a steady frame", _zoom(3.0), featured=True),
    _m("crash_zoom_out", "Crash zoom out", "zoom", "prompt_only", 1,
       "A crash zoom out: the lens snaps wide in a fraction of a second, the subject suddenly small in its setting, then holds.",
       "one abrupt zoom, locked tripod, then a steady frame", _zoom(0.4)),
    _m("eyes_in", "Eyes in", "zoom", "prompt_only", 1,
       "A slow macro push into the subject's eyes until they fill the frame, the rest of the face softening out of focus.",
       "smooth continuous push, the eyes stay centred and sharp", (Pose(), Pose(z=-0.35, fov=14.0))),
    _m("snorricam", "Snorricam", "story", "prompt_only", 1,
       "A snorricam: the camera is rigged to the subject's body facing them, so the subject stays fixed in frame while "
       "the whole world swings and lurches behind them as they move.",
       "subject locked to the frame, the background moves instead", (Pose(),)),
    # rendered as a dolly out and played backwards since Oct 26 (REVERSES): asked for in words, every take pulled back
    _m("through_object", "Through object", "story", "prompt_only", 1,
       "The camera pushes forward through an opening in the foreground, a window, a doorway or a gap, and comes out "
       "into the scene beyond it.",
       "continuous forward travel through the opening, no cut", _line(dz=0.9)),
    _m("hyperlapse", "Hyperlapse", "story", "prompt_only", 1,
       "A hyperlapse: the camera travels a long way through the scene in time-lapse, people and light streaking past "
       "while the subject stays the anchor of the frame.",
       "long steady travel at time-lapse speed, horizon level", (Pose(x=-0.9, z=-1.6), Pose(x=0.9, z=-0.6))),
    _m("lazy_susan", "Lazy Susan", "orbit", "prompt_only", 1,
       "A turntable shot: the camera is locked off while the subject rotates slowly on the spot, showing every side "
       "like a product on a lazy Susan.",
       "camera locked off, the subject turns a full circle, constant lighting", (Pose(),)),
    _m("loop", "Loop", "lock", "keyframed", 2,
       "A seamless loop: the camera holds its frame while the scene moves and breathes, and every motion returns "
       "exactly to where it began, so the last frame flows back into the first.",
       "the frame holds; the motion comes back to its start", (Pose(), Pose())),
    # Bullet time is made from two parts that held (October 25, GPU session 9). Asked for in its own words, LTX played
    # the dancer out and held the camera still. Re-shot from the side by the angle edits, the dancer and the samurai only
    # turned their heads while the street stayed put. The October 23 time-freeze prompt (style 1) rolled the frame, pulled
    # back or held still on three new takes. What held: one still of the moment at its peak, the 90-degree orbit's
    # style-2 words and the time-freeze sentence; the camera circled Tomas, frozen mid-strike, from the front to behind
    # his shoulder (r11-bt4-samurai-90). LTX gets exactly that (PROMPT_AS, HERO_MOMENT); this phrase describes the move.
    _m("bullet_time", "Bullet time", "orbit", "prompt_only", 1,
       "Bullet time: the moment is frozen in mid-air, every figure, droplet and speck of dust hanging perfectly still, "
       "while the camera alone sweeps a smooth quarter circle around the subject.",
       "the scene stays frozen; only the camera travels", _orbit(90, 9), featured=True),
    _m("aerial_pullback", "Aerial pullback", "crane", "prompt_only", 1,
       "An aerial pullback: the camera pulls back and rises high into the sky in one continuous move, the subject "
       "shrinking as the wide landscape opens up around them.",
       "one smooth rising pull-back, horizon level", (Pose(), Pose(y=1.2, z=-2.6, pitch=-35.0))),
    _m("dutch_angle", "Dutch angle", "lock", "prompt_only", 1,
       "A Dutch angle: the frame stays rolled about 20 degrees to one side for the whole shot, the horizon slanting "
       "across the frame and the roll never changing, a sense of unease.",
       "the tilt holds at the same angle throughout; the camera never rolls further", (Pose(),)),
    _m("fisheye", "Fisheye", "zoom", "prompt_only", 1,
       "An ultra-wide fisheye lens close to the subject, the edges of the frame bending in strong barrel distortion "
       "as the camera drifts.",
       "fisheye distortion throughout, gentle drift only", (Pose(z=-0.6, fov=110.0),)),
    _m("super_dolly_in", "Super dolly in", "dolly", "prompt_only", 1,
       "A super dolly in: one long, fast push from a wide view of the setting all the way into a close-up of the "
       "subject, without a cut.",
       "one continuous fast push, no zoom", _line(dz=0.75)),
    _m("yoyo_zoom", "YoYo zoom", "zoom", "prompt_only", 1,
       "A yo-yo zoom: the lens zooms in fast on the subject, back out, and in again, a rhythmic punch on the beat.",
       "the camera stays locked, only the zoom moves", (Pose(), Pose(fov=16.0), Pose(fov=40.0), Pose(fov=16.0))),
)

MOVES: dict[str, Move] = {m.id: m for m in _MOVES}
assert len(MOVES) == 49, f"expected 49 moves, found {len(MOVES)}"


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
# Three or more stills in one LTX pass (the middle ones guided inside the shot) instead of one first-last-frame segment
# per pair of stills. Off until a real render of it has been checked by eye; the receipt records which way a take was made.
SINGLE_PASS = True  # on since Oct 22: the one-pass orbits ghosted at the template's guide strength (0.7) and held at 0.4 in the evening sweep
# The template pins every guided still at 0.7. A lower value steers the camera through the middle stills without
# locking the subject to their pose; None keeps the template's value; flipped by hand after a render is checked.
MID_GUIDE_STRENGTH: float | None = 0.4  # checked by eye on the Oct 22 evening one-pass sweep (sp-orbit-*)
LTX_FPS = 24  # the templates' fixed frame rate (a test reads it from the graph); frames = seconds * LTX_FPS + 1


def mid_frame_index(k: int, stills: int, seconds: int) -> int:
    """The frame a middle still is guided at in a shot of `stills` stills: still k sits k/(stills-1) of the way through,
    snapped to a multiple of 8 (LTX's temporal stride) and kept clear of the first and last frames."""
    if not 0 < k < stills - 1:
        raise ValueError(f"still {k} is not a middle still of {stills}")
    frames = seconds * LTX_FPS + 1
    steps = (frames - 1) // 8
    at = round(k / (stills - 1) * steps) * 8
    return int(min(max(at, 8), frames - 1 - 8))


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
    effect: str = "none"  # an EFFECTS or TRANSFORMATIONS preset on the shot; "none" is left out of recipes so old fingerprints hold
    grade: str = "none"  # a GRADES colour palette; "none" is left out of recipes the same way
    score: str = "none"  # a SCORES music preset; "none" is left out of recipes so old fingerprints hold
    soundscape: str = "none"  # a SOUNDSCAPES ambient preset; "none" is left out of recipes the same way
    angle: str = ANGLE_DEFAULT  # where the camera starts ("azimuth/height/distance"); the default is left out of recipes too

    def validate(self) -> None:
        for value, table, name in (
            (self.sensor, SENSORS, "sensor"), (self.lens, LENSES, "lens"),
            (self.aperture, APERTURES, "aperture"), (self.lighting, LIGHTING, "lighting"),
            (self.speed, SPEEDS, "speed"), (self.effect, EFFECT_IDS, "effect"), (self.grade, GRADES, "grade"),
            (self.score, SCORES, "score"), (self.soundscape, SOUNDSCAPES, "soundscape"),
        ):
            if value not in table:
                raise ValueError(f"unsupported {name}: {value}")
        parse_angle(self.angle)
        get_move(self.movement)
        if not MIN_FOCAL_MM <= self.focal_length_mm <= MAX_FOCAL_MM:
            raise ValueError(f"focal_length_mm must be between {MIN_FOCAL_MM} and {MAX_FOCAL_MM}")
        if not MIN_DURATION_SECONDS <= self.duration_seconds <= MAX_DURATION_SECONDS:
            raise ValueError(
                f"duration_seconds must be between {MIN_DURATION_SECONDS} and {MAX_DURATION_SECONDS}")


@dataclass(frozen=True)
class AnchorSpec:
    index: int
    role: str  # "hero" | "edit" | "repeat_hero" | "transform" (the end state of a transformation)
    edit_prompt: str | None = None
    check_identity: bool = True  # False when the still is meant to change the face (a gold statue, forty years)


@dataclass(frozen=True)
class SegmentSpec:
    index: int
    start_anchor: int
    end_anchor: int | None
    seconds: int
    template: str  # "ltx25_flf2v" | "ltx25_i2v"
    mids: tuple[tuple[int, int], ...] = ()  # (anchor index, frame index) of the stills guided inside one pass


@dataclass(frozen=True)
class ShotPlan:
    rig: CameraRig
    move_id: str
    mode: str
    prompt: str
    anchors: tuple[AnchorSpec, ...]
    segments: tuple[SegmentSpec, ...]
    total_seconds: int
    notes: tuple[str, ...] = field(default=())
    transformation: str | None = None  # the TRANSFORMATIONS id when the effect edits the last still
    angle: dict[str, Any] | None = None  # angle_plan(): the hero is re-shot from here before the move (None: as shot)
    dialogue: dict[str, Any] | None = None  # dialogue_plan(): the spoken line, its delivery and language (None: silent)
    action: str | None = None  # action_words(): what happens, in the video prompt only (None: no action)
    roll: float | None = None  # ROLLS: degrees the finished video is turned in code (None: as shot)
    mirror: str | None = None  # MIRRORS: the twin move rendered on the flipped hero, flipped back in code (None: as shot)
    reframe: dict[str, Any] | None = None  # REFRAMES: the window moved over the render in code (None: as shot)
    reverse: str | None = None  # REVERSES: the move rendered instead, its picture played backwards in code (None: as shot)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _focal_word(mm: int) -> str:
    for limit, word in ((24, "ultra-wide"), (35, "wide"), (70, "natural"), (135, "short telephoto")):
        if mm < limit:
            return word
    return "telephoto"


_NO_SPEED = {"static", "handheld", "whip_pan", "crash_zoom_in", "crash_zoom_out", "snorricam", "hyperlapse", "lazy_susan", "super_dolly_in", "bullet_time", "yoyo_zoom", "aerial_pullback", "loop", "dutch_angle"}  # the move's own tempo is in its phrase

# A move that is itself a lens: its words replace the rig's lens and focal length in the still and the video prompt alike,
# so the first frame is already distorted and LTX is never told two different lenses.
LENS_MOVES = {
    "fisheye": "an ultra-wide circular fisheye lens, about 8mm, its strong barrel distortion bending the edges of the frame",
}


def _lens_words(rig: CameraRig) -> str:
    if rig.movement in LENS_MOVES:
        return LENS_MOVES[rig.movement]
    return f"{LENSES[rig.lens]}, {rig.focal_length_mm}mm ({_focal_word(rig.focal_length_mm)})"


def _grade_words(rig: CameraRig) -> str:
    return f", {GRADES[rig.grade]}" if GRADES.get(rig.grade) else ""


def _sound_sentence(rig: CameraRig, audio: str | None) -> str | None:
    """The sound paragraph: ambient soundscape, free-text audio, then the score. Empty means no sound sentence."""
    ambient: list[str] = []
    if SOUNDSCAPES.get(rig.soundscape):
        ambient.append(SOUNDSCAPES[rig.soundscape])
    if audio and audio.strip():
        ambient.append(audio.strip().rstrip("."))
    music: list[str] = []
    if rig.score == "no_music":
        music.append("No music.")
    elif SCORES.get(rig.score):
        music.append(f"Music: {SCORES[rig.score]}, continuing across the whole shot.")
    if not ambient and not music:
        return None
    parts: list[str] = []
    if ambient:
        parts.append(f"Sound: {'. '.join(ambient)}.")
    parts.extend(music)
    return " ".join(parts)


def effect_sentence(effect_id: str) -> str:
    """The sentence an effect adds to the shot prompt: a weather preset's own, or a transformation's motion phrase."""
    if effect_id in TRANSFORMATIONS:
        return TRANSFORMATIONS[effect_id].phrase
    return EFFECTS.get(effect_id, "")


def dialogue_sentence(line: str, delivery: str = "natural", language: str | None = None) -> str:
    """The spoken line as LTX's prompting guide wants it: the delivery, the language when given, the words in quotes."""
    if delivery not in DELIVERIES:
        raise ValueError(f"delivery must be one of {', '.join(DELIVERIES)}")
    words = " ".join(line.split()).strip().strip('"').strip("“”")
    if not words:
        raise ValueError("the line is empty")
    if len(words) > LINE_MAX:
        raise ValueError(f"keep the line under {LINE_MAX} characters")
    tongue = " ".join((language or "").split()).strip()
    if len(tongue) > LANGUAGE_MAX:
        raise ValueError(f"keep the language under {LANGUAGE_MAX} characters")
    spoken = f"in {tongue}, " if tongue else ""
    return f'The person in the shot speaks {spoken}{DELIVERIES[delivery]}, lips moving with the words: "{words}"'


def dialogue_plan(line: str | None, delivery: str = "natural", language: str | None = None) -> dict[str, Any] | None:
    """What the receipt and the plan say about a spoken line; None when the shot has none."""
    if not line or not line.strip():
        return None
    sentence = dialogue_sentence(line, delivery, language)
    words = sentence.split(": ", 1)[1].strip('"')
    out: dict[str, Any] = {"line": words, "delivery": delivery, "tested": DIALOGUE_TESTED}
    tongue = " ".join((language or "").split()).strip()
    if tongue:
        out["language"] = tongue
    return out


def action_words(action: str | None) -> str | None:
    """The action as a recipe keeps it: whitespace collapsed, 3 to ACTION_MAX characters, passed by the content guard.
    None or blank means no action."""
    if action is None:
        return None
    if not isinstance(action, str):
        raise ValueError("the action must be text")
    words = " ".join(action.split())
    if not words:
        return None
    if not 3 <= len(words) <= ACTION_MAX:
        raise ValueError(f"describe the action in 3 to {ACTION_MAX} characters")
    require_safe(words)
    return words


def action_sentence(action: str | None) -> str | None:
    """The action as its own sentence in the video prompt: a capital first letter and a closing stop. None without one."""
    words = action_words(action)
    if not words:
        return None
    text = words.rstrip(" ,;:") or words
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


# Prompt style 2 (October 24, from LTX 2.5's prompting guide and published camera guides): the camera sentence ends
# on where the move arrives, said in positive words, because LTX 2.5 runs at CFG 1 with no negative prompt and a
# "no zoom" still puts the word zoom in front of it; the default look sentence is dropped from the video prompt (the
# still already carries it). Style 2 is the default since October 24: it held on the A/B renders (the samurai's dolly
# went further and still drew the katana; the crash zoom and the half orbit held; the super dolly in finally pushed all
# the way in) and the tested moves were rendered again under it. OPENFIELD_PROMPT_STYLE=1 brings back the old words.
PROMPT_STYLES = (1, 2)
ENDS: dict[str, str] = {
    "static": "The frame stays perfectly still from the first moment to the last; only the subject moves.",
    "pan_left": "The camera turns in place to the left and settles on the new view, level and at the same height.",
    "pan_right": "The camera turns in place to the right and settles on the new view, level and at the same height.",
    "tilt_up": "The camera turns upward in place and settles on the higher view.",
    "tilt_down": "The camera turns downward in place and settles on the lower view.",
    "whip_pan": "After one fast swing the frame comes to rest on a new, steady view.",
    "dolly_in": "The camera travels forward on its track and arrives at a close view of the subject, the lens height unchanged.",
    "dolly_out": "The camera travels backward on its track and arrives at a wide view with the whole setting around the subject.",
    "push_in": "The camera eases a short way forward and ends a little closer on the subject.",
    "pull_out": "The camera eases a short way back and ends a little wider around the subject.",
    "vertigo": "The subject keeps the same size from start to end while the background stretches away behind it.",
    "optical_zoom_in": "The camera stays planted in one spot and only the lens zooms, ending on a tight view of the subject with the background flattened behind.",
    "optical_zoom_out": "The camera stays planted in one spot and only the lens zooms out, ending on a wide view of the whole scene.",
    "rack_focus": "The camera holds still and the focus finishes sharp on the subject, the foreground melted into soft blur.",
    "orbit_90": "The camera circles a quarter turn at the same distance and height and ends with the subject seen from the side, still centred.",
    "orbit_180": "The camera circles halfway round at the same distance and height and ends behind the subject, who stays centred and facing the same way.",
    "orbit_360": "The camera circles all the way round at the same distance and height and ends where it began, the subject centred throughout.",
    # an arc names its direction once, in its phrase (the end still carries it as well)
    "arc_left": "The camera ends at the same distance on a three-quarter view of the subject, who keeps facing the same way while the setting swings round behind them.",
    "arc_right": "The camera ends at the same distance on a three-quarter view of the subject, who keeps facing the same way while the setting swings round behind them.",
    "track_left": "The camera glides sideways to the left at the same distance, the subject keeping its size while the background slides past.",
    "track_right": "The camera glides sideways to the right at the same distance, the subject keeping its size while the background slides past.",
    "truck_left": "The camera slides to the left facing the same direction the whole time, the scene passing across the frame.",
    "truck_right": "The camera slides to the right facing the same direction the whole time, the scene passing across the frame.",
    "crane_up": "The camera rises smoothly and ends high above, looking down over the subject and the setting.",
    "crane_down": "The camera descends smoothly and ends at eye level with the subject.",
    "pedestal_up": "The camera rises straight up facing the same way and ends higher, the subject lower in the frame.",
    "pedestal_down": "The camera sinks straight down facing the same way and ends lower, the subject higher in the frame.",
    "top_down": "The camera looks straight down from directly above for the whole shot.",
    "low_angle": "The camera stays low near the ground, looking up, steady for the whole shot.",
    "helicopter": "The camera flies a wide smooth arc while rising, the horizon level, and ends high above the scene.",
    "handheld": "The frame breathes with a light handheld sway and small reframes, staying on the subject.",
    "fpv_drone": "The camera flies on in one continuous fast take, banking through the scene.",
    "robot_arm": "The camera follows one mechanically smooth path and settles precisely on the subject.",
    "over_shoulder": "The shoulder stays soft and dark in the foreground while the subject beyond it stays sharp; the camera holds steady.",
    "reveal": "The foreground element slides out of the frame and the subject is revealed, sharp and centred.",
    "crash_zoom_in": "After one abrupt snap of the zoom the frame holds steady on a tight view of the subject.",
    "crash_zoom_out": "After one abrupt snap of the zoom the frame holds steady on a wide view, the subject small in the setting.",
    "eyes_in": "The push ends on an extreme close-up of the eyes, centred and sharp.",
    "snorricam": "The subject stays fixed in the centre of the frame while the world swings around them.",
    "through_object": "The camera passes through the opening in one continuous forward move and arrives on the subject beyond it.",
    "hyperlapse": "The camera travels on at time-lapse speed in one steady line, the horizon level.",
    "lazy_susan": "The camera holds still while the subject turns a full circle on the spot, the light staying the same.",
    "loop": "The motion comes back round to exactly where it began, so the last frame matches the first.",
    "bullet_time": "The camera arrives at the subject's side, the frozen moment now seen in profile.",
    "aerial_pullback": "The camera rises and pulls back in one smooth move and ends high above, the subject small in the landscape, the horizon level.",
    "dutch_angle": "The frame stays rolled at the same angle for the whole shot, the horizon slanting the same way from start to end.",
    "fisheye": "The fisheye curve stays on the whole frame while the camera drifts gently.",
    "super_dolly_in": "The camera pushes forward fast in one continuous move and ends on a close-up of the subject's face.",
    "yoyo_zoom": "The camera stays planted while the zoom pushes in, pulls back out and pushes in again.",
}


# Style 2 rewrites the six move phrases that carry a negation ("without tilting", "never changing"); all six were
# untested under style 1, so no tested move's words change.
PHRASES_V2: dict[str, str] = {
    "truck_left": "The camera trucks left, sliding sideways past the scene while facing the same direction.",
    "truck_right": "The camera trucks right, sliding sideways past the scene while facing the same direction.",
    "pedestal_up": "The camera rises straight up, level and facing the same way, the frame lifting away from the subject.",
    # Oct 25: "the horizon line rising through the frame" described a tilt down, and LTX tilted down and rose; a level
    # camera that lowers keeps the horizon where it is while the subject rises in the frame
    "pedestal_down": "The camera lowers straight down like an elevator, staying level and facing straight ahead: the "
                     "subject rises in the frame while the horizon stays level across it.",
    "dutch_angle": "A Dutch angle: the frame is rolled about 20 degrees to one side and holds that tilt for the whole shot, "
                   "the horizon slanting across the frame, a sense of unease.",
    "super_dolly_in": "A super dolly in: one long, fast, continuous push from a wide view of the setting all the way into a "
                      "close-up of the subject.",
}


def prompt_style() -> int:
    """The video prompt style: OPENFIELD_PROMPT_STYLE (1 or 2), read each time; 2 when unset or not a style."""
    raw = os.environ.get("OPENFIELD_PROMPT_STYLE", "2").strip()
    return int(raw) if raw in {"1", "2"} else 2


def _look_is_default(rig: CameraRig) -> bool:
    base = CameraRig()
    return all(getattr(rig, f) == getattr(base, f) for f in ("sensor", "lens", "focal_length_mm", "aperture", "lighting", "grade"))


def compile_prompt(rig: CameraRig, subject: str, audio: str | None = None, *, line: str | None = None,
                   delivery: str = "natural", language: str | None = None, action: str | None = None,
                   style: int | None = None, as_delivered: bool = False) -> str:
    """One flowing paragraph in the style LTX responds to: scene, action, look, camera, constraint, speech, sound.
    Style 2: scene, action, camera and where it arrives, effect, look only when changed, speech, sound.
    `as_delivered`: describe the move the viewer sees, not the render it is made from (an extension continues the
    delivered take, so a mirrored or reversed move keeps its own words there)."""
    rig.validate()
    # a rolled move (ROLLS) is shot level and static; the turn is made afterwards, in code; a mirrored or reversed move is
    # prompted with its twin's words (PROMPT_AS), unless the words must say what was delivered
    delivered = as_delivered and (rig.movement in MIRRORS or rig.movement in REVERSES)
    move = get_move("static" if rig.movement in ROLLS else rig.movement if delivered else PROMPT_AS.get(rig.movement, rig.movement))
    if (style or prompt_style()) == 2:
        return _compile_prompt_v2(rig, move, subject, audio, line=line, delivery=delivery, language=language,
                                  action=action)
    look = (
        f"Shot on {SENSORS[rig.sensor]} with {_lens_words(rig)}, {APERTURES[rig.aperture]}; "
        f"{LIGHTING[rig.lighting]}{_grade_words(rig)}."
    )
    move_text = move.phrase if move.id in _NO_SPEED else (
        f"{move.phrase.rstrip('.')}, moving {SPEEDS[rig.speed]}."
    )
    parts = [subject.strip().rstrip(".") + ".", look, move_text]
    sentence = action_sentence(action)
    if sentence:  # what happens comes straight after what is there
        parts.insert(1, sentence)
    if rig.movement in HERO_MOMENT and rig.effect != "time_freeze":
        parts.append(EFFECTS["time_freeze"])  # the frozen instant, in the words that held
    if effect_sentence(rig.effect):
        parts.append(effect_sentence(rig.effect))
    parts.append(f"Constraint: {move.hold}.")
    if line and line.strip():
        parts.append(dialogue_sentence(line, delivery, language))
    sound = _sound_sentence(rig, audio)
    if sound:
        parts.append(sound)
    return " ".join(parts)


def _compile_prompt_v2(rig: CameraRig, move: Move, subject: str, audio: str | None, *, line: str | None,
                       delivery: str, language: str | None, action: str | None) -> str:
    phrase = PHRASES_V2.get(move.id, move.phrase)
    move_text = phrase if move.id in _NO_SPEED else f"{phrase.rstrip('.')}, moving {SPEEDS[rig.speed]}."
    parts = [subject.strip().rstrip(".") + "."]
    sentence = action_sentence(action)
    if sentence:
        parts.append(sentence)
    parts += [move_text, ENDS.get(move.id, "")]
    if rig.movement in HERO_MOMENT and rig.effect != "time_freeze":
        parts.append(EFFECTS["time_freeze"])  # the frozen instant, in the words that held
    if effect_sentence(rig.effect):
        parts.append(effect_sentence(rig.effect))
    if not _look_is_default(rig):
        parts.append(f"Shot on {SENSORS[rig.sensor]} with {_lens_words(rig)}, {APERTURES[rig.aperture]}; "
                     f"{LIGHTING[rig.lighting]}{_grade_words(rig)}.")
    if line and line.strip():
        parts.append(dialogue_sentence(line, delivery, language))
    sound = _sound_sentence_v2(rig, audio)
    if sound:
        parts.append(sound)
    return " ".join(p for p in parts if p)


def _sound_sentence_v2(rig: CameraRig, audio: str | None) -> str | None:
    """Style 2's sound: the same soundscape, audio words and score as style 1, said as sentences without labels."""
    ambient: list[str] = []
    if SOUNDSCAPES.get(rig.soundscape):
        ambient.append(SOUNDSCAPES[rig.soundscape].rstrip("."))
    if audio and audio.strip():
        ambient.append(audio.strip().rstrip("."))
    parts: list[str] = []
    if ambient:
        heard = "; ".join(ambient)
        if len(heard) > 1 and heard[0].isupper() and heard[1].islower():
            heard = heard[0].lower() + heard[1:]  # "Heavy rain" reads on after "We hear"; "LA traffic" keeps its capitals
        parts.append(f"We hear {heard}.")
    if rig.score == "no_music":
        parts.append("No music.")
    elif SCORES.get(rig.score):
        parts.append(f"The music is {SCORES[rig.score]}, continuing across the whole shot.")
    return " ".join(parts) or None


# How the first still is framed when a shot renders from that one still (a prompt-only move, or quick mode): it has
# to leave room for the move. A keyframed move takes its framing from its anchor stills instead.
START_FRAMING = {
    "pan_left": "Framed as a wide view, the subject on the right side of the frame and open landscape to the left.",
    "pan_right": "Framed as a wide view, the subject on the left side of the frame and open landscape to the right.",
    "tilt_up": "Framed with the subject in the lower half of the frame and open sky filling the upper half.",
    "tilt_down": "Framed as a medium-wide shot with the ground at the subject's feet in view.",
    "crash_zoom_in": "Framed as a wide shot, the subject small in the frame with the whole setting around them.",
    "super_dolly_in": "Framed as a wide view of the whole setting, the subject small in it.",
    "yoyo_zoom": "Framed as a medium-wide shot of the subject.",
    "eyes_in": "Framed as a medium close-up of the face.",
    "crash_zoom_out": "Framed as a tight close-up of the subject.",
    "aerial_pullback": "Framed as a medium shot of the subject from slightly above.",
    # played backwards (REVERSES), the render's first frame is the delivered shot's last: the still is where the push ends
    "through_object": "Framed from just inside an open doorway or window, the edges of its frame at the very borders of "
                      "the picture, the room and the subject ahead.",
    "over_shoulder": "Framed from just behind a person's shoulder, looking toward the subject.",
    "low_angle": "Framed from a low angle near the ground, looking up at the subject.",
    "top_down": "Framed from directly overhead, looking straight down.",
    "dutch_angle": "Framed as a wide shot, the subject's whole figure centred with plenty of room above the head and on every side.",
    "crane_up": "Framed as a wide shot from low down, the subject small with the whole setting above and around it.",
    "crane_down": "Framed as a wide shot from high up, looking down over the whole setting.",
    "dolly_in": "Framed as a wide shot with room to move in.",
    "push_in": "Framed as a wide shot with room to move in.",
    "optical_zoom_in": "Framed as a wide shot with the subject at its centre.",
    "dolly_out": "Framed as a close shot of the subject.",
    "pull_out": "Framed as a close shot of the subject.",
    "optical_zoom_out": "Framed as a wide shot of the whole scene with the subject at its centre.",
    "rack_focus": "Framed with an object close to the lens in sharp focus in the foreground, and the subject behind it soft "
                  "and out of focus.",
    "reveal": "Framed from behind a dark object close to the lens that hides one side of the frame, the subject beyond it.",
    "helicopter": "Framed as a high aerial view of the landscape, the subject small far below.",
    "fpv_drone": "Framed as a low, wide view down a long open space toward the subject.",
    "robot_arm": "Framed as a medium-wide shot of the subject.",
}


# Moves made from their mirror image (October 25). Track right and truck right held on real renders; their twins went
# the wrong way or barely moved. So the hero is flipped, the twin renders, and the video is flipped back in code: the
# camera travels the other way through the same scene. A move here is prompted with its twin's words. Arc right was
# made from arc left this way until Oct 26; both arcs are two stills now, so neither leans on the other.
MIRRORS: dict[str, str] = {"track_left": "track_right", "truck_left": "truck_right"}
# Moves made by playing their reverse backwards (October 26). Every through-object take pulled back out of the opening
# and pedestal down rose or tilted, while the dolly out and the pedestal up hold. So the reverse renders from the still
# and the picture is played backwards in code: the still is where the shot ends. An action or a spoken line would run
# backwards with it, so compile_shot refuses both. A move here is prompted with its reverse's words (PROMPT_AS).
REVERSES: frozenset[str] = frozenset({"through_object", "pedestal_down"})
# Moves made by moving a window over a larger render in code (October 25), prompted as PROMPT_AS says. An optical zoom
# only changes the lens and a small tilt turns the camera in place, so neither carries the camera through the scene:
# a window that tightens or rises over a still camera's render is the same picture. The dolly zoom is a dolly-out
# whose lens closes in as the camera backs away. (zoom at the first and last frame, height at the first and last
# frame): zoom 1 shows the whole render, 1.5 two thirds of it; height 0 is the top of the free travel, 1 the bottom.
REFRAMES: dict[str, tuple[tuple[float, float], tuple[float, float], str]] = {
    "vertigo": ((1.0, 1.8), (0.5, 0.5), "rendered as a dolly-out, then zoomed in code as the camera backs away, so the subject keeps its size"),
    "optical_zoom_out": ((1.5, 1.0), (0.5, 0.5), "rendered from a still camera, then the lens widened in code from 1.5x to the whole frame"),
    "optical_zoom_in": ((1.0, 1.5), (0.5, 0.5), "rendered from a still camera, then the lens narrowed in code from the whole frame to 1.5x"),
    "tilt_up": ((1.5, 1.5), (1.0, 0.0), "rendered from a still camera, then the frame tilted upward in code across the render"),
}
# Reframes that follow the face instead of the fixed curve (October 26). A real dolly zoom holds the subject's size, and
# a fixed 1 to 1.8 zoom only does that when the render backs away at exactly the speed it assumes. So the render is
# sampled, the face measured and the zoom holds its first height (video.face_zoom_path); when too few frames show a
# face the fixed curve stands, and the receipt says why.
TRACKED: dict[str, str] = {"vertigo": "face"}
PROMPT_AS: dict[str, str] = {**MIRRORS, "vertigo": "dolly_out", "optical_zoom_out": "static", "optical_zoom_in": "static",
                             "tilt_up": "static",
                             "bullet_time": "orbit_90",
                             "through_object": "dolly_out", "pedestal_down": "pedestal_up"}


# Moves whose one still must catch a moment at its peak: the action is described in the still (where it freezes) and
# never in the video prompt (where LTX would play it out, which is how the old bullet time failed). The video prompt
# adds the time-freeze sentence, so the world holds while the camera moves.
# Keyframed moves whose hero must be framed for the move (a one-still move uses START_FRAMING): the end still is edited
# from this hero, so the hero has to be where the move starts.
HERO_FRAMING: dict[str, str] = {
    "crane_down": "Framed as a wide shot from high up, looking down over the subject and the whole setting.",
}
HERO_MOMENT: dict[str, str] = {
    "bullet_time": "The moment is caught at its peak, frozen mid-motion, with everything in the air suspended in place.",
}


# A rolled frame is made, not asked for. Image models draw a level horizon however the prompt words it, and LTX 2.5
# levels a canted first frame back out within the shot (both seen on real renders, Oct 25). So a rolled move is shot
# level and static, larger than the frame, and the finished video is turned in code and cropped back to the frame:
# the tilt holds exactly from the first frame to the last, and nothing is upscaled. The hero leaves room for the crop.
ROLLS: dict[str, float] = {"dutch_angle": 15.0}


def move_words(move_id: str) -> dict[str, str | None]:
    """What the default prompt style tells LTX 2.5 about a move (at the default speed), and how a move made in code is
    made. The Lobby's move page shows both, so the words on screen are the words the model reads."""
    shot = get_move("static" if move_id in ROLLS else PROMPT_AS.get(move_id, move_id))
    phrase = PHRASES_V2.get(shot.id, shot.phrase)
    text = phrase if shot.id in _NO_SPEED else f"{phrase.rstrip('.')}, moving {SPEEDS['steady']}."
    parts = [text, ENDS.get(shot.id, "")]
    if move_id in HERO_MOMENT:
        parts.append(EFFECTS["time_freeze"])
    made = None
    if move_id in MIRRORS:
        made = f"Rendered as its mirror image ({get_move(MIRRORS[move_id]).label.lower()}), then flipped back in code."
    elif move_id in REVERSES:
        made = f"Rendered as its reverse ({get_move(PROMPT_AS[move_id]).label.lower()}), then played backwards in code."
    elif move_id in REFRAMES:
        note = REFRAMES[move_id][2]
        made = f"{note[0].upper()}{note[1:].rstrip('.')}."
        if move_id in TRACKED:
            made += f" The zoom follows the {TRACKED[move_id]} it finds in the render."
    elif move_id in ROLLS:
        made = f"Rendered level, then turned {ROLLS[move_id]:g} degrees in code."
    return {"words": " ".join(part for part in parts if part), "made": made}


def compile_still_prompt(rig: CameraRig, subject: str, *, one_still: bool | None = None, action: str | None = None) -> str:
    """Prompt for the hero still: the rig's look, with no motion words. A shot rendered from this one still
    (`one_still`, by default whenever the move is not keyframed) also gets the framing its move needs. A move that
    freezes a moment (HERO_MOMENT) gets that clause, with the action said here instead of in the video prompt."""
    rig.validate()
    look = (
        f"Photographed on {SENSORS[rig.sensor]} with {_lens_words(rig)}, {APERTURES[rig.aperture]}; "
        f"{LIGHTING[rig.lighting]}{_grade_words(rig)}."
    )
    if one_still is None:
        one_still = get_move(rig.movement).mode != "keyframed"
    framing = f" {START_FRAMING[rig.movement]}" if one_still and rig.movement in START_FRAMING else ""
    if not one_still and rig.movement in HERO_FRAMING:
        framing = f" {HERO_FRAMING[rig.movement]}"
    if rig.movement in HERO_MOMENT:
        sentence = action_sentence(action)
        framing += f"{' ' + sentence if sentence else ''} {HERO_MOMENT[rig.movement]}"
    return f"{subject.strip().rstrip('.')}.{framing} {look} Cinematic still frame, no text, no watermark."


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
                 prompt_only: bool = False, single_pass: bool | None = None,
                 line: str | None = None, delivery: str = "natural", language: str | None = None,
                 action: str | None = None) -> ShotPlan:
    """Turn a rig and a subject into prompts, an anchor plan and the segments to render.

    `prompt_only` renders a keyframed move from one still and a camera instruction instead of planning
    anchor stills: cheaper, with no approvals, and the baseline keyframing is compared against.
    `single_pass` (None: the module's SINGLE_PASS) renders a move of three or more stills as one LTX
    generation with the middle stills guided inside it, instead of one first-last-frame segment per pair.
    A transformation (TRANSFORMATIONS) edits the last still into the end state, so a one-still move gains
    a second still and renders first-to-last like a keyframed one.
    `action` (what happens) is a sentence in the video prompt only, so the stills show the moment before it.
    """
    rig.validate()
    require_safe(subject, audio, line, language)
    dialogue = dialogue_plan(line, delivery, language)  # validates the delivery and the line's length
    action_text = action_words(action)  # validates the action's length and words
    move = get_move(rig.movement)
    if move.id in HERO_MOMENT and rig.angle != ANGLE_DEFAULT:
        raise ValueError(f"{move.label} circles the moment from the camera as shot; leave the start angle as shot")
    reverse = PROMPT_AS[move.id] if move.id in REVERSES else None
    if reverse:  # the picture plays backwards, so anything that happens in it would run backwards too
        made_from = f"{move.label} is made from a {get_move(reverse).label.lower()} played backwards"
        if action_text:
            raise ValueError(f"{made_from}, so an action would run backwards; leave the action out")
        if dialogue:
            raise ValueError(f"{made_from}, so the lips would move backwards against the words; leave the line out")
        if rig.effect and rig.effect != "none":
            raise ValueError(f"{made_from}, so an effect would run backwards (rain would rise, a change would undo itself); leave the effect out")
    if single_pass is None:
        single_pass = SINGLE_PASS
    notes: list[str] = []
    anchors = [AnchorSpec(0, "hero")]
    segments: list[SegmentSpec] = []
    mode = move.mode
    fx = TRANSFORMATIONS.get(rig.effect)
    if prompt_only and mode == "keyframed":
        mode = "prompt_only"
        notes.append("quick mode: one still and a camera instruction, no anchor stills")
        if move.id in RETURNS:
            notes.append("quick mode: nothing ties the last frame to the first, so the shot may not end where it began")
    if mode == "keyframed":
        for i in range(1, move.anchors):
            if move.id in RETURNS and i == move.anchors - 1:
                anchors.append(AnchorSpec(i, "repeat_hero"))
            else:
                anchors.append(AnchorSpec(i, "edit", move.edits[i - 1]))
        if fx:
            last = anchors[-1]
            if last.role == "repeat_hero":
                notes.append("transformation: the loop ends on the transformed still, so it no longer flows back into its first frame"
                             if move.id == "loop" else
                             "transformation: the full orbit ends on the transformed still instead of the hero")
                edit = fx.edit
            else:
                edit = f"{(last.edit_prompt or '').rstrip('.')}. {fx.edit}"
            anchors[-1] = AnchorSpec(last.index, "transform", edit, check_identity=fx.keeps_identity)
        count = move.anchors - 1
        if single_pass and count >= 2:
            total = rig.duration_seconds
            mids = tuple((k, mid_frame_index(k, move.anchors, total)) for k in range(1, move.anchors - 1))
            segments = [SegmentSpec(0, 0, move.anchors - 1, total, "ltx25_flf2v", mids=mids)]
            notes.append(f"one pass: {len(mids)} middle still{'s' if len(mids) != 1 else ''} guided inside the shot")
        else:
            per = max(2, round(rig.duration_seconds / count))
            total = per * count
            if total != rig.duration_seconds:
                notes.append(f"duration {rig.duration_seconds}s becomes {total}s ({count} segments of {per}s)")
            segments = [SegmentSpec(i, i, i + 1, per, "ltx25_flf2v") for i in range(count)]
    else:
        total = rig.duration_seconds
        if fx:  # the end state is a second still edited from the hero; LTX renders the change between the two
            anchors.append(AnchorSpec(1, "transform", fx.edit, check_identity=fx.keeps_identity))
            segments = [SegmentSpec(0, 0, 1, total, "ltx25_flf2v")]
        else:
            segments = [SegmentSpec(0, 0, None, total, "ltx25_i2v")]
    if fx:
        notes.append(f"transformation ({fx.label.lower()}): the last still is edited into the end state and LTX renders the change")
    angle = angle_plan(rig.angle)
    if angle:
        notes.append(f"angled: the hero is re-shot from {angle['label'].lower()} before the move")
    mirror = MIRRORS.get(move.id)
    if mirror:
        notes.append(f"mirrored: the hero is flipped, the {get_move(mirror).label.lower()} is rendered on it, and the video "
                     "is flipped back in code, so the camera travels the other way through the same scene")
    if reverse:
        notes.append(f"reversed: the {get_move(reverse).label.lower()} is rendered from your still and the picture is "
                     "played backwards in code, so the camera travels the other way; the sound plays as rendered")
        notes.append("Your still is where the shot ends.")
    reframe = None
    if move.id in REFRAMES:
        zoom, height, how = REFRAMES[move.id]
        reframe = {"zoom": zoom, "height": height, "how": how}
        note = f"made in code: {how}"
        if move.id in TRACKED:
            reframe["track"] = TRACKED[move.id]
            note += (f"; the zoom follows the {TRACKED[move.id]} it finds in the render, or runs {zoom[0]:g}x to "
                     f"{zoom[1]:g}x when too few frames show one")
        notes.append(note)
    roll = ROLLS.get(move.id)
    if roll:
        notes.append(f"rolled: the shot is rendered level (larger where the template allows), then the video is turned "
                     f"{roll:g} degrees in code and cropped to the frame, so the tilt holds from the first frame to the last")
    if move.id in HERO_MOMENT:
        notes.append(f"made as an {get_move(PROMPT_AS[move.id]).label.lower()} around one still of the moment at its peak, "
                     "with the world frozen while the camera moves")
    if action_text and move.id in HERO_MOMENT:
        notes.append(f"action: {move.label.lower()} catches it at its peak in the still and holds it frozen while the camera moves")
    elif action_text and mode == "keyframed":  # quick mode has already made a keyframed move prompt_only
        notes.append("action: a keyframed move pins its first and last stills to the same moment, so the action may "
                     "barely move; quick mode or a one-still move gives it room")
    if dialogue:
        notes.append("dialogue: LTX 2.5 speaks the line with the picture")
    return ShotPlan(
        rig=rig, move_id=move.id, mode=mode,
        prompt=compile_prompt(rig, subject, audio, line=line, delivery=delivery, language=language,
                              action=None if move.id in HERO_MOMENT else action),
        anchors=tuple(anchors), segments=tuple(segments), total_seconds=total, notes=tuple(notes),
        transformation=rig.effect if fx else None, angle=angle, dialogue=dialogue, action=action_text, roll=roll,
        mirror=mirror, reframe=reframe, reverse=reverse,
    )


def catalog() -> dict[str, Any]:
    """Everything the UI needs to render the rig console and the Move Pad."""
    return {
        "groups": [{"id": gid, "label": label} for gid, label in GROUPS.items()],
        "moves": [m.describe() for m in MOVES.values()],
        "options": {
            "sensor": list(SENSORS), "lens": list(LENSES), "aperture": list(APERTURES),
            "lighting": list(LIGHTING), "speed": list(SPEEDS), "effect": list(EFFECT_IDS), "grade": list(GRADES),
            "score": list(SCORES), "soundscape": list(SOUNDSCAPES),
        },
        # every effect with its kind: a prompt preset (one sentence) or a keyframed transformation (an edited end still)
        "effects": [
            *({"id": k, "label": k.replace("_", " ").capitalize(), "kind": "prompt", "tested": k in VALIDATED_EFFECTS}
              for k in EFFECTS),
            *({"id": k, "label": t.label, "kind": "keyframed", "tested": k in VALIDATED_EFFECTS}
              for k, t in TRANSFORMATIONS.items()),
        ],
        "effects_tested": sorted(VALIDATED_EFFECTS),
        "single_pass": SINGLE_PASS,
        # where the camera may start: the stops of the three dials, the default (the hero as shot) and the tested angles
        "angles": {
            "azimuths": [{"id": k, "label": s.label, "degrees": s.value} for k, s in AZIMUTHS.items()],
            "elevations": [{"id": k, "label": s.label, "degrees": s.value} for k, s in ELEVATIONS.items()],
            "distances": [{"id": k, "label": s.label, "scale": s.value} for k, s in DISTANCES.items()],
            "default": ANGLE_DEFAULT, "tested": sorted(ANGLES_TESTED),
        },
        "from_image_tested": FROM_IMAGE_TESTED,
        "face_only_tested": FACE_ONLY_TESTED,  # the face-only Re-shoot: a Cast's face on a clip's first frame, then re-performed
        # a spoken line: the deliveries to pick from, the length limits and whether a real render checked it
        "dialogue": {
            "deliveries": [{"id": k, "label": k.capitalize()} for k in DELIVERIES],
            "tested": DIALOGUE_TESTED, "dub_tested": DUB_TESTED, "max_chars": LINE_MAX, "language_max_chars": LANGUAGE_MAX,
        },
        # what happens in the shot (the video prompt only): the longest action it takes
        "action_max": ACTION_MAX,
        # one still changed by words: the presets, the lights the relight picker offers, and which a real render checked
        "edits": {
            "presets": [{"id": k, "label": e.label, "needs_cast": e.needs_cast, "needs_detail": e.needs_detail,
                         "tested": k in EDITS_TESTED} for k, e in EDITS.items()],
            "lights": [{"id": k, "label": k.capitalize()} for k in LIGHTS], "max_chars": EDIT_DETAIL_MAX,
        },
        # one still re-shot as a board of setups: the positions in reading order and whether a board has been checked
        "shots": {
            "board": [{"angle": a, "label": label, "angle_tested": a in ANGLES_TESTED} for a, label in SHOTS_BOARD],
            "tested": SHOTS_TESTED, "seconds_each": SHOTS_SECONDS_EACH,
        },
        # a bridge between two takes: the styles, whether a real render checked each, and the lengths LTX can do
        "transitions": {
            "styles": [{"id": k, "label": t.label, "tested": k in TRANSITIONS_TESTED} for k, t in TRANSITIONS.items()],
            "default": TRANSITION_DEFAULT, "seconds": list(TRANSITION_SECONDS), "idea_max": TRANSITION_IDEA_MAX,
        },
        # a finished take enlarged to 2K or 4K: the targets (pixels on the long side) and whether a real render checked it
        "upscale": {
            "targets": [{"id": k, "label": k.upper(), "long_side": side} for k, side in UPSCALE_TARGETS.items()],
            "tested": UPSCALE_TESTED,
        },
        # extend a finished take from its last frame: the lengths LTX can do and whether a real render checked it
        "extend": {"seconds": list(EXTEND_SECONDS), "tested": EXTEND_TESTED},
        "quality": quality.describe(),
        "quality_tested": sorted(quality.VALIDATED_QUALITY),
        "defaults": asdict(CameraRig()),
        "limits": {"duration_seconds": [MIN_DURATION_SECONDS, MAX_DURATION_SECONDS],
                   "focal_length_mm": [MIN_FOCAL_MM, MAX_FOCAL_MM]},
    }
