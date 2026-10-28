#!/usr/bin/env python3
"""Fill the three publish-time links in the public documents in one go, once they exist.

    python scripts/fill_links.py --repo https://github.com/<account>/openfield-studio \\
        --site https://<account>.github.io/openfield-studio/ --video https://youtu.be/<id> [--dry-run]

It replaces <repo link>, <try-it link> and <video link> wherever the release check looks for them (README.md,
SUBMISSION.md, PRODUCT.md, docs/, showcase/README.md, openfield/workflows/README.md), refuses an address that is not
https, and says what it changed. Run `python scripts/release_check.py` after it: the gate then passes on links.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDERS = {"<repo link>": "repo", "<try-it link>": "site", "<video link>": "video"}


def _gate_pattern():
    """The release check's own pattern for a link still to fill, so this script and the gate never disagree."""
    spec = importlib.util.spec_from_file_location("_release_check", Path(__file__).with_name("release_check.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)  # its dataclasses look themselves up there
    spec.loader.exec_module(module)
    return module.PLACEHOLDER_LINK


PLACEHOLDER_LINK = _gate_pattern()


def public_docs(root: Path) -> list[Path]:
    """The documents the release check reads for unfinished markers."""
    found = [root / name for name in ("README.md", "SUBMISSION.md", "PRODUCT.md")]
    found += sorted((root / "docs").rglob("*.md")) if (root / "docs").is_dir() else []
    found += [root / "showcase" / "README.md", root / "openfield" / "workflows" / "README.md"]
    return [p for p in found if p.is_file()]


def check_url(name: str, url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or not parts.netloc or " " in url.strip():
        raise ValueError(f"--{name} must be a full https address, not {url!r}")
    return url.strip()


def fill(root: Path, links: dict[str, str], *, dry_run: bool = False) -> list[str]:
    """Replace every placeholder in the public documents; return one line per change ("file:line: old -> new")."""
    changes = []
    for path in public_docs(root):
        text = path.read_text(encoding="utf-8")
        lines = text.split("\n")
        changed = False
        for number, line in enumerate(lines, start=1):
            new = line
            for marker, key in PLACEHOLDERS.items():
                if marker in new and links.get(key):
                    new = new.replace(marker, links[key])
            if new != line:
                changes.append(f"{path.relative_to(root).as_posix()}:{number}: {new.strip()[:110]}")
                lines[number - 1] = new
                changed = True
        if changed and not dry_run:
            path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return changes


def remaining(root: Path) -> list[str]:
    """Links still to fill in the public documents, as the release check sees them (any "<... link>")."""
    left = []
    for path in public_docs(root):
        for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
            left += [f"{path.relative_to(root).as_posix()}:{number}: {m.group(0)}" for m in PLACEHOLDER_LINK.finditer(line)]
    return left


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True, help="the public repository, https://github.com/<account>/openfield-studio")
    parser.add_argument("--site", required=True, help="the hosted copy, https://<account>.github.io/openfield-studio/")
    parser.add_argument("--video", required=True, help="the demo video, where it is posted")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--dry-run", action="store_true", help="print the changes, write nothing")
    args = parser.parse_args(argv)
    try:
        links = {key: check_url(key, getattr(args, key)) for key in ("repo", "site", "video")}
    except ValueError as exc:
        print(f"fill_links: {exc}", file=sys.stderr)
        return 2
    root = Path(args.root).resolve()
    changes = fill(root, links, dry_run=args.dry_run)
    for line in changes:
        print(line)
    if args.dry_run:
        print(f"{len(changes)} line(s) would change; nothing was written.")
        return 0
    left = remaining(root)
    if left:
        print("still unfilled:\n  " + "\n  ".join(left), file=sys.stderr)
        return 1
    print(f"{len(changes)} line(s) filled. Now run: python scripts/release_check.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
