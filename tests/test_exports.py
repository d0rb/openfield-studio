from __future__ import annotations

import json
import subprocess
from pathlib import Path

import imageio_ffmpeg
import pytest

from openfield.engine import receipt as receipts
from openfield.engine import video
from openfield.exports import export_reel_sync, export_vertical_sync
from openfield.ledger import Ledger, LedgerError, write_json

MODEL = {"role": "video:ltx-2.5", "file": "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors",
         "license": "LTX-2.x Community License Agreement", "open_weights": True, "source": "https://example.test/m"}
OTHER = {"role": "image:qwen-image-2.1", "file": "qwen_image_2.1_int8_convrot.safetensors",
         "license": "Qwen Research License Agreement", "open_weights": True, "source": "https://example.test/q",
         "attribution": "Built with Qwen"}


def make_clip(path: Path, seconds: int = 2, size: str = "640x360") -> Path:
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=24:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


def finished_take(ledger: Ledger, *, models=(MODEL,), audit="pass", seconds: int = 2) -> str:
    take = ledger.create("direct", "A source take", {"subject": "x"})
    folder = ledger.take_dir(take["id"])
    make_clip(folder / "take.mp4", seconds)
    raw = receipts.new_receipt(
        take_id=take["id"], kind="direct", label="A source take", models=list(models),
        audit={"policy": "open-weights-only", "result": audit, "disallowed": [] if audit == "pass" else ["X"]})
    write_json(folder / "receipt.json", receipts.seal(raw))
    ledger.update(take["id"], status="succeeded", recipe_hash="abc")
    return take["id"]


@pytest.fixture
def ledger(tmp_path) -> Ledger:
    return Ledger(tmp_path / "takes")


def test_vertical_export_is_a_new_take_with_a_receipt_that_points_back(ledger):
    source = finished_take(ledger)
    made = export_vertical_sync(ledger, source, focus_x=0.3)
    folder = ledger.take_dir(made["id"])
    assert made["kind"] == "export" and made["parent"] == source and made["status"] == "succeeded"
    info = video.probe(folder / "take.mp4")
    assert (info.width, info.height) == (1080, 1920)
    receipt = json.loads((folder / "receipt.json").read_text())
    assert receipts.verify(receipt) and receipt["take"]["kind"] == "export"
    source_receipt = json.loads((ledger.take_dir(source) / "receipt.json").read_text())
    assert receipt["inputs"]["sources"] == [
        {"take": source, "receipt_digest": source_receipt["integrity"]["digest"]}]
    assert receipt["inputs"]["format"] == "9x16" and receipt["inputs"]["focus_x"] == 0.3
    assert [m["file"] for m in receipt["models"]] == [MODEL["file"]]  # the chain of custody survives
    assert receipt["audit"]["result"] == "pass"
    found, verified = receipts.read_media(folder / "take.mp4")
    assert verified and found["take"]["id"] == made["id"]


def test_reel_joins_takes_and_merges_their_provenance(ledger):
    a = finished_take(ledger, models=(MODEL,))
    b = finished_take(ledger, models=(MODEL, OTHER))
    made = export_reel_sync(ledger, [a, b], crossfade_s=0.5)
    folder = ledger.take_dir(made["id"])
    assert video.probe(folder / "take.mp4").duration_s == pytest.approx(3.5, abs=0.4)
    receipt = json.loads((folder / "receipt.json").read_text())
    assert sorted(m["file"] for m in receipt["models"]) == sorted([MODEL["file"], OTHER["file"]])
    assert [s["take"] for s in receipt["inputs"]["sources"]] == [a, b]
    assert receipts.verify(receipt)


def test_an_unfinished_audit_failure_in_a_source_fails_the_export_audit(ledger):
    good = finished_take(ledger)
    bad = finished_take(ledger, audit="fail")
    made = export_reel_sync(ledger, [good, bad], crossfade_s=0.0)
    receipt = json.loads((ledger.take_dir(made["id"]) / "receipt.json").read_text())
    assert receipt["audit"]["result"] == "fail" and receipt["audit"]["disallowed"] == ["X"]


def test_bad_exports_are_refused_cleanly(ledger):
    done = finished_take(ledger)
    running = ledger.create("direct", "still going", {})
    ledger.update(running["id"], status="running")
    with pytest.raises(LedgerError, match="not finished"):
        export_vertical_sync(ledger, running["id"])
    with pytest.raises(ValueError, match="between 2 and"):
        export_reel_sync(ledger, [done])
    with pytest.raises(ValueError, match="focus_x"):
        export_vertical_sync(ledger, done, focus_x=2.0)
    with pytest.raises(ValueError, match="half of the shortest"):
        export_reel_sync(ledger, [done, done], crossfade_s=1.5)  # clips are 2s
    with pytest.raises(LedgerError):
        export_vertical_sync(ledger, "tk_20260101_000000_abcd")
    assert all(t["kind"] != "export" for t in ledger.list())  # nothing half-made was left behind


def test_failed_export_is_recorded_as_failed(ledger, monkeypatch):
    source = finished_take(ledger, seconds=1)

    def boom(*args, **kwargs):
        raise video.VideoError("ffmpeg exploded")

    monkeypatch.setattr(video, "concat", boom)
    with pytest.raises(video.VideoError):
        export_reel_sync(ledger, [source, source], crossfade_s=0.0)
    failed = [t for t in ledger.list() if t["kind"] == "export"]
    assert failed and failed[0]["status"] == "failed" and failed[0]["error"]["code"] == "export_failed"


def test_export_routes(client):
    take = client.post("/api/takes/direct", json={
        "subject": "A lighthouse at dusk", "rig": {"movement": "static"}, "auto_approve": True}).json()
    import time

    for _ in range(300):
        if client.get(f"/api/takes/{take['id']}").json()["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.1)
    assert client.get(f"/api/takes/{take['id']}").json()["status"] == "succeeded"
    vertical = client.post(f"/api/takes/{take['id']}/export/vertical", json={"focus_x": 0.5})
    assert vertical.status_code == 201 and vertical.json()["kind"] == "export"
    assert client.get(f"/api/takes/{vertical.json()['id']}/media/poster.png").status_code == 200
    reel = client.post("/api/exports/reel", json={"take_ids": [take["id"], take["id"]], "crossfade_s": 0.2})
    assert reel.status_code == 201
    assert client.post(f"/api/takes/{take['id']}/export/vertical", json={"focus_x": 3}).status_code == 422
    assert client.post("/api/exports/reel", json={"take_ids": [take["id"]]}).status_code == 422
    assert client.post("/api/takes/tk_20260101_000000_abcd/export/vertical", json={}).status_code == 404
