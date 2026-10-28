"""A take at a glance: a still as a small JPEG, a clip as a strip of frames. The studio serves both, so a client on a
slow link (the MCP server, a phone, a tunnel to a rented box) gets ~30 KB instead of the full PNG or MP4."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

from PIL import Image

from .engine import video

THUMB_MAX, STRIP_MAX_FRAMES = 1600, 12


def thumbnail_jpeg(image: Path | bytes, max_px: int = 448, quality: int = 80) -> bytes:
    """The image shrunk to `max_px` on its long side (never enlarged), as a JPEG."""
    source = io.BytesIO(image) if isinstance(image, bytes) else image
    with Image.open(source) as im:
        rgb = im.convert("RGB")
    rgb.thumbnail((max(16, min(max_px, THUMB_MAX)),) * 2)
    out = io.BytesIO()
    rgb.save(out, "JPEG", quality=quality)
    return out.getvalue()


def strip_jpeg(clip: Path, frames: int = 6, width: int = 256, seconds: float | None = None) -> bytes:
    """`frames` frames spread evenly across the clip (each in the middle of its slice), three to a row."""
    frames = max(1, min(frames, STRIP_MAX_FRAMES))
    length = seconds or video.probe(clip).duration_s or 1.0
    tiles = []
    with tempfile.TemporaryDirectory(prefix="of-peek-") as tmp:
        for i in range(frames):
            png = video.extract_frame(clip, Path(tmp) / f"f{i}.png", length * (i + 0.5) / frames)
            with Image.open(png) as im:
                tile = im.convert("RGB")
            tile.thumbnail((width, width))
            tiles.append(tile)
    w, h = tiles[0].size
    cols = min(3, len(tiles))
    sheet = Image.new("RGB", (w * cols, h * ((len(tiles) + cols - 1) // cols)), "black")
    for i, tile in enumerate(tiles):
        sheet.paste(tile, ((i % cols) * w, (i // cols) * h))
    out = io.BytesIO()
    sheet.save(out, "JPEG", quality=78)
    return out.getvalue()
