"""The interface ships as plain files: no build step, no CDN, no network at runtime. These checks keep it that way."""
from __future__ import annotations

import gzip
import importlib.util
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "openfield" / "web"
SOURCES = [p for p in WEB.rglob("*") if p.suffix in {".js", ".css", ".html", ".svg"} and "showcase" not in p.parts]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_interface_stays_small():
    scripts = sorted((WEB / "js").rglob("*.js"))
    raw = sum(p.stat().st_size for p in scripts)
    wire = sum(len(gzip.compress(p.read_bytes(), 9)) for p in scripts)
    assert raw <= 200_000, f"{raw / 1000:.0f} KB of script source: split or trim before adding more"
    assert wire <= 75_000, f"{wire / 1000:.0f} KB of script over the wire"
    styles = sum(p.stat().st_size for p in (WEB / "css").rglob("*.css"))
    assert styles <= 80_000, f"{styles / 1000:.0f} KB of CSS"


def test_nothing_is_fetched_from_another_site():
    allowed = ("http://www.w3.org/", "http://127.0.0.1", "http://localhost")
    offenders = []
    for path in SOURCES:
        for url in re.findall(r"https?://[^\s\"')<>]+", _text(path)):
            if not url.startswith(allowed):
                offenders.append(f"{path.relative_to(WEB)}: {url}")
    assert not offenders, "the page must work offline; found " + ", ".join(offenders)


def test_every_file_the_page_loads_exists():
    html = _text(WEB / "index.html")
    local = [u for u in re.findall(r"""(?:href|src)="([^"#]+)""", html) if not u.startswith(("http", "data:"))]
    assert local, "index.html loads nothing?"
    missing = [u for u in local if not (WEB / u).is_file()]
    assert not missing, missing
    for css in (WEB / "css").glob("*.css"):
        for ref in re.findall(r"url\(\"?([^)\"]+)\"?\)", _text(css)):
            if not ref.startswith("data:"):
                assert (css.parent / ref).resolve().is_file(), f"{css.name} refers to {ref}"


def test_every_script_import_resolves():
    for path in (WEB / "js").rglob("*.js"):
        for ref in re.findall(r"""from\s+["'](\.[^"']+)["']""", _text(path)):
            assert (path.parent / ref).resolve().is_file(), f"{path.relative_to(WEB)} imports {ref}"


def test_the_icon_sprite_has_every_icon_the_code_draws():
    spec = importlib.util.spec_from_file_location("build_icons", Path(__file__).resolve().parents[1] / "scripts" / "build_icons.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    have = set(re.findall(r'<symbol id="i-([a-z0-9-]+)"', _text(WEB / "icons" / "sprite.svg")))
    missing = sorted(module.used_names() - have)
    assert not missing, f"drawn but missing from the sprite: {missing}"
    assert have == set(module.ICONS), "the sprite is stale: run scripts/build_icons.py"


def test_the_fonts_and_icons_carry_their_licences():
    assert "SIL Open Font License" in _text(WEB / "fonts" / "OFL-Inter.txt")
    assert "ISC License" in _text(WEB / "icons" / "LICENSE-lucide.txt")
    assert (WEB / "fonts" / "inter-latin-wght-normal.woff2").read_bytes()[:4] == b"wOF2"


def test_the_stylesheets_define_what_they_use():
    tokens = _text(WEB / "css" / "tokens.css")
    defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", tokens))
    used = set()
    for css in (WEB / "css").glob("*.css"):
        used |= set(re.findall(r"var\((--[a-z0-9-]+)", _text(css)))
    undefined = sorted(used - defined - {"--n", "--p", "--fill", "--split", "--aw", "--ah", "--still-h"})  # set per element
    assert not undefined, f"used but never defined: {undefined}"
