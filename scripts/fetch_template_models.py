#!/usr/bin/env python3
"""Download the model files that OpenField's official ComfyUI templates need.

Self-contained on purpose (stdlib + huggingface_hub at download time) so it can be copied to a
rented GPU box on its own. The file list is read from the templates themselves
(`properties.models`: name / directory / url), so nothing is hard-coded and it follows upstream.

    HF_TOKEN=hf_... python fetch_template_models.py --comfy-dir /workspace/ComfyUI
    python fetch_template_models.py --dry-run            # print the plan, download nothing
    python fetch_template_models.py --only wan,qwen      # subset
    python fetch_template_models.py --all                # also the files our workflows do not load

When a manifest.json (the repo's openfield/engine/manifest.json) sits next to this script or in the repo,
the plan comes from it: it is pinned, works offline, and marks which files OpenField's own workflows
really load once their prompt enhancers are removed. Without it the official templates are fetched from
GitHub and a name heuristic guesses (the safe fallback is to pass --all).

The token is read from HF_TOKEN only, passed to huggingface_hub, never printed or written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

TEMPLATE_REPO = "Comfy-Org/workflow_templates"
# Pinned commit (2026-10-16) so a judge reproducing the setup gets the templates we tested.
DEFAULT_REF = "04a508b31bec1818e48122ca0761c1de4140a234"
GROUPS: dict[str, list[str]] = {
    "ltx": ["video_ltx2_5_flf2v", "video_ltx2_5_i2v"],
    "qwen": ["image_qwen_image_2_1_image_edit", "image_qwen_image_2_1_t2i"],
    "wan": ["video_wan_animate2"],
    "esrgan": ["utility-gan_upscaler"],  # Video Upscale: Real-ESRGAN (one 67 MB file, not gated)
}
# Core node classes one of our workflows adds to an official template, by template name. They join the allowlist and are
# recorded under the template's `added_node_types` in the manifest, so an addition is stated, never silent.
# utility-gan_upscaler: its own note says to resize the x4 result to the target with "a resize node"; ImageScale (nodes.py)
# is that node, and official templates such as video_wanmove_480p use it.
ADDED_NODE_TYPES: dict[str, tuple[str, ...]] = {"utility-gan_upscaler": ("ImageScale",)}
# What a template does not say about a file, recorded once from the Hugging Face tree API on 2026-10-23: its size and its
# LFS sha256. gen_manifest.py copies these into the manifest, so a regenerated manifest keeps them.
KNOWN_FILES: dict[str, dict[str, Any]] = {
    "RealESRGAN_x4plus.safetensors": {
        "bytes": 66857836,
        "sha256": "37f9a931c215f040aa6d50f711f2cb115f713c46df1d0d6469a8bd7bfe9a60bb",
    },
}
# Files the templates list but our workflows never need (prompt enhancers, T2V-only upscaler).
OPTIONAL_PATTERNS = ("gemma4_e2b_it", "_pe_i2i", "_pe_t2i", "latent-spatial-upscaler")
UI_ONLY_NODE_TYPES = {"MarkdownNote", "Note", "Reroute", "PrimitiveNode"}
HF_URL = re.compile(r"^https://huggingface\.co/([^/]+/[^/]+)/resolve/([^/]+)/(.+)$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
GATED_HINT = {"Lightricks/LTX-2.5": "https://huggingface.co/Lightricks/LTX-2.5"}


def fetch_template(name: str, ref: str) -> tuple[dict[str, Any], str, int]:
    """Return (parsed JSON, sha256, byte length) of one official template."""
    url = f"https://raw.githubusercontent.com/{TEMPLATE_REPO}/{ref}/templates/{name}.json"
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 (fixed https host)
        raw = resp.read()
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest(), len(raw)


def _walk(node: Any, models: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        listed = node.get("models")
        if isinstance(listed, list):
            for item in listed:
                if isinstance(item, dict) and item.get("url") and item.get("name"):
                    models.append(item)
        for value in node.values():
            _walk(value, models)
    elif isinstance(node, list):
        for value in node:
            _walk(value, models)


def collect_models(template: dict[str, Any]) -> list[dict[str, Any]]:
    """Unique model entries (name, directory, url) found anywhere in a template."""
    found: list[dict[str, Any]] = []
    _walk(template, found)
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in found:
        unique.setdefault((item["name"], item.get("directory", "")), item)
    return list(unique.values())


def collect_node_types(template: dict[str, Any]) -> list[str]:
    """Executable node class names, including those inside subgraph definitions."""
    types: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            nodes = node.get("nodes")
            if isinstance(nodes, list):
                for entry in nodes:
                    kind = entry.get("type") if isinstance(entry, dict) else None
                    if isinstance(kind, str) and not UUID.match(kind):
                        types.add(kind)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(template)
    return sorted(types - UI_ONLY_NODE_TYPES)


def is_optional(name: str) -> bool:
    return any(pattern in name for pattern in OPTIONAL_PATTERNS)


def hf_parts(url: str) -> tuple[str, str, str] | None:
    match = HF_URL.match(url)
    return (match.group(1), match.group(2), match.group(3)) if match else None


def build_plan(groups: list[str], ref: str, include_optional: bool) -> list[dict[str, Any]]:
    plan: dict[str, dict[str, Any]] = {}
    for group in groups:
        for template_name in GROUPS[group]:
            template, _, _ = fetch_template(template_name, ref)
            for item in collect_models(template):
                parts = hf_parts(item["url"])
                if parts is None:
                    print(f"  skipping non-Hugging-Face url: {item['url']}", file=sys.stderr)
                    continue
                repo, revision, path = parts
                entry = plan.setdefault(
                    item["url"],
                    {
                        "name": item["name"],
                        "directory": item.get("directory") or path.split("/")[0],
                        "repo": repo,
                        "revision": revision,
                        "path": path,
                        "optional": is_optional(item["name"]),
                        "templates": [],
                    },
                )
                entry["templates"].append(template_name)
    rows = list(plan.values())
    return rows if include_optional else [row for row in rows if not row["optional"]]


GROUP_OF = {template: group for group, names in GROUPS.items() for template in names}


def find_manifest(explicit: str | None) -> Path | None:
    here = Path(__file__).resolve().parent
    candidates = [Path(explicit)] if explicit else [here / "manifest.json",
                                                    here.parent / "openfield" / "engine" / "manifest.json"]
    return next((c for c in candidates if c.is_file()), None)


def plan_from_manifest(path: Path, groups: list[str], include_optional: bool) -> list[dict[str, Any]]:
    """The download plan from the repo's manifest, honouring its `required` flags."""
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for model in data["models"]:
        wanted = [t for t in model["templates"] if GROUP_OF.get(t) in groups]
        if not wanted:
            continue
        required = model.get("required", not model.get("optional", False))
        if required or include_optional:
            rows.append({**model, "optional": not required, "templates": wanted})
    return rows


