"""scripts/pod_setup.sh runs on a rented Linux box, so it is checked with a real Linux bash."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHELL_FILES = sorted([*(ROOT / "scripts").glob("*.sh"), *(ROOT / "tests" / "shell").glob("*.sh")])


def linux_bash(command: str) -> subprocess.CompletedProcess[str] | None:
    """Run a bash command in a real Linux environment: here, or WSL on Windows; None when there is none."""
    if sys.platform.startswith("linux") and shutil.which("bash"):
        return subprocess.run(["bash", "-c", command], cwd=ROOT, capture_output=True, text=True, timeout=120,
                              check=False)
    if sys.platform == "win32" and shutil.which("wsl"):
        probe = subprocess.run(["wsl", "bash", "-c", "echo ready"], capture_output=True, text=True, timeout=60,
                               check=False)
        if probe.returncode != 0 or "ready" not in probe.stdout:
            return None
        root = subprocess.run(["wsl", "wslpath", "-a", str(ROOT)], capture_output=True, text=True, timeout=60,
                              check=False).stdout.strip()
        return subprocess.run(["wsl", "bash", "-c", f"cd '{root}' && {command}"], capture_output=True, text=True,
                              timeout=120, check=False)
    return None


def test_shell_scripts_have_unix_line_endings():
    """A CRLF in a script copied to the pod is a syntax error there ('set: pipefail: invalid option name')."""
    assert SHELL_FILES
    for path in SHELL_FILES:
        assert b"\r" not in path.read_bytes(), f"{path.relative_to(ROOT)} has carriage returns: run dos2unix"


def test_the_repository_forces_lf_for_scripts_on_every_checkout():
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "*.sh text eol=lf" in attributes


def test_pod_setup_parses_under_linux_bash():
    done = linux_bash("bash -n scripts/pod_setup.sh && echo parsed")
    if done is None:
        pytest.skip("no Linux bash here (install WSL or run on Linux/CI)")
    assert done.returncode == 0 and "parsed" in done.stdout, done.stderr


def test_a_stale_pid_file_never_gets_an_unrelated_process_killed():
    done = linux_bash("bash tests/shell/pod_functions.sh")
    if done is None:
        pytest.skip("no Linux bash here (install WSL or run on Linux/CI)")
    assert done.returncode == 0 and "OK" in done.stdout, done.stdout + done.stderr
