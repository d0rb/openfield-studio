"""Cast: reusable reference sets (a character, product, wardrobe or location).

References are normalised to PNG on the way in (EXIF rotation applied, RGB, longest side capped)
so every later stage sees the same pixels. Consent is mandatory and stored with the cast; faces
are analysed locally, and nothing leaves the machine except inside a render the user starts.
"""
from __future__ import annotations

import io
import json
import re
import secrets
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from .ledger import SAFE_PART, now_iso, write_json

KINDS = ("character", "product", "wardrobe", "location")
CONSENT = {
    "mine": "These are photos of me.",
    "consented": "The people shown agreed to this use.",
    "fictional": "These are AI-generated or fictional.",
}
CAST_ID = re.compile(r"^ca_[0-9a-f]{8}$")
MAX_REFS = 8
MAX_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 48_000_000  # far above any photo worth using, far below a decompression bomb
MAX_SIDE = 1536
MIN_FACE_PX = 80


def generated_origin(take: dict[str, Any], receipt: dict[str, Any], candidate: int) -> dict[str, Any]:
    """Provenance recorded on a Cast made from one candidate of a generated-character take."""
    return {
        "generated": True, "take": take["id"], "description": take["recipe"]["description"],
        "seed": take["recipe"]["seed"] + candidate - 1, "prompt": receipt["inputs"]["final_prompt"],
        "models": [{"file": m["file"], "license": m["license"]} for m in receipt["models"]],
        "disclosure": "AI-generated fictional character",
    }


class CastError(ValueError):
    pass


class CastStore:
    def __init__(self, root: Path, gate: Any = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.gate = gate  # a FaceGate, or a callable returning the current one

    def _gate(self) -> Any:
        return self.gate() if callable(self.gate) else self.gate

    def _dir(self, cast_id: str) -> Path:
        if not CAST_ID.match(cast_id):
            raise CastError(f"not a cast id: {cast_id!r}")
        return self.root / cast_id

    def create(self, name: str, kind: str, consent: str, images: list[tuple[str, bytes]],
               origin: dict[str, Any] | None = None) -> dict[str, Any]:
        """Save a cast. `origin` records how generated references were made (prompt, seed, models)."""
        name = name.strip()
        if not 1 <= len(name) <= 40:
            raise CastError("give the cast a name of 1 to 40 characters")
        if kind not in KINDS:
            raise CastError(f"kind must be one of {', '.join(KINDS)}")
        if consent not in CONSENT:
            raise CastError("consent is required: say whether these are yours, consented, or fictional")
        if not 1 <= len(images) <= MAX_REFS:
            raise CastError(f"add between 1 and {MAX_REFS} images")
        cast_id = f"ca_{secrets.token_hex(4)}"
        folder = self._dir(cast_id)
        (folder / "refs").mkdir(parents=True)
        refs = []
        try:
            for index, (filename, data) in enumerate(images, start=1):
                refs.append(self._store_image(folder / "refs", index, filename, data, kind))
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        cast = {
            "id": cast_id, "name": name, "kind": kind, "consent": consent,
            "consent_text": CONSENT[consent], "created_at": now_iso(), "refs": refs,
            "face_check": bool(self._gate() and getattr(self._gate(), "available", False)),
        }
        if origin:
            cast["origin"] = origin
        write_json(folder / "cast.json", cast)
        return cast

    def _store_image(self, refs_dir: Path, index: int, filename: str, data: bytes, kind: str) -> dict[str, Any]:
        if len(data) > MAX_BYTES:
            raise CastError(f"{filename}: larger than {MAX_BYTES // (1024 * 1024)} MB")
        try:
            with Image.open(io.BytesIO(data)) as raw:
                if raw.width * raw.height > MAX_PIXELS:  # a tiny file can claim a gigantic canvas
                    raise CastError(f"{filename}: larger than {MAX_PIXELS // 1_000_000} megapixels")
                image = ImageOps.exif_transpose(raw).convert("RGB")
        except Image.DecompressionBombError:
            raise CastError(f"{filename}: far too many pixels") from None
        except (UnidentifiedImageError, OSError):
            raise CastError(f"{filename}: not an image Pillow can read") from None
        image.thumbnail((MAX_SIDE, MAX_SIDE))
        target = refs_dir / f"ref_{index}.png"
        image.save(target, "PNG")
        entry: dict[str, Any] = {"file": target.name, "size": list(image.size), "faces": None, "hint": None}
        gate = self.gate() if callable(self.gate) else self.gate
        if kind == "character" and gate is not None and getattr(gate, "available", False):
            faces = gate.faces(target)
            entry["faces"] = len(faces)
            if not faces:
                entry["hint"] = "No face found: this photo will not count toward the identity check."
            elif len(faces) > 1:
                entry["hint"] = "Several faces found: the largest is used."
            elif min(faces[0].box[2:]) < MIN_FACE_PX:
                entry["hint"] = "The face is small; a closer photo gives a steadier identity check."
        return entry

    def get(self, cast_id: str) -> dict[str, Any]:
        try:
            return json.loads((self._dir(cast_id) / "cast.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise CastError(f"no such cast: {cast_id}") from None

    def list(self) -> list[dict[str, Any]]:
        casts = []
        for entry in self.root.iterdir():
            if entry.is_dir() and CAST_ID.match(entry.name):
                try:
                    casts.append(self.get(entry.name))
                except (CastError, ValueError):
                    continue
        return sorted(casts, key=lambda c: c["created_at"], reverse=True)

    def delete(self, cast_id: str) -> None:
        shutil.rmtree(self._dir(cast_id), ignore_errors=True)

    def ref_paths(self, cast_id: str) -> list[Path]:
        cast = self.get(cast_id)
        return [self._dir(cast_id) / "refs" / r["file"] for r in cast["refs"]]

    def ref_file(self, cast_id: str, filename: str) -> Path:
        if not SAFE_PART.match(filename):
            raise CastError("bad file name")
        path = self._dir(cast_id) / "refs" / filename
        if not path.is_file():
            raise CastError("no such file")
        return path