def destination(comfy_dir: Path, row: dict[str, Any]) -> Path:
    return comfy_dir / "models" / row["directory"] / row["name"]


def download_root(comfy_dir: Path, row: dict[str, Any]) -> Path:
    """The folder hf_hub_download writes under: it appends the file's path in the repository, and the file must land in
    models/<directory>/<name>. Most repositories keep the directory in that path (diffusion_models/x.safetensors); the
    Real-ESRGAN one keeps its file at the repository's root, so there the folder is models/upscale_models itself."""
    return destination(comfy_dir, row).parents[len(Path(row["path"]).parts) - 1]


def download(row: dict[str, Any], comfy_dir: Path, token: str | None) -> str:
    from huggingface_hub import hf_hub_download  # imported late: dry runs need no extras
    from huggingface_hub.errors import GatedRepoError, HfHubHTTPError

    target = destination(comfy_dir, row)
    if target.exists() and target.stat().st_size > 1_000_000:
        return "present"
    try:
        hf_hub_download(
            repo_id=row["repo"],
            filename=row["path"],
            revision=row["revision"],
            local_dir=str(download_root(comfy_dir, row)),
            token=token,
        )
    except GatedRepoError:
        hint = GATED_HINT.get(row["repo"], f"https://huggingface.co/{row['repo']}")
        return f"GATED - click 'Agree and Access' at {hint}, then re-run"
    except HfHubHTTPError as exc:
        code = getattr(getattr(exc, "response", None), "status_code", "?")
        return f"HTTP {code} from Hugging Face (token missing, wrong scope, or repo not unlocked?)"
    if not target.exists():
        return f"downloaded, but expected file missing at {target}"
    return "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--comfy-dir", default="ComfyUI", help="ComfyUI install root (default ./ComfyUI)")
    parser.add_argument("--only", default=",".join(GROUPS), help="comma list of: " + ", ".join(GROUPS))
    parser.add_argument("--ref", default=DEFAULT_REF, help="git ref of Comfy-Org/workflow_templates")
    parser.add_argument("--all", action="store_true", help="include optional files too")
    parser.add_argument("--manifest", help="manifest.json to plan from (default: next to this script or in the repo)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    args = parser.parse_args(argv)

    groups = [g.strip() for g in args.only.split(",") if g.strip()]
    unknown = [g for g in groups if g not in GROUPS]
    if unknown:
        parser.error(f"unknown group(s): {', '.join(unknown)}")

    manifest = find_manifest(args.manifest)
    if manifest is not None:
        plan = plan_from_manifest(manifest, groups, args.all)
        source = f"manifest {manifest.name}"
    else:
        try:
            plan = build_plan(groups, args.ref, args.all)
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"could not fetch templates from GitHub: {exc}", file=sys.stderr)
            return 2
        source = f"templates @ {args.ref}"

    comfy_dir = Path(args.comfy_dir).expanduser().resolve()
    print(f"{len(plan)} model files for groups {groups} ({source})")
    for row in plan:
        flag = " (optional)" if row["optional"] else ""
        print(f"  {row['repo']:28} {row['directory']:22} {row['name']}{flag}")
    if args.dry_run:
        return 0

    token = os.environ.get("HF_TOKEN") or None
    if token is None:
        print("note: HF_TOKEN is not set; gated repos (Lightricks/LTX-2.5) will refuse.", file=sys.stderr)
    failures = 0
    for row in plan:
        status = download(row, comfy_dir, token)
        print(f"  [{status}] {row['name']}")
        failures += status not in {"ok", "present"}
    print("done." if not failures else f"{failures} file(s) need attention (see above).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
