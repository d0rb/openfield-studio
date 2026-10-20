"""The interface in a real browser: the live app on the offline fake of the Comfy API, then the hosted Replay.

Needs Node and a Chrome or Edge on the machine (set OPENFIELD_BROWSER to point at one); skips cleanly otherwise.
The checks themselves are in tests/ui/smoke.mjs, so they can also be run by hand against any running copy.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from .ui_support import NODE, ROOT, browser, export_site, fake_stack, serve_static


def _smoke(mode: str, url: str) -> str:
    done = subprocess.run([NODE, "tests/ui/smoke.mjs", mode, f"{url}/"], cwd=ROOT, capture_output=True, text=True, timeout=300)
    report = done.stdout + done.stderr
    assert done.returncode == 0, f"UI smoke test ({mode}) failed:\n{report}"
    return report


@pytest.mark.skipif(NODE is None, reason="Node is not installed")
def test_the_interface_in_a_real_browser_live_then_hosted_replay(tmp_path: Path):
    if not browser():
        pytest.skip("no Chrome or Edge found (set OPENFIELD_BROWSER)")
    data = tmp_path / "data"
    with fake_stack(data) as live:
        assert "PASS" in _smoke("live", live)
        # the take the live run made is what the hosted Replay will play back
        site = tmp_path / "site"
        export_site(data, site)
    with serve_static(site) as static:
        _smoke("static", static)
