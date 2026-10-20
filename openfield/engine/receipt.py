"""Provenance receipts: canonical JSON, sealing, scrubbing, and PNG/MP4/sidecar embedding.

A receipt is a plain dict (schema "openfield.receipt/1"). `seal` adds a sha256 over its
canonical form, which detects edits but is not a signature: anyone can re-seal a changed copy.
Embedding rewrites the media file, so hash the outputs (`outputs[].sha256`) before embedding.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from openfield import __version__
from openfield.engine import video
from openfield.fsutil import replace_file

SCHEMA = "openfield.receipt/1"
RECIPE_SCHEMA = "openfield.recipe/1"
DISCLOSURE = (
    "AI-generated content. Made with OpenField Studio using open-weights models; "
    "see models and audit for the exact files."
)
PNG_KEY = "openfield.receipt"
MP4_KEY = "openfield_receipt"
SIDECAR_SUFFIX = ".receipt.json"

Receipt = dict[str, Any]
PathLike = video.PathLike

_MAX_UNPACKED_BYTES = 4 * 1024 * 1024
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JSON_LEAD = b"\xef\xbb\xbf \t\r\n"


def canonical_json(obj: Any) -> bytes:
    """Deterministic UTF-8 JSON: sorted keys, no whitespace, raw unicode, NaN/Infinity rejected."""
    text = json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return text.encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: PathLike) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_sections() -> dict[str, Any]:
    return {
        "inputs": {},
        "workflow": {"template": "", "sha256": "", "snapped": {}},
        "models": [],
        "audit": {"policy": "", "result": "", "disallowed": []},
        "identity": {"status": "", "score": None, "threshold": None, "refs_used": 0},
        "backend": {"kind": "", "job_id": "", "timings": {}},
        "outputs": [],
        "disclosure": DISCLOSURE,
    }


def new_receipt(
    *,
    take_id: str,
    kind: str,
    created_at: str | None = None,
    label: str = "",
    app_version: str | None = None,
    **sections: Any,
) -> Receipt:
    """Unsealed receipt with every required section present.

    `sections` may set inputs, workflow, models, audit, identity, backend, outputs and
    disclosure (other names raise TypeError). Dict sections are merged over their defaults.
    """
    receipt_sections = _default_sections()
    unknown = sorted(set(sections) - set(receipt_sections))
    if unknown:
        raise TypeError(f"unknown receipt section(s): {', '.join(unknown)}")
    for name, value in copy.deepcopy(sections).items():
        default = receipt_sections[name]
        if value is not None:
            receipt_sections[name] = {**default, **value} if isinstance(default, dict) else value
    stamp = created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema": SCHEMA,
        "app": {"name": "OpenField Studio", "version": app_version or __version__},
        "take": {"id": take_id, "kind": kind, "created_at": stamp, "label": label},
        **receipt_sections,
    }


_SECRET_KEY = re.compile(
    r"token|api[-_ ]?key|passw(?:or)?d|secret|authorization|credential", re.IGNORECASE
)
_PATH_ROOTS = "home|Users|root|mnt|media|Volumes|tmp|var|opt|srv|workspace"
_PATH_START = rf"(?:[A-Za-z]:[\\/]|\\\\[^\s\\/]+[\\/]|/(?:{_PATH_ROOTS})/)"
_WHOLE_PATH = re.compile(rf"{_PATH_START}[^\r\n]*")
_EMBEDDED_PATH = re.compile(rf"(?<![\w.~%-]){_PATH_START}[^\s\"'<>|?*]*")
_HOME_DIR = re.compile(r"(?:[A-Za-z]:[\\/]Users[\\/]|/Users/|/home/)[^\\/]+[\\/]*")
_SEPARATORS = re.compile(r"[\\/]+")


def _bare_name(path: str) -> str:
    if _HOME_DIR.fullmatch(path):
        return "~"
    parts = [part for part in _SEPARATORS.split(path) if part]
    return parts[-1] if parts else path


def _scrub_text(text: str) -> str:
    if _WHOLE_PATH.fullmatch(text):
        return _bare_name(text)
    return _EMBEDDED_PATH.sub(lambda found: _bare_name(found.group()), text)


def _scrub(value: Any) -> Any:
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return _scrub(tolist())
    if isinstance(value, dict):
        return {
            _scrub_text(str(key)): _scrub(item)
            for key, item in value.items()
            if not _SECRET_KEY.search(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_scrub(item) for item in value]
    if isinstance(value, os.PathLike):
        return _scrub_text(os.fspath(value))
    if isinstance(value, str):
        return _scrub_text(value)
    return value


def scrub(receipt: Receipt) -> Receipt:
    """Deep copy that is safe to share.

    Absolute Windows, UNC and well-known POSIX paths (/home, /Users, /root, /mnt, ...) inside
    any string collapse to their bare file name, and every key whose name contains token,
    api key, password, secret, authorization or credential is dropped. Tuples, Path objects and
    numpy scalars/arrays (anything with `tolist`) become plain JSON types.
    """
    return _scrub(receipt)


def seal(receipt: Receipt) -> Receipt:
    """Scrubbed deep copy with `integrity` = sha256 of the canonical receipt without it."""
    body = {key: value for key, value in scrub(receipt).items() if key != "integrity"}
    body["integrity"] = {"alg": "sha256", "digest": sha256_hex(canonical_json(body))}
    return body


def verify(receipt: object) -> bool:
    """True only if the integrity digest matches; never raises on malformed input."""
    if not isinstance(receipt, dict):
        return False
    integrity = receipt.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("alg") != "sha256":
        return False
    body = {key: value for key, value in receipt.items() if key != "integrity"}
    try:
        return integrity.get("digest") == sha256_hex(canonical_json(body))
    except (TypeError, ValueError, RecursionError):
        return False


def sidecar_path(media: PathLike) -> Path:
    return Path(f"{os.fspath(media)}{SIDECAR_SUFFIX}")


def write_sidecar(media: PathLike, receipt: Receipt) -> Path:
    path = sidecar_path(media)
    text = json.dumps(receipt, indent=2, ensure_ascii=False, allow_nan=False)
    path.write_text(f"{text}\n", encoding="utf-8", newline="\n")
    return path


def _load_receipt(text: str | bytes | None) -> Receipt | None:
    if not text:
        return None
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def read_sidecar(media: PathLike) -> Receipt | None:
    try:
        return _load_receipt(sidecar_path(media).read_bytes())
    except OSError:
        return None


def embed_png(src: PathLike, out: PathLike, receipt: Receipt) -> Path:
    """Re-save `src` as PNG with the receipt in an iTXt chunk; other text chunks are kept."""
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_name(f"{target.stem}.{uuid.uuid4().hex[:8]}.part{target.suffix}")
    try:
        with Image.open(src) as image:
            info = PngInfo()
            for key, value in getattr(image, "text", {}).items():
                if key != PNG_KEY:
                    info.add_text(key, value)
            info.add_itxt(PNG_KEY, canonical_json(receipt).decode("utf-8"))
            image.save(staged, format="PNG", pnginfo=info)
        replace_file(staged, target)
    finally:
        staged.unlink(missing_ok=True)
    return target


def read_png(path: PathLike) -> Receipt | None:
    """Receipt from the iTXt chunk; reads the header chunks only, pixels are never decoded."""
    with Image.open(path) as image:
        return _load_receipt(image.info.get(PNG_KEY)) if image.format == "PNG" else None


def _pack(obj: Any) -> str:
    packed = zlib.compress(canonical_json(obj), 9)
    return base64.urlsafe_b64encode(packed).rstrip(b"=").decode("ascii")


def _unpack(token: str) -> Any:
    """Inverse of `_pack`; ValueError on anything malformed or larger than 4 MiB unpacked."""
    try:
        packed = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        inflater = zlib.decompressobj()
        data = inflater.decompress(packed, _MAX_UNPACKED_BYTES)
        if not inflater.eof:
            raise ValueError("truncated or oversized payload")
        return json.loads(data)
    except (zlib.error, RecursionError) as exc:
        raise ValueError(f"malformed payload: {exc}") from exc


def _read_packed(token: str | None) -> Receipt | None:
    if not token:
        return None
    try:
        data = _unpack(token)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def embed_mp4(src: PathLike, out: PathLike, receipt: Receipt) -> Path:
    """Stream-copy `src` with the receipt packed as base64url(zlib(JSON)) in `openfield_receipt`."""
    return video.embed_metadata(src, out, {MP4_KEY: _pack(receipt)})


def read_mp4(path: PathLike) -> Receipt | None:
    return _read_packed(video.read_metadata(path).get(MP4_KEY))


def _read_in_file(media: Path) -> Receipt | None:
    try:
        with open(media, "rb") as handle:
            head = handle.read(12)
        if head.startswith(_PNG_MAGIC):
            return read_png(media)
        if head[4:8] == b"ftyp":
            return read_mp4(media)
        if head.lstrip(_JSON_LEAD).startswith(b"{"):
            with open(media, "rb") as handle:
                return _load_receipt(handle.read(_MAX_UNPACKED_BYTES))
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError, video.VideoError):
        return None
    return None


def read_media(path: PathLike) -> tuple[Receipt, bool] | None:
    """Find the receipt of a file and report whether its integrity digest checks out.

    Returns `(receipt, verified)`, or None if nothing was found. A receipt inside the file (PNG,
    MP4, or a bare receipt .json) wins over the `.receipt.json` sidecar, which is the fallback
    for every other file. A tampered receipt is still returned, with `verified` False, so a UI
    can show what it claims.
    """
    media = Path(path)
    receipt = _read_in_file(media)
    if receipt is None:
        receipt = read_sidecar(media)
    return None if receipt is None else (receipt, verify(receipt))


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def recipe_from_receipt(receipt: Receipt) -> dict[str, Any]:
    """Just enough to rebuild a Take: kind, inputs, workflow template, model files and seed.

    The seed is mirrored from `inputs["seed"]`. Backend details, job ids, outputs and audit data
    are left out, and paths and secrets are scrubbed.
    """
    inputs = _as_dict(receipt.get("inputs"))
    models = receipt.get("models")
    return _scrub(
        {
            "schema": RECIPE_SCHEMA,
            "kind": _as_dict(receipt.get("take")).get("kind", ""),
            "template": _as_dict(receipt.get("workflow")).get("template", ""),
            "inputs": inputs,
            "models": [
                {"role": entry.get("role", ""), "file": entry.get("file", "")}
                for entry in (models if isinstance(models, list) else [])
                if isinstance(entry, dict)
            ],
            "seed": inputs.get("seed"),
        }
    )


def recipe_link(recipe: dict[str, Any]) -> str:
    """base64url(zlib(canonical JSON)) without padding; safe inside a URL fragment."""
    return _pack(recipe)


def parse_recipe_link(s: str) -> dict[str, Any]:
    """Inverse of `recipe_link`; ValueError for anything that is not a packed JSON object."""
    if not isinstance(s, str):
        raise ValueError("recipe link must be a string")
    recipe = _unpack(s.strip())
    if not isinstance(recipe, dict):
        raise ValueError("recipe link does not hold an object")
    return recipe
