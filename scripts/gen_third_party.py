#!/usr/bin/env python3
"""Write THIRD_PARTY_MODELS.md from the model registry the open-weights audit uses.

    python scripts/gen_third_party.py

The registry (openfield/engine/models.py + manifest.json) is the single source of truth, so this
document cannot drift from what the app actually audits. Confirm each licence on its model card
before publishing.
"""
from __future__ import annotations

import sys
from pathlib import Path

from openfield.engine.models import LICENSES, REPO_LICENSE, manifest, registry

OUT = Path(__file__).resolve().parents[1] / "THIRD_PARTY_MODELS.md"

HEADER = """# Third-party models and licences

OpenField Studio's own code is MIT. It does not bundle any model weights: they are downloaded
from Hugging Face by the official ComfyUI templates (see `docs/POD.md`) and run on Comfy Cloud or
your own GPU box. Every weight file below is **open-weights** (downloadable and runnable locally).
"Open weights" is not the same as "open source": each model has its own licence, summarised here.
Check the model card before any commercial use.

The app enforces this list at runtime: before a workflow is submitted, the open-weights audit
refuses any node that is not in the allowlist taken from the official templates, and any weight
file that is not listed here. The audit result is stored in every take's receipt.

"""

NOTES = """
## Notes

- **Qwen-Image 2.1** is under the Qwen Research License: non-commercial use only, and products
  built with it must show "Built with Qwen". The still-image step is a swappable slot.
- **LTX 2.5** is gated on Hugging Face (one click on "Agree and Access" shares your contact
  details with Lightricks). Free commercial use applies below $10M annual revenue.
- **Real-ESRGAN** (the video upscaler, 67 MB, not gated) is BSD-3-Clause as the Comfy-Org repack's model card
  declares. The upstream repository states BSD-3-Clause for its code and names no separate licence for the
  weights, so the weights' own terms are not confirmed from the authors.
- **Face check** (optional, local): YuNet (MIT) and SFace (Apache-2.0) from the OpenCV Zoo, downloaded
  on demand and checked against pinned SHA-256 hashes.
- This list covers weights. Python dependencies carry their own licences (see `pyproject.toml`).
"""


def render() -> str:
    reg = registry()
    required = {m["name"]: m.get("required", True) for m in manifest()["models"]}
    lines = [HEADER]
    by_license: dict[str, list] = {}
    for info in reg.values():
        by_license.setdefault(info.license_id, []).append(info)
    for license_id, models in sorted(by_license.items()):
        lic = LICENSES[license_id]
        lines.append(f"## {lic.name}\n")
        lines.append(f"- Commercial use: {lic.commercial}.")
        if lic.attribution:
            lines.append(f"- Required attribution: \"{lic.attribution}\".")
        lines.append(f"- Licence text: {lic.url}\n")
        lines.append("| File | Role | Source repo | Loaded by OpenField |\n|---|---|---|---|")
        for m in sorted(models, key=lambda m: (m.role, m.file)):
            used = "yes" if required.get(m.file, True) else "no (listed by the official templates only)"
            lines.append(f"| `{m.file}` | {m.role} | [{m.repo}](https://huggingface.co/{m.repo}) | {used} |")
        lines.append("")
    lines.append(NOTES)
    source = manifest()["source"]
    lines.append(f"\n_Generated from the official templates at `{source['repo']}@{source['ref'][:12]}`; "
                 f"repo to licence map: {', '.join(f'{repo} -> {lic_id}' for repo, lic_id in REPO_LICENSE.items())}._\n")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Write the document, or with --check fail when the file on disk is stale."""
    text = render()
    if argv and "--check" in argv:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if current != text:
            print(f"{OUT.name} is out of date: run python scripts/gen_third_party.py", file=sys.stderr)
            return 1
        print(f"{OUT.name} is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT} ({len(registry())} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
