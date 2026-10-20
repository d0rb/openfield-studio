"""The slot contract each workflow template must satisfy for the pipeline to drive it.

The pipeline only ever talks to logical slot names. Whether a template is the real graph exported
from ComfyUI or a unit-test miniature, `check_contract` says whether it can be driven.
"""
from __future__ import annotations

from dataclasses import dataclass

from .workflows import Template


@dataclass(frozen=True)
class Contract:
    slots: dict[str, str]  # slot name -> kind
    outputs: tuple[str, ...]
    optional: frozenset[str] = frozenset()


CONTRACTS: dict[str, Contract] = {
    "qwen21_t2i": Contract(
        {"prompt": "text", "seed": "seed", "width": "int", "height": "int"}, ("image",)),
    "qwen21_edit": Contract(
        {"prompt": "text", "seed": "seed", "base_image": "image", "refs": "image_list",
         "custom_size": "bool", "width": "int", "height": "int"},
        ("image",), frozenset({"refs"})),
    "ltx25_i2v": Contract(
        {"prompt": "text", "seed": "seed", "duration": "int", "width": "int", "height": "int",
         "first_frame": "image"}, ("video",)),
    "ltx25_flf2v": Contract(
        {"prompt": "text", "seed": "seed", "duration": "int", "width": "int", "height": "int",
         "first_frame": "image", "last_frame": "image"}, ("video",)),
    "wan_animate2": Contract(
        {"prompt": "text", "motion_prompt": "text", "seed": "seed", "reference_image": "image",
         "pose_video": "video", "width": "int", "height": "int"},
        ("video",), frozenset({"motion_prompt", "width", "height"})),
}


def check_contract(name: str, template: Template) -> list[str]:
    """Problems that stop the pipeline driving this template; empty means it satisfies the contract."""
    contract = CONTRACTS.get(name)
    if contract is None:
        return [f"no contract is defined for template {name!r}"]
    issues: list[str] = []
    for slot_name, kind in contract.slots.items():
        slot = template.slots.get(slot_name)
        if slot is None:
            issues.append(f"missing slot {slot_name!r} ({kind})")
        elif slot.kind != kind:
            issues.append(f"slot {slot_name!r} is {slot.kind!r}, the pipeline needs {kind!r}")
    for output in contract.outputs:
        if output not in template.outputs:
            issues.append(f"missing output {output!r}")
    return issues
