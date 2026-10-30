#!/usr/bin/env python3
"""Put rendered pictures into openfield/web/art with their provenance.

    python scripts/install_art.py --from out/art --jobs docs/art-jobs-r16.json

For each job whose PNG was rendered, this writes the web copy as webp, its sidecar (the prompt and when it was made)
and its manifest entry (size, bytes, sha256 and what it was made from), so every shipping raster carries the same
record a take's receipt does. It refuses to install a picture whose render sidecar is missing, because an art file
without its prompt and workflow hash is not provenance.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "openfield" / "web" / "art"
MANIFEST = ART / "manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="src", required=True, type=Path, help="where render_art.py wrote the PNGs")
    parser.add_argument("--jobs", required=True, type=Path, help="the same job list that was rendered")
    parser.add_argument("--quality", type=int, default=82, help="webp quality (the plates are mostly black and compress hard)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    jobs = json.loads(args.jobs.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = {e["file"]: e for e in manifest["files"]}
    now = datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")
    installed = 0

    for job in jobs:
        name = job["file"]
        stem = Path(name).stem
        png = args.src / f"{stem}.png"
        made_path = args.src / f"{stem}.json"
        if not png.is_file():
            print(f"skip {name}: not rendered", file=sys.stderr)
            continue
        if not made_path.is_file():
            print(f"skip {name}: no render sidecar, so no provenance", file=sys.stderr)
            continue
        made = json.loads(made_path.read_text(encoding="utf-8"))
        made["render"] = png.name
        with Image.open(png) as im:
            picture = im.convert("RGB")
            # a crop the job asked for, recorded with the picture: a text-to-image model will put the lamp body in
            # the frame when it is told to draw a beam, and an overlay wants the light alone, entering from off screen
            crop = job.get("crop_top", 0)
            if crop:
                picture = picture.crop((0, int(crop), picture.width, picture.height))
                made["crop_top"] = int(crop)
            # a texture is read at low opacity under a surface, not looked at: it ships at the width it is used at
            cap = job.get("max_width", 0)
            if cap and picture.width > cap:
                picture = picture.resize((cap, round(picture.height * cap / picture.width)), Image.LANCZOS)
                made["resized_to"] = cap
            width, height = picture.size
            if args.dry_run:
                print(f"would write {name} ({width}x{height})")
                continue
            picture.save(ART / name, "WEBP", quality=int(job.get("quality", args.quality)), method=6)
        data = (ART / name).read_bytes()
        (ART / f"{name}.json").write_text(json.dumps({"prompt": job["prompt"], "createdAt": now}, indent=2) + "\n",
                                          encoding="utf-8")
        entry = {"file": name, "width": width, "height": height, "bytes": len(data),
                 "sha256": hashlib.sha256(data).hexdigest(), "made_from": made}
        if name in entries:
            entries[name].clear()
            entries[name].update(entry)
        else:
            manifest["files"].append(entry)
            entries[name] = entry
        installed += 1
        print(f"{name}: {width}x{height}, {len(data) // 1024} KB")

    if not args.dry_run and installed:
        manifest["files"].sort(key=lambda e: e["file"])
        manifest["made"] = f"{manifest.get('made', '')}; {now[:10]}".lstrip("; ")
        MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(f"{installed} installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
