#!/usr/bin/env python3
"""Check every workflow template against the pipeline contract and the open-weights audit.

    python scripts/validate_workflows.py                  # the bundled openfield/workflows/
    python scripts/validate_workflows.py --dir some/dir   # any directory of <name>.api.json + .slots.json
    python scripts/validate_workflows.py --object-info http://127.0.0.1:9188
                                                          # also compare each numeric slot's range with
                                                          # the real node limits reported by ComfyUI

Exit status is 0 only when every template satisfies its slot contract, has no dangling links, every
slot points at a real node/input, and the open-weights audit passes (allowlisted nodes, known
weights). Run it after exporting templates and before committing them.

With --object-info, every int/float/seed slot is also checked against the limits ComfyUI itself reports
for that node input (`/object_info`): a slot allowing a value the node would reject is a template bug.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

from openfield.engine.contract import CONTRACTS, check_contract
from openfield.engine.workflows import WORKFLOW_DIR, load_template


def validate(directory: Path) -> dict[str, list[str]]:
    results: dict[str, list[str]] = {}
    for name in CONTRACTS:
        try:
            template = load_template(name, directory)
        except FileNotFoundError:
            results[name] = ["not found (needs <name>.api.json and <name>.slots.json)"]
            continue
        except (ValueError, KeyError) as exc:
            results[name] = [f"unreadable: {exc}"]
            continue
        results[name] = check_contract(name, template) + template.problems()
    return results


def fetch_object_info(base_url: str) -> dict:
    with urllib.request.urlopen(base_url.rstrip("/") + "/object_info", timeout=60) as response:
        return json.loads(response.read())


def check_ranges(name: str, template, info: dict) -> list[str]:
    """Numeric slots whose range is wider than what the target node accepts."""
    problems = []
    for slot in template.slots.values():
        if slot.kind not in {"int", "float", "seed"}:
            continue
        node = template.graph.get(slot.node) or {}
        spec = info.get(node.get("class_type", ""))
        if spec is None:
            problems.append(f"slot {slot.name!r}: class {node.get('class_type')!r} is unknown to ComfyUI")
            continue
        inputs = {**spec["input"].get("required", {}), **spec["input"].get("optional", {})}
        definition = inputs.get(slot.input)
        if not definition or not isinstance(definition[0], str) or definition[0] not in {"INT", "FLOAT"}:
            continue  # dynamic or nested inputs (for example resize_type.width) cannot be range-checked here
        limits = definition[1] if len(definition) > 1 else {}
        low, high = limits.get("min"), limits.get("max")
        for label, value in (("min", slot.min), ("max", slot.max), ("default", slot.default)):
            if value is None:
                continue
            if low is not None and value < low:
                problems.append(f"slot {slot.name!r}: {label} {value} is below the node's minimum {low}")
            if high is not None and value > high:
                problems.append(f"slot {slot.name!r}: {label} {value} is above the node's maximum {high}")
        step = limits.get("step")
        if slot.multiple_of and isinstance(step, int) and step > 1 and slot.multiple_of % step:
            problems.append(f"slot {slot.name!r}: multiple_of {slot.multiple_of} is not a multiple of the node's step {step}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", default=str(WORKFLOW_DIR), help="template directory")
    parser.add_argument("--object-info", metavar="URL", help="ComfyUI URL: also check slot ranges against its node limits")
    args = parser.parse_args(argv)
    results = validate(Path(args.dir))
    if args.object_info:
        info = fetch_object_info(args.object_info)
        for name in results:
            try:
                template = load_template(name, Path(args.dir))
            except (FileNotFoundError, ValueError, KeyError):
                continue
            results[name] += check_ranges(name, template, info)
    bad = 0
    for name, problems in results.items():
        if problems:
            bad += 1
            print(f"[FAIL] {name}")
            for problem in problems:
                print(f"         - {problem}")
        else:
            print(f"[ ok ] {name}")
    print(f"\n{len(results) - bad}/{len(results)} templates usable")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
