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
    # raised from 200 KB on 2026-10-20 when the compare modes, the caption, take links, the wall's display and
    # the hover previews landed; the wire figure (what a visitor downloads, gzipped per file) was raised from
    # 75 KB to 80 KB on 2026-10-21 for the receipt's verdict and stage strip, the code sheet, Play all and the
    # footage following the move in Replay; it stays the number to defend
    # 240 KB to 262 KB on 2026-10-22 for the live previs stage (the stage view, the playhead it follows, the wall's
    # inset), the curated filmstrip order and the round-4 feel pass (cuts, scrubber ticks, keys)
    # 262 KB to 280 KB on 2026-10-22 (round 5) for Angles (the pivot geometry, the dials and the drag on the stage, the
    # Angles sheet), the transformations' grouped select and the one-pass plan mirror
    # 286 KB to 310 KB on 2026-10-23 (round 7) for the Shots station, the Transition sheet, the moving tiles and the
    # Takes wall (the loop player that plays only what is on screen, a few at a time)
    # 310 KB to 320 KB on 2026-10-23 (round 7b): Edit with words, Dub, the face-only Re-shoot (the three take-from-a-take
    # sheets now share their parts with the Transition sheet)
    # 320 KB to 324 KB on 2026-10-23 (round 7c): the Extend and Upscale steps in the progress rail, merged with 7b
    # 324 KB to 329 KB on 2026-10-23 (round 7d): Extend sheet and the What happens field, with the Transition sheet's
    # How it gets there
    # 329 KB to 329.8 KB on 2026-10-23 (round 7e): review-2 fixes (a remix asks the recording it names, the spoken line and
    # the transition idea tidied as the server keeps them, a bundled Shots board)
    # 329.8 KB to 332.3 KB on 2026-10-23 (round 7f): the Upscale sheet (built with Extend on one shared choice sheet)
    # 535.2 KB to 536.3 KB on 2026-10-27 (round 13 site pass): the sharp-copy rule for gallery loops, the sound pill's word
    # on the Lobby screen, the compact identity chip on wall tiles
    # 536.3 KB raw / 192 KB wire / 171.4 KB CSS to the caps below on 2026-10-27 (round 14, the living cinema): the light in the rooms (ui/ambient.js), the studio sounds (ui/sound.js), the room crossfade and the sheets leaving, the move page carried from its card, the path chips on frames (ui/pathchip.js), hover-play on every take tile (ui/hoverplay.js), the pixel rule (lib/pictures.js), and the Play all, filmstrip focus and trailer slot fixes
    # 576 KB raw / 210 KB wire to the caps below on 2026-10-29 (round 18): the card a first visitor meets and the tour it offers (ui/welcome.js), which walks six rooms in the same window rather than sending anyone to a video
    assert raw <= 592_000, f"{raw / 1000:.0f} KB of script source: split or trim before adding more"  # 280 KB on 2026-10-22 for the angle dials; 286 KB the same evening for the spoken line and the Score and Soundscape presets; 358.5 KB on 2026-10-25 for the Lobby (the posters, the marquee, the lobby cards, the poster proof and its ticket), its finish-review fixes (the recorded-take stamp, Coming soon, one billing order), the rotating display, the defect-review fixes and the Shots room opening on a recorded board; 378 KB the same day for the Chat room (the person's own agent driving the studio over MCP: the room, its event stream, its logic) and the alignment pass; 400 KB later on 2026-10-25 (round 11): the Chat room's agent lanes and pickers, the Share sheet, the camera-move quiz, the lobby trailer and wall wake, the sound switch and the Make-your-own sheet; 410 KB the same evening: the lobby's trailer screen and wave, the Make-your-own sheet, the quiz, the share sheet and the chat's agent pickers; 472 KB late on 2026-10-25 (round 12): the video-first Lobby (the trailer screen and its reel, the camera-move gallery with scrub and filters, a page per move, the effects rail, the quiz's score card), the in-browser seal check, GPU time and cost, small pictures and lazy posters, and the Compare sheet; 495 KB the night of 2026-10-25 to 26: the take saved with its camera path (the stage drawn on a canvas and the in-page recorder), the Takes room's GPU ledger and the review fixes to the decoder slots; 512 KB early on 2026-10-26: the shot sheet (frames, path, words and receipt drawn on a canvas) and the second review's fixes; 512 KB on 2026-10-26 (round 13): the reveal that follows the viewport, the quiz and move-page settles, the room mark, keyed Shots tiles, in-place chat streaming, the seal check's three states, the picker keys and the sheets' focus trap; 531 KB the night of 2026-10-26: the review fixes (the chat tool card drawn again on any change, the setup command kept whole on a phone, the sheets and pickers cleaning up after themselves)
    # 80 KB to 88 KB on 2026-10-22 for the Connect sheet (a target, an honest test, the readiness table) and the
    # shared sheet helper; 88 KB to 94 KB the same day for the previs stage and the round-4 feel pass named above
    # (with the keyboard sheet, cinema mode and the cast's takes row); the guard sums every file on purpose, so lazy
    # loading would not count
    # 94 KB to 101 KB on 2026-10-22 (round 5) for the same Angles, transformations and one-pass work
    # 536.3 KB raw / 192 KB wire / 171.4 KB CSS to the caps below on 2026-10-27 (round 14, the living cinema): the light in the rooms (ui/ambient.js), the studio sounds (ui/sound.js), the room crossfade and the sheets leaving, the move page carried from its card, the path chips on frames (ui/pathchip.js), hover-play on every take tile (ui/hoverplay.js), the pixel rule (lib/pictures.js), and the Play all, filmstrip focus and trailer slot fixes
    # 576 KB raw / 210 KB wire to the caps below on 2026-10-29 (round 18): the card a first visitor meets and the tour it offers (ui/welcome.js), which walks six rooms in the same window rather than sending anyone to a video
    assert wire <= 216_000, f"{wire / 1000:.0f} KB of script over the wire"  # 101 KB on 2026-10-22 for the angle dials; 103 KB the same evening for the spoken line and the sound presets; 110 KB on 2026-10-23 for round 7 (Shots, Transitions, the moving tiles and the wall); 114 KB on 2026-10-23 (round 7b): Edit with words, Dub, the face-only Re-shoot; 116 KB on 2026-10-23 (round 7d): Extend sheet and the What happens field, with the Transition sheet's How it gets there; 116.5 KB on 2026-10-23 (round 7e): review-2 fixes; 117.4 KB on 2026-10-23 (round 7f): the Upscale sheet; 126.7 KB on 2026-10-25 for the Lobby, its finish-review fixes, the rotating display, the defect-review fixes and the Shots opening board; 134 KB the same day for the Chat room and the alignment pass; 142 KB later on 2026-10-25 (round 11): the Chat room's agent lanes and pickers, the Share sheet, the camera-move quiz, the lobby trailer and wall wake, the sound switch and the Make-your-own sheet; 146 KB the same evening: the lobby's trailer screen and wave, the Make-your-own sheet, the quiz and the chat's agent pickers; 170 KB late on 2026-10-25 (round 12): the video-first Lobby (the trailer screen and its reel, the camera-move gallery with scrub and filters, a page per move, the effects rail, the quiz's score card), the in-browser seal check, GPU time and cost, small pictures and lazy posters, and the Compare sheet; 178 KB the night of 2026-10-25 to 26: the take saved with its camera path (the stage drawn on a canvas and the in-page recorder), the Takes room's GPU ledger and the review fixes to the decoder slots; 185 KB early on 2026-10-26: the shot sheet (frames, path, words and receipt drawn on a canvas) and the second review's fixes; 184 KB on 2026-10-26 (round 13): the reveal that follows the viewport, the quiz and move-page settles, the room mark, keyed Shots tiles, in-place chat streaming, the seal check's three states, the picker keys and the sheets' focus trap; 192 KB the night of 2026-10-26: the review fixes (the chat room settling every turn, Compare naming what code did to a take, the setup command kept whole on a phone)
    styles = sum(p.stat().st_size for p in (WEB / "css").rglob("*.css"))
    # 171.4 KB on 2026-10-27 after the Lobby screen's sound pill and the phone order of the front; the cap leaves a room's
    # worth of rules before the next split
    # 536.3 KB raw / 192 KB wire / 171.4 KB CSS to the caps below on 2026-10-27 (round 14, the living cinema): the light in the rooms (ui/ambient.js), the studio sounds (ui/sound.js), the room crossfade and the sheets leaving, the move page carried from its card, the path chips on frames (ui/pathchip.js), hover-play on every take tile (ui/hoverplay.js), the pixel rule (lib/pictures.js), and the Play all, filmstrip focus and trailer slot fixes
    # 180.0 KB to 183.2 KB on 2026-10-27 (round 15, the hero): the trailer across the Lobby's front with the actions on its foot,
    # the screen's scroll sink and the light in the rooms turned up; the cap leaves room for the week's fixes
    assert styles <= 206_000, f"{styles / 1000:.0f} KB of CSS"  # 203.0 KB on 2026-10-28 (round 17): the Chat room's call sheet printed on card stock beside the take an agent made in that room, net of the three dead .perf-* utilities removed with it; 196.3 KB on 2026-10-28, round 16 finished: the card-stock Take pane with the rendered paper tooth under it, and the screen's brass foot as a strip of rendered brass; 191.2 KB on 2026-10-27 (round 16, the stock): the grain over every room, the keykode printed up each frame's edge, the perforated die-cut edge, and the Lobby screen set in the room instead of bleeding to its edges; 80 to 86 KB on 2026-10-22: the Connect sheet and its table; 88 KB the same day for the angle dials; 94 KB on 2026-10-23 for the wall, the moving tiles, Shots and the Transition sheet; 118.5 KB on 2026-10-25 for the cinema lobby: lobby.css (posters, marquee, lobby cards, the ticket receipt), the ticket buttons, the bulb progress, the rendered rail props, then the finish-review fixes; 126.5 KB on 2026-10-25 for the alignment pass (baselines in rows, the move tiles' label line, the plan note's icon, the filmstrip's column edge, the Takes filter and phone sheet switches whole, the receipt's label pairs, the posters' type on shared lines, one column for sheet heads and bodies, cinema centred at every width, the scrolling rooms' foot room); 132.5 KB the same day for the Chat room and the desktop review's fixes; 140 KB later on 2026-10-25 (round 11): the Chat room's agent lanes and pickers, the Share sheet, the camera-move quiz, the lobby trailer and wall wake, the sound switch and the Make-your-own sheet; 157 KB late on 2026-10-25 (round 12): the video-first Lobby (the trailer screen and its reel, the camera-move gallery with scrub and filters, a page per move, the effects rail, the quiz's score card), the in-browser seal check, GPU time and cost, small pictures and lazy posters, and the Compare sheet; 156 KB on 2026-10-26 (round 13): the reveal that follows the viewport, the quiz and move-page settles, the room mark, keyed Shots tiles, in-place chat streaming, the seal check's three states, the picker keys and the sheets' focus trap; 172 KB on 2026-10-27 (round 13 motion): the Lobby's motion pass (the projector's flicker, the nearer dust, the film grain, the bulbs chasing round the marquee, the posters' lift and push-in, the rail props' lift and warm light)


