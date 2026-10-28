#!/usr/bin/env python3
"""Build openfield/web/icons/sprite.svg: the icons the interface uses, taken from Lucide (ISC licence).

    python scripts/build_icons.py --lucide <folder holding Lucide's *.svg files>
    python scripts/build_icons.py --check        # the sprite on disk has exactly the icons the code uses

Lucide is not vendored whole. Get the files with `npm pack lucide-static` and unpack its icons/ folder.
The sprite is checked in so the app needs no build step and no network.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPRITE = ROOT / "openfield" / "web" / "icons" / "sprite.svg"
JS_ROOT = ROOT / "openfield" / "web"

# every icon the interface can draw, by Lucide name
ICONS = [
    # stations (the ticket is the Lobby, the message the Chat room)
    "ticket", "users-round", "clapperboard", "repeat-2", "film", "grid-3x3", "message-square",
    # transport and player
    "play", "pause", "volume-2", "volume-x", "maximize", "repeat", "circle-play",
    # actions
    "x", "check", "upload", "folder-open", "trash-2", "dices", "square", "refresh-cw", "undo-2", "link", "package",
    "file-json", "user-round-plus", "smartphone", "image", "arrow-left-right", "chevrons-right", "send", "columns-2",
    # disclosure
    "chevron-down", "chevron-up", "chevron-right", "chevron-left", "panel-right",
    # state and trust
    "triangle-alert", "circle-alert", "lock", "shield-check", "circle-dashed", "info", "ban", "clock", "cloud",
    "scan-face",
]


SIZES = {"sm", "lg"}  # icon()'s second argument: a size, never a name


def icon_calls(text: str) -> list[str]:
    """The argument text of every icon(...) call, its parentheses balanced (a string's own brackets do not count)."""
    calls = []
    for match in re.finditer(r"\bicon\(", text):
        depth, i, quote = 1, match.end(), ""
        while i < len(text) and depth:
            c = text[i]
            if quote:
                if c == "\\":
                    i += 1
                elif c == quote:
                    quote = ""
            elif c in "\"'`":
                quote = c
            elif c in "([{":
                depth += 1
            elif c in ")]}":
                depth -= 1
            i += 1
        calls.append(text[match.end():i - 1])
    return calls


# a quoted name in a name's place inside an icon(...) call: the first argument, or a branch of ? :, ??, || or &&; a word
# right after a comparison (=== "failed") is a value the code tests, not an icon
ICON_NAME = re.compile(r"""(?:^|\?\??|:|\|\||&&)\s*["']([a-z0-9-]+)["']""")


def used_names() -> set[str]:
    """Icon names the JavaScript and HTML actually reference: every name an icon(...) call can draw, #i-name and data-icon."""
    names: set[str] = set()
    for path in JS_ROOT.rglob("*"):
        if path.suffix not in {".js", ".html", ".css"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for args in icon_calls(text):
            names.update(set(ICON_NAME.findall(args)) - SIZES)
        names.update(re.findall(r"#i-([a-z0-9-]+)", text))
        names.update(re.findall(r"""data-icon=["']([a-z0-9-]+)["']""", text))
    return names


def _inner(svg: str, name: str) -> str:
    match = re.search(r"<svg\b[^>]*>(.*)</svg>", svg, re.DOTALL)
    if not match:
        raise SystemExit(f"{name}: not an svg")
    body = re.sub(r"<!--.*?-->", "", match.group(1), flags=re.DOTALL)
    body = re.sub(r"\s+", " ", body).strip()
    # one stroke width at every size: the stylesheet sets the width, the sprite keeps it from scaling
    return re.sub(r"<(path|circle|rect|line|polyline|polygon|ellipse)\b", r'<\1 vector-effect="non-scaling-stroke"', body)


def build(lucide: Path) -> str:
    symbols = []
    for name in sorted(set(ICONS)):
        file = lucide / f"{name}.svg"
        if not file.is_file():
            raise SystemExit(f"Lucide has no icon called {name!r} in {lucide}")
        symbols.append(f'<symbol id="i-{name}" viewBox="0 0 24 24">{_inner(file.read_text(encoding="utf-8"), name)}</symbol>')
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0" style="position:absolute">\n'
        "<!-- Lucide icons (ISC licence, see LICENSE-lucide.txt), selected by scripts/build_icons.py -->\n"
        + "\n".join(symbols) + "\n</svg>\n"
    )


def mentioned_names() -> set[str]:
    """Any quoted word in the interface that is one of our icons: icons are often named in arrays and ternaries."""
    quoted: set[str] = set()
    for path in JS_ROOT.rglob("*"):
        if path.suffix in {".js", ".html", ".css"} and path.is_file():
            quoted.update(re.findall(r"""["']([a-z][a-z0-9-]*)["']""", path.read_text(encoding="utf-8")))
    return quoted & set(ICONS)


def check() -> int:
    if not SPRITE.is_file():
        print("no sprite yet: run scripts/build_icons.py --lucide <folder>", file=sys.stderr)
        return 1
    have = set(re.findall(r'<symbol id="i-([a-z0-9-]+)"', SPRITE.read_text(encoding="utf-8")))
    missing = sorted(used_names() - have)
    unused = sorted(have - used_names() - mentioned_names())
    if missing:
        print("used but not in the sprite:", ", ".join(missing), file=sys.stderr)
    if unused:
        print("in the sprite but never used (remove from ICONS):", ", ".join(unused), file=sys.stderr)
    return 1 if missing else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lucide", type=Path, help="folder with Lucide's icon files")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        return check()
    if not args.lucide:
        parser.error("--lucide is required unless --check")
    SPRITE.parent.mkdir(parents=True, exist_ok=True)
    SPRITE.write_text(build(args.lucide), encoding="utf-8", newline="\n")
    print(f"wrote {SPRITE.relative_to(ROOT)} with {len(set(ICONS))} icons ({SPRITE.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
