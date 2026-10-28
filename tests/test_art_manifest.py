"""The rendered art in openfield/web/art is catalogued in manifest.json with size
and sha256, and every still carries a sidecar with its prompt and createdAt."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ART = Path(__file__).resolve().parents[1] / "openfield" / "web" / "art"
MANIFEST = ART / "manifest.json"

# Composite trailer assets are cuts or poster frames generated from recorded takes;
# they are documented by trailer.json instead of per-file sidecars.
FILES_WITHOUT_SIDECAR = frozenset({"trailer.mp4", "trailer-640.mp4", "trailer-hd.mp4", "trailer.webp"})


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest():
    return _manifest()


def _media_files() -> list[Path]:
    return [
        p
        for p in ART.iterdir()
        if p.is_file()
        and p.name not in ("manifest.json", "trailer.json")
        and not p.name.endswith(".json")
        and not p.name.startswith(".")  # a file the OS drops there (.DS_Store, Thumbs.db, desktop.ini) is not art
        and p.name.lower() not in ("thumbs.db", "desktop.ini")
    ]


def test_exception_set_matches_files_without_sidecars():
    """The named exception set is the complete list of media files that have no sidecar today."""
    without_sidecar = {p.name for p in _media_files() if not (ART / f"{p.name}.json").is_file()}
    assert without_sidecar == FILES_WITHOUT_SIDECAR, (
        f"FILES_WITHOUT_SIDECAR is stale: expected {sorted(FILES_WITHOUT_SIDECAR)}, "
        f"found {sorted(without_sidecar)}"
    )


def test_every_media_file_has_a_matching_manifest_entry(manifest):
    entries = {entry["file"]: entry for entry in manifest["files"]}
    missing = []
    mismatched = []
    for path in _media_files():
        entry = entries.get(path.name)
        if entry is None:
            missing.append(path.name)
            continue
        data = path.read_bytes()
        if len(data) != entry["bytes"]:
            mismatched.append(
                f"{path.name}: bytes manifest={entry['bytes']} actual={len(data)}"
            )
        actual_sha = hashlib.sha256(data).hexdigest()
        if actual_sha != entry["sha256"]:
            mismatched.append(
                f"{path.name}: sha256 manifest={entry['sha256']} actual={actual_sha}"
            )
    assert not missing, f"media files missing from manifest: {sorted(missing)}"
    assert not mismatched, "\n".join(mismatched)


def test_every_manifest_entry_exists_on_disk(manifest):
    missing = [
        entry["file"] for entry in manifest["files"] if not (ART / entry["file"]).is_file()
    ]
    assert not missing, f"manifest entries missing on disk: {sorted(missing)}"


def test_every_webp_entry_has_a_non_empty_prompt_sidecar(manifest):
    failures = []
    for entry in manifest["files"]:
        name = entry["file"]
        if not name.endswith(".webp"):
            continue
        if name in FILES_WITHOUT_SIDECAR:
            continue
        sidecar_path = ART / f"{name}.json"
        if not sidecar_path.is_file():
            failures.append(f"{name}: missing sidecar {sidecar_path.name}")
            continue
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        if not isinstance(sidecar.get("prompt"), str) or not sidecar["prompt"].strip():
            failures.append(f"{name}: sidecar has no non-empty prompt")
        if "createdAt" not in sidecar:
            failures.append(f"{name}: sidecar missing createdAt")
    assert not failures, "\n".join(failures)


def test_no_sidecar_is_orphaned():
    orphaned = []
    for path in ART.iterdir():
        if (
            not path.is_file()
            or path.name in ("manifest.json", "trailer.json")
            or not path.name.endswith(".json")
        ):
            continue
        picture = path.with_suffix("")
        if not picture.is_file():
            orphaned.append(path.name)
    assert not orphaned, f"orphaned sidecars: {sorted(orphaned)}"
