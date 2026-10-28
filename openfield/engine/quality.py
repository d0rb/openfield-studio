"""Quality tiers for a Direct take: what a tier changes, said honestly.

The templates fix most of their numbers: LTX 2.5 is a distilled model with its sigma schedules written into the graph, the
frame rate is 24 and the sound is always on. What a tier can change is the size of the stills and of the video, and the
sampling steps of the Qwen-Image stills. So a tier is sizes plus still steps, nothing else, and the interface says so.

Every size satisfies the templates' snapping rules (the Qwen graphs and the first-and-last-frame LTX graph take multiples of
16, the still-to-video LTX graph multiples of 64, its half-size first pass landing on a multiple of 32), with one known
exception kept on purpose: standard's 1280×720 video snaps to 1280×704 on the still-to-video graph, as it always did, and
the receipt records the snap. Standard is exactly what the app rendered before tiers existed, so recorded takes keep their
recipes and their fingerprints.
"""
from __future__ import annotations

from typing import Any

TIERS: dict[str, dict[str, Any]] = {
    "draft": {"label": "Draft", "still": (896, 512), "video": (896, 512), "steps": 12,
              "what": "896×512 stills and video, 12 still steps: a quick look at the shot"},
    "standard": {"label": "Standard", "still": (1344, 768), "video": (1280, 720), "steps": 25,
                 "what": "1344×768 stills, 1280×720 video (704 high on the still-to-video graph), 25 still steps"},
    "fine": {"label": "Fine", "still": (1920, 1088), "video": (1920, 1088), "steps": 30,
             "what": "1920×1088 stills and video, 30 still steps: the slowest, for a final"},
}
DEFAULT = "standard"
# a tier is marked tested only after a real render at that tier has been checked by eye (the rule the moves follow)
VALIDATED_QUALITY: frozenset[str] = frozenset({"draft", "fine", "standard"})
FINE_FALLBACK = (1600, 896)  # if 1920×1088 does not fit the box's memory, this is the one-line change for the fine tier


def check(tier: str | None) -> str:
    """The tier's id, or a ValueError naming the choices."""
    chosen = tier or DEFAULT
    if chosen not in TIERS:
        raise ValueError(f"unsupported quality: {chosen} (one of {', '.join(TIERS)})")
    return chosen


def _oriented(size: tuple[int, int], orientation: str) -> tuple[int, int]:
    width, height = size
    return (height, width) if orientation == "portrait" else (width, height)


def still_size(tier: str, orientation: str = "landscape") -> tuple[int, int]:
    return _oriented(TIERS[check(tier)]["still"], orientation)


def video_size(tier: str, orientation: str = "landscape") -> tuple[int, int]:
    return _oriented(TIERS[check(tier)]["video"], orientation)


def steps(tier: str) -> int:
    return int(TIERS[check(tier)]["steps"])


def describe() -> list[dict[str, Any]]:
    """The tiers as the catalog ships them: id, label, what changes, and whether a real render checked it."""
    return [{"id": tier, "label": spec["label"], "what": spec["what"], "still": list(spec["still"]),
             "video": list(spec["video"]), "steps": spec["steps"], "tested": tier in VALIDATED_QUALITY}
            for tier, spec in TIERS.items()]