def test_nothing_is_fetched_from_another_site():
    allowed = ("http://www.w3.org/", "http://127.0.0.1", "http://localhost",
               # 2026-10-25 round 11: share links a visitor clicks; nothing is fetched from them
               "https://x.com/", "https://www.reddit.com/", "https://www.linkedin.com/", "https://wa.me/", "https://t.me/",
               # the Make-your-own sheet hands the visitor the repository to clone: a link they copy, never fetched
               "https://github.com/")
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


def test_the_icon_scan_reads_every_name_a_call_can_draw():
    spec = importlib.util.spec_from_file_location("build_icons", Path(__file__).resolve().parents[1] / "scripts" / "build_icons.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def names(source: str) -> set[str]:
        return {n for args in module.icon_calls(source) for n in module.ICON_NAME.findall(args)} - module.SIZES

    assert names('icon(open ? "chevron-up" : "chevron-down", "sm")') == {"chevron-up", "chevron-down"}  # both branches
    assert names('icon(t.status === "failed" ? "triangle-alert" : "clock")') == {"triangle-alert", "clock"}  # a tested value is no icon
    assert names('icon(TOOL_ICON[s] ?? "clock", opts.small ? "sm" : undefined)') == {"clock"}  # a size is no icon either
    assert names('icon("upload", className.includes(" sm") ? "sm" : undefined)') == {"upload"}  # a string's ")" does not end the call


def test_the_fonts_and_icons_carry_their_licences():
    assert "SIL Open Font License" in _text(WEB / "fonts" / "OFL-Barlow.txt")
    assert "SIL Open Font License" in _text(WEB / "fonts" / "OFL-OverpassMono.txt")
    assert "ISC License" in _text(WEB / "icons" / "LICENSE-lucide.txt")
    fonts = sorted((WEB / "fonts").glob("*.woff2"))
    assert {p.name for p in fonts} == {
        "barlow-condensed-latin-300.woff2",  # Barlow Condensed is part of the Barlow project: the same OFL file covers it
        "barlow-condensed-latin-600.woff2",
        "barlow-condensed-latin-800.woff2",
        "barlow-latin-400.woff2",
        "barlow-latin-500.woff2",
        "barlow-latin-600.woff2",
        "overpass-mono-latin-wght.woff2",
    }
    for font in fonts:
        assert font.read_bytes()[:4] == b"wOF2", font.name
    tokens = _text(WEB / "css" / "tokens.css")
    for font in fonts:
        assert font.name in tokens, f"{font.name} is shipped but never declared"


def test_the_stylesheets_define_what_they_use():
    tokens = _text(WEB / "css" / "tokens.css")
    defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", tokens))
    used = set()
    for css in (WEB / "css").glob("*.css"):
        used |= set(re.findall(r"var\((--[a-z0-9-]+)", _text(css)))
    undefined = sorted(used - defined - {"--n", "--p", "--fill", "--split", "--aw", "--ah", "--still-h", "--i", "--notch",
                                         # round 12 (2026-10-25): the screen's reel, the scrub line, the drift, the poster wall's rows
                                         "--share", "--through", "--scrub", "--loop", "--drift", "--per-row", "--col-gap", "--to",
                                         # round 16 (2026-10-27): the Lobby screen's inset from the room's sides, and the
                                         # perforation a die-cut edge is punched with (--perf-dots, set on .on-stock itself)
                                         "--hero-w", "--hero-inset", "--perf-dots", "--tick-holes"})  # set per element (--hero-w: the Lobby screen's width, round 15, 2026-10-27)
    assert not undefined, f"used but never defined: {undefined}"
