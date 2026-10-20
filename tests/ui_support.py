"""Shared helpers for the tests that drive the interface in a real browser: servers, the exported site, and a browser check."""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def browser() -> str:
    """The Chrome or Edge the browser tests will use ('' when there is none)."""
    if NODE is None:
        return ""
    code = "import { findBrowser } from './scripts/ui/browser.mjs'; console.log(findBrowser() ?? '')"
    out = subprocess.run([NODE, "--input-type=module", "-e", code], cwd=ROOT, capture_output=True, text=True, timeout=30)
    return out.stdout.strip()


def wait_for(url: str, seconds: float = 40) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    raise AssertionError(f"{url} did not come up")


def _stop(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@contextmanager
def fake_stack(data: Path, delay: float = 0.15):
    """The app on the offline fake of the Comfy API, as scripts/dev_fake_stack.py runs it. Yields its base URL."""
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "scripts/dev_fake_stack.py", "--delay", str(delay), "--port", str(port), "--data-dir", str(data)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_for(f"http://127.0.0.1:{port}/api/status")
        yield f"http://127.0.0.1:{port}"
    finally:
        _stop(proc)


def make_quick_take(base: str, subject: str = "A white lighthouse on a cliff at dusk") -> str:
    """Start a quick take (no approval pause) over HTTP and wait for it to finish; returns its id."""
    body = json.dumps({"subject": subject, "rig": {"movement": "static"}, "prompt_only": True, "auto_approve": True}).encode()
    request = urllib.request.Request(f"{base}/api/takes/direct", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Origin": base})
    with urllib.request.urlopen(request, timeout=30) as reply:
        take_id = json.loads(reply.read())["id"]
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        with urllib.request.urlopen(f"{base}/api/takes/{take_id}", timeout=10) as reply:
            take = json.loads(reply.read())
        if take["status"] in {"succeeded", "failed", "canceled"}:
            assert take["status"] == "succeeded", take.get("error")
            return take_id
        time.sleep(0.4)
    raise AssertionError("the take did not finish")


def export_site(data: Path, site: Path) -> None:
    """The hosted Replay: the takes under `data` written out as plain files."""
    done = subprocess.run(
        [sys.executable, "-m", "openfield", "export-static", "--out", str(site), "--takes", str(data / "takes")],
        cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr


@contextmanager
def serve_static(site: Path):
    """Serve a folder of plain files, as any static host would. Yields its base URL."""
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--directory", str(site), "--bind", "127.0.0.1"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_for(f"http://127.0.0.1:{port}/static/manifest.json")
        yield f"http://127.0.0.1:{port}"
    finally:
        _stop(proc)
