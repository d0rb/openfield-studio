"""Export: derive new takes from finished ones (vertical crop, reels) with ffmpeg. No GPU needed.

An export is a take of its own with a sealed receipt that points back at its sources by their
integrity digests, so the chain of custody (models, open-weights audit) is never lost.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from .engine import receipt as receipts
from .engine import video
from .fsutil import replace_file
from .ledger import Ledger, LedgerError, write_json

MAX_REEL_TAKES = 8


def _source(ledger: Ledger, take_id: str) -> tuple[dict[str, Any], dict[str, Any], Path]:
    take = ledger.read(take_id)
    if take["status"] != "succeeded":
        raise LedgerError(f"take {take_id} is not finished")
    folder = ledger.take_dir(take_id)
    media = folder / "take.mp4"
    if not media.is_file():
        raise LedgerError(f"take {take_id} has no video to export")
    receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
    return take, receipt, media


def _provenance(sources: list[dict[str, Any]]) -> dict[str, Any]:
    models: dict[str, dict[str, Any]] = {}
    for receipt in sources:
        for model in receipt.get("models", []):
            models.setdefault(model["file"], model)
    audits = [r.get("audit", {}) for r in sources]
    ok = all(a.get("result") == "pass" for a in audits)
    return {
        "models": list(models.values()),
        "audit": {"policy": "open-weights-only", "result": "pass" if ok else "fail",
                  "disallowed": sorted({n for a in audits for n in a.get("disallowed", [])})},
    }


def _finish(ledger: Ledger, take: dict[str, Any], final: Path, *, label: str, inputs: dict[str, Any],
            sources: list[dict[str, Any]], operation: dict[str, Any]) -> dict[str, Any]:
    take_id = take["id"]
    folder = ledger.take_dir(take_id)
    info = video.probe(final)
    poster = folder / "poster.png"
    video.extract_frame(final, poster, "mid")
    provenance = _provenance(sources)
    digest = hashlib.sha256(json.dumps(operation, sort_keys=True).encode()).hexdigest()
    raw = receipts.new_receipt(
        take_id=take_id, kind="export", label=label,
        inputs=dict(inputs, recipe_hash=take.get("recipe_hash")),
        workflow={"template": "ffmpeg", "sha256": digest, "runs": [], "operation": operation},
        models=provenance["models"], audit=provenance["audit"],
        identity={"status": "n/a", "score": None, "threshold": 0.363, "refs_used": 0},
        backend={"kind": "local", "job_id": "", "timings": {}},
        outputs=[{"role": "video", "file": "take.mp4", "node_id": "", "content_type": "video/mp4",
                  "sha256_before_receipt": receipts.sha256_file(final),
                  "seconds": round(info.duration_s, 2)}],
    )
    sealed = receipts.seal(raw)
    embedded = final.with_name("take.embedded.mp4")
    receipts.embed_mp4(final, embedded, sealed)
    replace_file(embedded, final)
    write_json(folder / "receipt.json", sealed)
    receipts.write_sidecar(final, sealed)
    outputs = [
        {"role": "video", "file": "take.mp4", "kind": "video", "content_type": "video/mp4"},
        {"role": "poster", "file": "poster.png", "kind": "image", "content_type": "image/png"},
        {"role": "receipt", "file": "receipt.json", "kind": "json", "content_type": "application/json"},
    ]
    return ledger.update(take_id, status="succeeded", stage="done", progress=1.0, outputs=outputs,
                         audit=sealed["audit"], seconds=round(info.duration_s, 2),
                         size=[info.width, info.height])


def _create(ledger: Ledger, label: str, recipe: dict[str, Any], parent: str | None) -> dict[str, Any]:
    take = ledger.create("export", label, recipe, parent=parent,
                         backend={"kind": "local", "label": "ffmpeg"})
    return ledger.update(take["id"], status="running", stage="export")


def export_vertical_sync(ledger: Ledger, source_id: str, *, focus_x: float = 0.5) -> dict[str, Any]:
    if not 0.0 <= focus_x <= 1.0:
        raise ValueError("focus_x must be between 0 and 1")
    source, source_receipt, media = _source(ledger, source_id)
    recipe = {"kind": "export", "format": "9x16", "source": source_id, "focus_x": focus_x}
    take = _create(ledger, f"9:16 of {source['label']}"[:70], recipe, source_id)
    try:
        final = ledger.take_dir(take["id"]) / "take.mp4"
        video.crop_9x16(media, final, focus_x=focus_x)
        return _finish(
            ledger, take, final, label=take["label"], sources=[source_receipt],
            inputs={"format": "9x16", "focus_x": focus_x, "sources": [_ref(source_id, source_receipt)]},
            operation={"op": "crop_9x16", "focus_x": focus_x})
    except Exception as exc:
        ledger.update(take["id"], status="failed",
                      error={"code": "export_failed", "message": str(exc), "retryable": False})
        raise


def export_reel_sync(ledger: Ledger, source_ids: list[str], *, crossfade_s: float = 0.5,
                     lufs: float | None = -14.0) -> dict[str, Any]:
    if not 2 <= len(source_ids) <= MAX_REEL_TAKES:
        raise ValueError(f"a reel joins between 2 and {MAX_REEL_TAKES} takes")
    sources = [_source(ledger, i) for i in source_ids]
    shortest = min(video.probe(media).duration_s for _, _, media in sources)
    if crossfade_s < 0 or 2 * crossfade_s > shortest:
        raise ValueError(f"crossfade_s must be at most half of the shortest clip ({shortest:.1f}s)")
    recipe = {"kind": "export", "format": "reel", "sources": source_ids,
              "crossfade_s": crossfade_s, "lufs": lufs}
    take = _create(ledger, f"reel of {len(source_ids)} takes", recipe, source_ids[0])
    try:
        final = ledger.take_dir(take["id"]) / "take.mp4"
        video.concat([m for _, _, m in sources], final, crossfade_s=crossfade_s, lufs=lufs)
        return _finish(
            ledger, take, final, label=take["label"], sources=[r for _, r, _ in sources],
            inputs={"format": "reel", "crossfade_s": crossfade_s, "lufs": lufs,
                    "sources": [_ref(i, r) for i, (_, r, _) in zip(source_ids, sources, strict=True)]},
            operation={"op": "concat", "crossfade_s": crossfade_s, "lufs": lufs})
    except Exception as exc:
        shutil.rmtree(ledger.take_dir(take["id"]) / "runs", ignore_errors=True)
        ledger.update(take["id"], status="failed",
                      error={"code": "export_failed", "message": str(exc), "retryable": False})
        raise


def _ref(take_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
    return {"take": take_id, "receipt_digest": receipt.get("integrity", {}).get("digest")}


async def export_vertical(ledger: Ledger, source_id: str, *, focus_x: float = 0.5) -> dict[str, Any]:
    return await asyncio.to_thread(export_vertical_sync, ledger, source_id, focus_x=focus_x)


async def export_reel(ledger: Ledger, source_ids: list[str], *, crossfade_s: float = 0.5,
                      lufs: float | None = -14.0) -> dict[str, Any]:
    return await asyncio.to_thread(export_reel_sync, ledger, source_ids, crossfade_s=crossfade_s, lufs=lufs)
