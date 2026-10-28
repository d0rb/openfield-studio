#!/usr/bin/env python3
"""Regenerate openfield/engine/manifest.json from the pinned official ComfyUI templates.

The manifest is the single source for (a) which model files each workflow needs and (b) the
allowlist of node classes the open-weights audit accepts. It records the template commit and a
SHA-256 per template so the provenance of every allowed node and model is checkable.

    python scripts/gen_manifest.py            # fetches the pinned commit from GitHub
    python scripts/gen_manifest.py --ref main # try newer templates (review the diff!)
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_template_models as ftm  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "openfield" / "engine" / "manifest.json"


def models_used_by_our_workflows(known: set[str]) -> dict[str, set[str]]:
    """Model file -> our workflow names that still load it after patching and pruning.

    This, not the official templates' lists, is what a render box needs: the templates also list the
    prompt-enhancer encoders, which our workflows remove, and some files the name patterns misjudge.
    """
    from export_templates import OFFICIAL

    from openfield.engine.workflows import WORKFLOW_DIR, load_template, sample_values

    used: dict[str, set[str]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        files = {"image": Path(tmp) / "x.png", "video": Path(tmp) / "x.mp4"}
        for path in files.values():
            path.write_bytes(b"")
        for ours in OFFICIAL:
            try:
                template = load_template(ours, WORKFLOW_DIR)
            except FileNotFoundError:
                return {}  # workflows not exported yet: no way to know, so nothing is marked
            graph = template.patch(sample_values(template, files["image"], files["video"])).graph
            for node in graph.values():
                for value in node.get("inputs", {}).values():
                    if isinstance(value, str) and value in known:
                        used.setdefault(value, set()).add(ours)
    return used


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default=ftm.DEFAULT_REF)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    templates: dict[str, dict] = {}
    models: dict[str, dict] = {}
    allowed: set[str] = set()
    for group, names in ftm.GROUPS.items():
        for name in names:
            data, digest, size = ftm.fetch_template(name, args.ref)
            types = ftm.collect_node_types(data)
            allowed.update(types)
            templates[name] = {
                "group": group,
                "sha256": digest,
                "bytes": size,
                "node_types": types,
                "models": [],
            }
            added = ftm.ADDED_NODE_TYPES.get(name)
            if added:  # our workflow adds core classes to this template: say so, and allow them
                templates[name]["added_node_types"] = sorted(added)
                allowed.update(added)
            for item in ftm.collect_models(data):
                parts = ftm.hf_parts(item["url"])
                if parts is None:
                    continue
                repo, revision, path = parts
                templates[name]["models"].append(item["name"])
                entry = models.setdefault(
                    item["name"],
                    {
                        "name": item["name"],
                        "directory": item.get("directory") or path.split("/")[0],
                        "repo": repo,
                        "revision": revision,
                        "path": path,
                        "url": item["url"],
                        **ftm.KNOWN_FILES.get(item["name"], {}),  # size and sha256, where they were recorded
                        "optional": ftm.is_optional(item["name"]),
                        "templates": [],
                    },
                )
                entry["templates"].append(name)
            templates[name]["models"].sort()

    used = models_used_by_our_workflows(set(models))
    for entry in models.values():
        if used:  # decided by what our workflows really load, not by file-name patterns
            entry["required"] = entry["name"] in used
            entry["optional"] = not entry["required"]
            entry["used_by"] = sorted(used.get(entry["name"], ()))
        else:
            entry["required"] = not entry["optional"]

    manifest = {
        "source": {
            "repo": ftm.TEMPLATE_REPO,
            "ref": args.ref,
            "generated": datetime.date.today().isoformat(),
        },
        "templates": templates,
        "models": sorted(models.values(), key=lambda m: (m["directory"], m["name"])),
        "allowed_node_types": sorted(allowed),
    }
    out = Path(args.out)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"wrote {out}: {len(templates)} templates, {len(models)} model files, "
        f"{len(allowed)} allowed node classes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
