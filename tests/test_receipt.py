from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import os
import re
import subprocess
import time
import urllib.parse
import zlib
from datetime import datetime, timezone
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

import openfield
from openfield.engine import receipt as rc
from openfield.engine import video

SECTIONS = {
    "schema",
    "app",
    "take",
    "inputs",
    "workflow",
    "models",
    "audit",
    "identity",
    "backend",
    "outputs",
    "disclosure",
}


@pytest.fixture(autouse=True)
def bundled_ffmpeg_without_ffprobe(monkeypatch):
    monkeypatch.setenv("OPENFIELD_FFMPEG", imageio_ffmpeg.get_ffmpeg_exe())
    monkeypatch.setattr(video, "ffprobe_exe", lambda: None)


def make_receipt(**overrides):
    sections = {
        "inputs": {
            "prompt": "a lighthouse at dusk",
            "seed": 1234,
            "duration_s": 5.0,
            "source": r"C:\Users\Alex\Videos\clip.mp4",
        },
        "workflow": {"template": "ltx_i2v", "sha256": "ab" * 32, "snapped": {"frames": [120, 121]}},
        "models": [
            {
                "role": "video",
                "file": "ltx-2.5.safetensors",
                "license": "LTX-2 Community",
                "open_weights": True,
                "source": "huggingface",
            },
            {
                "role": "vae",
                "file": r"D:\ComfyUI\models\vae\ltx-vae.safetensors",
                "license": "LTX-2 Community",
                "open_weights": True,
                "source": "huggingface",
            },
        ],
        "audit": {"policy": "open-weights-only", "result": "pass", "disallowed": []},
        "identity": {"status": "pass", "score": 0.71, "threshold": 0.5, "refs_used": 3},
        "backend": {
            "kind": "cloud",
            "job_id": "job-77",
            "timings": {"queue_s": 1.5, "run_s": 42.25},
        },
        "outputs": [
            {
                "role": "video",
                "file": "take_0001.mp4",
                "sha256": "cd" * 32,
                "content_type": "video/mp4",
                "seconds": 5.04,
            }
        ],
    }
    sections.update(overrides)
    return rc.new_receipt(
        take_id="take_0001",
        kind="video",
        label="Lighthouse at dusk",
        created_at="2026-10-16T12:00:00Z",
        **sections,
    )


def make_png(path: Path, text: dict[str, str] | None = None) -> Path:
    image = Image.linear_gradient("L").convert("RGB").resize((32, 24))
    info = PngInfo()
    for key, value in (text or {}).items():
        info.add_text(key, value)
    image.save(path, pnginfo=info)
    return path


@pytest.fixture(scope="module")
def clip(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("clips") / "clip.mp4"
    cmd = [video.ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y"]
    cmd += ["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=1"]
    cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac"]
    subprocess.run([*cmd, str(path)], check=True)
    return path


def pack_raw(data: bytes) -> str:
    return base64.urlsafe_b64encode(zlib.compress(data)).rstrip(b"=").decode("ascii")


def test_canonical_json_is_order_independent_and_compact():
    a = {"b": 1, "a": {"y": [1, 2], "x": None}}
    b = {"a": {"x": None, "y": [1, 2]}, "b": 1}
    assert rc.canonical_json(a) == rc.canonical_json(b) == b'{"a":{"x":null,"y":[1,2]},"b":1}'


def test_canonical_json_keeps_unicode_as_raw_utf8():
    assert rc.canonical_json({"k": "café 日本語 🎬"}) == '{"k":"café 日本語 🎬"}'.encode()


def test_canonical_json_floats_are_stable():
    values = [0.1 + 0.2, 1.0, 1, 1e22, -0.0, 5e-324, 2.5e-7, 12345.678]
    expected = b"[0.30000000000000004,1.0,1,1e+22,-0.0,5e-324,2.5e-07,12345.678]"
    assert rc.canonical_json(values) == expected
    assert rc.canonical_json(json.loads(expected)) == expected


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_canonical_json_rejects_non_finite_numbers(bad):
    with pytest.raises(ValueError):
        rc.canonical_json({"x": [bad]})


def test_sha256_helpers_match_hashlib(tmp_path):
    assert rc.sha256_hex(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    data = os.urandom(2_500_000)
    path = tmp_path / "blob.bin"
    path.write_bytes(data)
    assert rc.sha256_file(path) == hashlib.sha256(data).hexdigest()
    assert rc.sha256_file(str(path)) == rc.sha256_hex(data)


def test_new_receipt_has_every_section_with_defaults():
    receipt = rc.new_receipt(take_id="t1", kind="still")
    assert set(receipt) == SECTIONS
    assert receipt["schema"] == "openfield.receipt/1"
    assert receipt["app"] == {"name": "OpenField Studio", "version": openfield.__version__}
    take = receipt["take"]
    assert (take["id"], take["kind"], take["label"]) == ("t1", "still", "")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", take["created_at"])
    assert receipt["inputs"] == {} and receipt["models"] == [] and receipt["outputs"] == []
    assert set(receipt["workflow"]) == {"template", "sha256", "snapped"}
    assert set(receipt["audit"]) == {"policy", "result", "disallowed"}
    assert set(receipt["identity"]) == {"status", "score", "threshold", "refs_used"}
    assert set(receipt["backend"]) == {"kind", "job_id", "timings"}
    assert receipt["disclosure"] == (
        "AI-generated content. Made with OpenField Studio using open-weights models; "
        "see models and audit for the exact files."
    )
    assert receipt["disclosure"] == rc.DISCLOSURE


def test_new_receipt_stamps_the_current_utc_time():
    before = datetime.now(timezone.utc).replace(microsecond=0)
    stamp = rc.new_receipt(take_id="t", kind="video")["take"]["created_at"]
    moment = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert before <= moment <= datetime.now(timezone.utc)


def test_new_receipt_merges_partial_sections_over_defaults():
    receipt = rc.new_receipt(
        take_id="t",
        kind="motion",
        label="L",
        created_at="2026-01-02T03:04:05Z",
        app_version="9.9.9",
        identity={"status": "skipped"},
        backend={"kind": "local"},
        outputs=[{"role": "video", "file": "a.mp4"}],
        disclosure="custom",
    )
    assert receipt["app"]["version"] == "9.9.9"
    assert receipt["take"] == {
        "id": "t",
        "kind": "motion",
        "created_at": "2026-01-02T03:04:05Z",
        "label": "L",
    }
    assert receipt["identity"] == {
        "status": "skipped",
        "score": None,
        "threshold": None,
        "refs_used": 0,
    }
    assert receipt["backend"] == {"kind": "local", "job_id": "", "timings": {}}
    assert receipt["outputs"] == [{"role": "video", "file": "a.mp4"}]
    assert receipt["disclosure"] == "custom"


def test_new_receipt_copies_what_it_is_given():
    parts = ["a"]
    receipt = rc.new_receipt(take_id="t", kind="video", inputs={"parts": parts})
    parts.append("b")
    assert receipt["inputs"]["parts"] == ["a"]
    other = rc.new_receipt(take_id="t", kind="video")
    other["inputs"]["x"] = 1
    assert rc.new_receipt(take_id="t", kind="video")["inputs"] == {}


@pytest.mark.parametrize("name", ["bogus", "integrity", "schema", "take"])
def test_new_receipt_rejects_unknown_sections(name):
    with pytest.raises(TypeError, match=name):
        rc.new_receipt(take_id="t", kind="video", **{name: {}})


def test_seal_adds_integrity_over_the_canonical_body():
    sealed = rc.seal(make_receipt())
    body = {key: value for key, value in sealed.items() if key != "integrity"}
    digest = hashlib.sha256(rc.canonical_json(body)).hexdigest()
    assert sealed["integrity"] == {"alg": "sha256", "digest": digest}
    assert rc.verify(sealed) is True


def test_seal_does_not_modify_its_input():
    receipt = make_receipt()
    snapshot = copy.deepcopy(receipt)
    sealed = rc.seal(receipt)
    assert receipt == snapshot and "integrity" not in receipt
    sealed["take"]["label"] = "changed"
    assert receipt["take"]["label"] == "Lighthouse at dusk"


def test_seal_is_idempotent_and_replaces_a_stale_integrity_block():
    sealed = rc.seal(make_receipt())
    assert rc.seal(sealed) == sealed
    sealed["take"]["label"] = "edited"
    assert rc.verify(sealed) is False
    resealed = rc.seal(sealed)
    assert rc.verify(resealed) is True
    assert resealed["integrity"] != rc.seal(make_receipt())["integrity"]


def test_verify_survives_a_json_round_trip():
    receipt = make_receipt()
    receipt["take"]["label"] = "Café 日本語 🎬 \u2028"
    sealed = rc.seal(receipt)
    for text in (json.dumps(sealed), json.dumps(sealed, indent=2, ensure_ascii=False)):
        assert rc.verify(json.loads(text)) is True


def tamper_value(receipt):
    receipt["inputs"]["seed"] = 4321


def tamper_add_key(receipt):
    receipt["extra"] = True


def tamper_delete_section(receipt):
    del receipt["outputs"]


def tamper_nested_output(receipt):
    receipt["outputs"][0]["sha256"] = "00" * 32


def tamper_digest(receipt):
    receipt["integrity"]["digest"] = "0" * 64


def tamper_uppercase_digest(receipt):
    receipt["integrity"]["digest"] = receipt["integrity"]["digest"].upper()


def tamper_alg(receipt):
    receipt["integrity"]["alg"] = "md5"


def tamper_drop_integrity(receipt):
    del receipt["integrity"]


def tamper_integrity_type(receipt):
    receipt["integrity"] = "sha256:abc"


def tamper_digest_type(receipt):
    receipt["integrity"]["digest"] = None


@pytest.mark.parametrize(
    "tamper",
    [
        tamper_value,
        tamper_add_key,
        tamper_delete_section,
        tamper_nested_output,
        tamper_digest,
        tamper_uppercase_digest,
        tamper_alg,
        tamper_drop_integrity,
        tamper_integrity_type,
        tamper_digest_type,
    ],
)
def test_verify_rejects_any_tampering(tamper):
    sealed = rc.seal(make_receipt())
    assert rc.verify(sealed)
    tamper(sealed)
    assert rc.verify(sealed) is False


def test_verify_never_raises_on_malformed_input():
    cyclic: dict = {}
    cyclic["self"] = cyclic
    deep: list = []
    for _ in range(5000):
        deep = [deep]
    sealed = rc.seal(make_receipt())
    unserialisable = [float("nan"), {1, 2}, object(), b"bytes", cyclic, deep, {1: "a", "b": 2}]
    for index, junk in enumerate(unserialisable):
        broken = copy.deepcopy(sealed)
        broken["inputs"][f"junk{index}"] = junk
        assert rc.verify(broken) is False
    for junk in (None, 42, "text", [], (), {}, {"integrity": 1}, {"integrity": {"alg": "sha256"}}):
        assert rc.verify(junk) is False


def test_scrub_reduces_absolute_paths_to_file_names():
    messy = {
        "win": r"C:\Users\Alex\Videos\take 1.mp4",
        "win_forward": "C:/Users/Alex/Videos/take.mp4",
        "win_spaces_in_user": r"C:\Users\John Smith\My Videos\a b.mp4",
        "unc": r"\\NAS\media\alex\clip.mp4",
        "home": "/home/alex/outputs/a.png",
        "mac": "/Users/alex/Library/Caches/b.png",
        "wsl": "/mnt/c/Users/Alex/c.png",
        "root": "/root/.cache/y.bin",
        "prose": r"read C:\Users\Alex\a.png then /home/alex/b.png, ok",
        "nested": {"list": [r"D:\ComfyUI\models\x.safetensors", ["/home/alex/z.txt"]]},
    }
    out = rc.scrub(messy)
    assert out == {
        "win": "take 1.mp4",
        "win_forward": "take.mp4",
        "win_spaces_in_user": "a b.mp4",
        "unc": "clip.mp4",
        "home": "a.png",
        "mac": "b.png",
        "wsl": "c.png",
        "root": "y.bin",
        "prose": "read a.png then b.png, ok",
        "nested": {"list": ["x.safetensors", ["z.txt"]]},
    }
    assert not re.search(r"alex|john|smith", json.dumps(out), re.IGNORECASE)


def test_scrub_never_leaves_a_bare_home_directory_name():
    homes = {"a": "/home/alex", "b": r"C:\Users\Alex", "c": "/Users/alex/"}
    assert rc.scrub(homes) == {"a": "~", "b": "~", "c": "~"}


def test_scrub_leaves_urls_relative_paths_and_ratios_alone():
    safe = {
        "url": "https://example.com/home/x.png",
        "comfy": "http://127.0.0.1:8188/view?filename=a.png&type=output",
        "relative": "checkpoints/ltx-2.5.safetensors",
        "windows_relative": "models\\checkpoints\\ltx.safetensors",
        "ratio": "16/9 24/1 1/2",
        "endpoint": "/api/v1/prompt",
        "number": 3.5,
        "flag": True,
        "nothing": None,
    }
    assert rc.scrub(safe) == safe


def test_scrub_drops_secret_keys_at_any_depth_case_insensitively():
    data = {
        "Authorization": "Bearer x",
        "inputs": {
            "API_KEY": "k",
            "hf_token": "t",
            "nested": [{"Password": "p", "keep": 1}],
            "x-api-key": "z",
            "client_secret": "s",
            "ApiKey": "a",
        },
        "backend": {"comfy_api_key": "c", "kind": "cloud"},
    }
    assert rc.scrub(data) == {"inputs": {"nested": [{"keep": 1}]}, "backend": {"kind": "cloud"}}


def test_scrub_returns_a_deep_copy_and_is_idempotent():
    original = {"a": [{"b": r"C:\x\y.png"}], "t": (1, 2)}
    once = rc.scrub(original)
    assert original["a"][0]["b"] == r"C:\x\y.png"
    once["a"][0]["b"] = "changed"
    assert original["a"][0]["b"] == r"C:\x\y.png"
    assert rc.scrub(rc.scrub(original)) == rc.scrub(original)


def test_scrub_turns_numpy_values_into_plain_json_types():
    report = {
        "score": np.float32(0.5),
        "box": (np.int64(1), np.int64(2)),
        "ok": np.bool_(True),
        "vector": np.array([1.5, 2.5]),
    }
    out = rc.scrub(report)
    assert out == {"score": 0.5, "box": [1, 2], "ok": True, "vector": [1.5, 2.5]}
    assert type(out["score"]) is float and type(out["box"][0]) is int
    receipt = make_receipt(identity={"status": "pass", **report})
    sealed = rc.seal(receipt)
    assert rc.verify(json.loads(json.dumps(sealed))) is True


def test_scrub_accepts_path_objects_and_cleans_keys():
    out = rc.scrub({"p": Path(r"C:\Users\Alex\x.png"), r"C:\Users\Alex\key.txt": 1})
    assert out == {"p": "x.png", "key.txt": 1}


def test_seal_scrubs_before_hashing():
    receipt = make_receipt()
    receipt["backend"]["api_key"] = "sk-secret"
    receipt["inputs"]["Authorization"] = "Bearer abc"
    sealed = rc.seal(receipt)
    text = json.dumps(sealed)
    assert "sk-secret" not in text and "Bearer" not in text
    assert "Alex" not in text and "C:\\" not in text and "D:\\" not in text
    assert sealed["inputs"]["source"] == "clip.mp4"
    assert sealed["models"][1]["file"] == "ltx-vae.safetensors"
    assert rc.verify(sealed) is True
    assert "api_key" in receipt["backend"]  # the caller's copy is untouched


def test_sidecar_path_appends_to_the_full_file_name(tmp_path):
    assert rc.sidecar_path(tmp_path / "clip.mp4") == tmp_path / "clip.mp4.receipt.json"
    assert rc.sidecar_path("a/b.png").name == "b.png.receipt.json"


def test_sidecar_round_trip(tmp_path):
    media = tmp_path / "clip.mp4"
    sealed = rc.seal(make_receipt())
    sealed["take"]["label"] = "Café 日本語"
    sealed = rc.seal(sealed)
    path = rc.write_sidecar(media, sealed)
    assert path == tmp_path / "clip.mp4.receipt.json"
    text = path.read_text(encoding="utf-8")
    assert text.endswith("}\n") and "日本語" in text
    assert rc.read_sidecar(media) == sealed
    assert rc.verify(rc.read_sidecar(media)) is True


@pytest.mark.parametrize("content", [b"{not json", b"[1, 2]", b'"text"', b"\xff\xfe\x00junk", b""])
def test_read_sidecar_is_none_for_missing_or_unusable_files(tmp_path, content):
    media = tmp_path / "m.mp4"
    assert rc.read_sidecar(media) is None
    rc.sidecar_path(media).write_bytes(content)
    assert rc.read_sidecar(media) is None


def test_png_round_trip_keeps_pixels(tmp_path):
    source = make_png(tmp_path / "src.png")
    sealed = rc.seal(make_receipt())
    out = rc.embed_png(source, tmp_path / "nested" / "out.png", sealed)
    assert out == tmp_path / "nested" / "out.png"
    assert rc.read_png(out) == sealed
    assert rc.verify(rc.read_png(out)) is True
    with Image.open(source) as before, Image.open(out) as after:
        assert (before.size, before.mode) == (after.size, after.mode)
        assert before.tobytes() == after.tobytes()
    assert rc.read_png(source) is None


def test_png_chunk_is_compact_canonical_json_in_itxt(tmp_path):
    sealed = rc.seal(make_receipt())
    out = rc.embed_png(make_png(tmp_path / "src.png"), tmp_path / "out.png", sealed)
    with Image.open(out) as image:
        assert image.info["openfield.receipt"].encode("utf-8") == rc.canonical_json(sealed)
    raw = out.read_bytes()
    assert b"iTXt" in raw and b"openfield.receipt" in raw
    assert raw.index(b"iTXt") < raw.index(b"IDAT")


def test_png_keeps_existing_text_chunks_and_replaces_an_old_receipt(tmp_path):
    comfy = {"prompt": '{"3": {"class_type": "KSampler"}}', "workflow": '{"nodes": []}'}
    source = make_png(tmp_path / "src.png", text=comfy)
    first, second = rc.seal(make_receipt()), rc.seal(make_receipt(inputs={"seed": 1}))
    once = rc.embed_png(source, tmp_path / "once.png", first)
    twice = rc.embed_png(once, tmp_path / "twice.png", second)
    with Image.open(twice) as image:
        assert image.text["prompt"] == comfy["prompt"]
        assert image.text["workflow"] == comfy["workflow"]
    assert rc.read_png(twice) == second
    assert twice.read_bytes().count(b"iTXtopenfield.receipt\x00") == 1


def test_png_round_trips_unicode(tmp_path):
    receipt = make_receipt()
    receipt["take"]["label"] = "Café 日本語 🎬"
    sealed = rc.seal(receipt)
    out = rc.embed_png(make_png(tmp_path / "src.png"), tmp_path / "out.png", sealed)
    assert rc.read_png(out) == sealed


def test_png_can_be_embedded_in_place(tmp_path):
    path = make_png(tmp_path / "pic.png")
    sealed = rc.seal(make_receipt())
    rc.embed_png(path, path, sealed)
    assert rc.read_png(path) == sealed
    assert [p.name for p in tmp_path.iterdir()] == ["pic.png"]


def test_png_embedding_converts_other_image_formats(tmp_path):
    jpeg = tmp_path / "pic.jpg"
    Image.linear_gradient("L").convert("RGB").save(jpeg, "JPEG")
    sealed = rc.seal(make_receipt())
    out = rc.embed_png(jpeg, tmp_path / "pic.png", sealed)
    assert rc.read_png(out) == sealed
    assert rc.read_png(jpeg) is None


def test_png_embedding_failure_leaves_nothing_behind(tmp_path):
    out = tmp_path / "out.png"
    with pytest.raises(FileNotFoundError):
        rc.embed_png(tmp_path / "missing.png", out, make_receipt())
    junk = tmp_path / "junk.png"
    junk.write_bytes(b"not an image")
    with pytest.raises(OSError):
        rc.embed_png(junk, out, make_receipt())
    assert [p.name for p in tmp_path.iterdir()] == ["junk.png"]


def test_png_with_a_broken_receipt_chunk_reads_as_none(tmp_path):
    for broken in ("{not json", "[1, 2]", ""):
        path = make_png(tmp_path / "broken.png", text={"openfield.receipt": broken})
        assert rc.read_png(path) is None


def test_mp4_round_trip(clip, tmp_path):
    sealed = rc.seal(make_receipt())
    out = rc.embed_mp4(clip, tmp_path / "tagged.mp4", sealed)
    assert out == tmp_path / "tagged.mp4"
    assert rc.read_mp4(out) == sealed
    assert rc.verify(rc.read_mp4(out)) is True
    assert rc.read_mp4(clip) is None


def test_mp4_tag_is_base64url_zlib_of_the_canonical_json(clip, tmp_path):
    sealed = rc.seal(make_receipt())
    out = rc.embed_mp4(clip, tmp_path / "tagged.mp4", sealed)
    token = video.read_metadata(out)["openfield_receipt"]
    assert re.fullmatch(r"[A-Za-z0-9_-]+", token)
    padded = token + "=" * (-len(token) % 4)
    assert zlib.decompress(base64.urlsafe_b64decode(padded)) == rc.canonical_json(sealed)


def test_mp4_keeps_the_media_intact(clip, tmp_path):
    out = rc.embed_mp4(clip, tmp_path / "tagged.mp4", rc.seal(make_receipt()))
    before, after = video.probe(clip), video.probe(out)
    assert (after.width, after.height, after.fps) == (before.width, before.height, before.fps)
    assert (after.video_codec, after.has_audio) == ("h264", True)
    assert after.duration_s == pytest.approx(before.duration_s, abs=0.05)


def test_mp4_round_trips_a_large_receipt(clip, tmp_path):
    receipt = make_receipt()
    receipt["inputs"]["notes"] = os.urandom(20_000).hex()  # incompressible: ~40 KB packed
    sealed = rc.seal(receipt)
    out = rc.embed_mp4(clip, tmp_path / "big.mp4", sealed)
    assert len(video.read_metadata(out)["openfield_receipt"]) > 20_000
    assert rc.read_mp4(out) == sealed


def test_mp4_with_a_garbage_tag_reads_as_none(clip, tmp_path):
    cases = {
        "not base64!": "not base64!",
        "valid base64, not zlib": base64.urlsafe_b64encode(b"hello world").decode(),
        "zlib, not json": pack_raw(b"{oops"),
        "json, not an object": pack_raw(b"[1,2,3]"),
    }
    for name, token in cases.items():
        out = video.embed_metadata(clip, tmp_path / "garbage.mp4", {"openfield_receipt": token})
        assert rc.read_mp4(out) is None, name


def test_read_media_finds_png_mp4_and_sidecar_receipts(clip, tmp_path):
    sealed = rc.seal(make_receipt())
    png = rc.embed_png(make_png(tmp_path / "a.png"), tmp_path / "b.png", sealed)
    mp4 = rc.embed_mp4(clip, tmp_path / "b.mp4", sealed)
    other = tmp_path / "c.webm"
    other.write_bytes(b"\x1a\x45\xdf\xa3 pretend webm")
    rc.write_sidecar(other, sealed)
    for path in (png, mp4, other):
        assert rc.read_media(path) == (sealed, True)
        assert rc.read_media(str(path)) == (sealed, True)


def test_read_media_reports_tampering_but_still_returns_the_receipt(clip, tmp_path):
    forged = rc.seal(make_receipt())
    forged["take"]["label"] = "forged"
    unsealed = make_receipt()
    source = make_png(tmp_path / "src.png")
    forged_png = rc.embed_png(source, tmp_path / "forged.png", forged)
    unsealed_png = rc.embed_png(source, tmp_path / "unsealed.png", unsealed)
    forged_mp4 = rc.embed_mp4(clip, tmp_path / "forged.mp4", forged)
    assert rc.read_media(forged_png) == (forged, False)
    assert rc.read_media(unsealed_png) == (unsealed, False)
    assert rc.read_media(forged_mp4) == (forged, False)


def test_read_media_prefers_the_embedded_receipt_over_the_sidecar(tmp_path):
    embedded, sidecar = rc.seal(make_receipt()), rc.seal(make_receipt(inputs={"seed": 5}))
    png = rc.embed_png(make_png(tmp_path / "a.png"), tmp_path / "b.png", embedded)
    rc.write_sidecar(png, sidecar)
    assert rc.read_media(png) == (embedded, True)


def test_read_media_falls_back_to_the_sidecar_when_nothing_is_embedded(clip, tmp_path):
    sealed = rc.seal(make_receipt())
    png, mp4 = make_png(tmp_path / "plain.png"), tmp_path / "plain.mp4"
    mp4.write_bytes(clip.read_bytes())
    assert rc.read_media(png) is None and rc.read_media(mp4) is None
    rc.write_sidecar(png, sealed)
    rc.write_sidecar(mp4, sealed)
    assert rc.read_media(png) == (sealed, True)
    assert rc.read_media(mp4) == (sealed, True)


def test_read_media_accepts_a_bare_receipt_file(tmp_path):
    sealed = rc.seal(make_receipt())
    sidecar = rc.write_sidecar(tmp_path / "take.mp4", sealed)
    assert rc.read_media(sidecar) == (sealed, True)
    bom = tmp_path / "bom.json"
    bom.write_bytes(b"\xef\xbb\xbf\n" + json.dumps(sealed).encode("utf-8"))
    assert rc.read_media(bom) == (sealed, True)
    for name, content in {"list.json": b"[1, 2]", "cut.json": b'{"schema": "openf'}.items():
        (tmp_path / name).write_bytes(content)
        assert rc.read_media(tmp_path / name) is None


def test_read_media_does_not_slurp_huge_json_files(tmp_path):
    huge = tmp_path / "huge.json"
    huge.write_bytes(b'{"padding": "' + b"x" * (5 * 1024 * 1024) + b'"}')
    assert rc.read_media(huge) is None


def test_read_media_uses_the_sidecar_when_the_embedded_receipt_is_broken(tmp_path):
    sealed = rc.seal(make_receipt())
    png = make_png(tmp_path / "broken.png", text={"openfield.receipt": "{not json"})
    assert rc.read_media(png) is None
    rc.write_sidecar(png, sealed)
    assert rc.read_media(png) == (sealed, True)


def test_read_media_returns_none_for_unknown_missing_or_broken_files(tmp_path):
    assert rc.read_media(tmp_path / "missing.mp4") is None
    junk = tmp_path / "junk.bin"
    junk.write_bytes(os.urandom(64))
    assert rc.read_media(junk) is None
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    assert rc.read_media(empty) is None
    truncated = tmp_path / "cut.png"
    truncated.write_bytes(make_png(tmp_path / "full.png").read_bytes()[:40])
    assert rc.read_media(truncated) is None
    fake_mp4 = tmp_path / "fake.mp4"
    fake_mp4.write_bytes(b"\x00\x00\x00\x18ftypisom" + os.urandom(40))
    assert rc.read_media(fake_mp4) is None
    rc.sidecar_path(fake_mp4).write_text("{broken", encoding="utf-8")
    assert rc.read_media(fake_mp4) is None


def test_recipe_from_receipt_keeps_only_what_restores_a_take():
    sealed = rc.seal(make_receipt())
    recipe = rc.recipe_from_receipt(sealed)
    assert recipe == {
        "schema": "openfield.recipe/1",
        "kind": "video",
        "template": "ltx_i2v",
        "inputs": {
            "prompt": "a lighthouse at dusk",
            "seed": 1234,
            "duration_s": 5.0,
            "source": "clip.mp4",
        },
        "models": [
            {"role": "video", "file": "ltx-2.5.safetensors"},
            {"role": "vae", "file": "ltx-vae.safetensors"},
        ],
        "seed": 1234,
    }
    text = json.dumps(recipe)
    assert "job-77" not in text and "Alex" not in text and "C:\\" not in text


def test_recipe_from_receipt_scrubs_an_unsealed_receipt_too():
    receipt = make_receipt()
    receipt["inputs"]["hf_token"] = "hf_secret"
    receipt["inputs"]["extra"] = {"cache": "/home/alex/.cache/ref.png"}
    recipe = rc.recipe_from_receipt(receipt)
    assert "hf_secret" not in json.dumps(recipe)
    assert recipe["inputs"]["extra"] == {"cache": "ref.png"}
    assert recipe["inputs"]["source"] == "clip.mp4"


def test_recipe_from_receipt_tolerates_sparse_or_odd_receipts():
    assert rc.recipe_from_receipt({}) == {
        "schema": "openfield.recipe/1",
        "kind": "",
        "template": "",
        "inputs": {},
        "models": [],
        "seed": None,
    }
    odd = {"take": "x", "inputs": [1], "workflow": None, "models": [1, {"role": "a"}, "b"]}
    recipe = rc.recipe_from_receipt(odd)
    assert recipe["models"] == [{"role": "a", "file": ""}]
    assert recipe["inputs"] == {} and recipe["kind"] == ""


def test_recipe_link_round_trip_is_url_fragment_safe():
    recipe = rc.recipe_from_receipt(rc.seal(make_receipt()))
    link = rc.recipe_link(recipe)
    assert re.fullmatch(r"[A-Za-z0-9_-]+", link)
    assert urllib.parse.quote(link, safe="") == link
    assert rc.parse_recipe_link(link) == recipe
    assert rc.recipe_link(copy.deepcopy(recipe)) == link
    assert len(link) < len(rc.canonical_json(recipe))


def test_parse_recipe_link_round_trips_arbitrary_objects_and_tolerates_whitespace():
    recipe = {"kind": "still", "inputs": {"prompt": "café 日本語 🎬", "n": [1, 2.5, None, True]}}
    link = rc.recipe_link(recipe)
    assert rc.parse_recipe_link(f"  {link}\n") == recipe
    assert rc.parse_recipe_link(link + "=" * (-len(link) % 4)) == recipe


@pytest.mark.parametrize(
    "garbage",
    [
        "",
        "   ",
        "!!!",
        "not a link",
        "abc",
        "A" * 40,
        "ab+/cd==",
        base64.urlsafe_b64encode(b"hello world").decode(),
        pack_raw(b"{oops"),
        pack_raw(b"[1,2,3]"),
        pack_raw(b'"just a string"'),
        pack_raw(b"null"),
        pack_raw(b"\xff\xfe"),
        pack_raw(b"[" * 200_000),
    ],
)
def test_parse_recipe_link_rejects_garbage(garbage):
    with pytest.raises(ValueError):
        rc.parse_recipe_link(garbage)


def test_parse_recipe_link_rejects_links_with_foreign_characters():
    link = rc.recipe_link({"kind": "video", "inputs": {"r": os.urandom(30).hex()}})
    for noise in ("!!", "+", " ", "/"):
        with pytest.raises(ValueError):
            rc.parse_recipe_link(link[:10] + noise + link[10:])


def test_parse_recipe_link_rejects_truncated_links():
    link = rc.recipe_link({"kind": "video", "inputs": {"r": os.urandom(300).hex()}})
    for cut in (1, 10, len(link) // 2):
        with pytest.raises(ValueError):
            rc.parse_recipe_link(link[:-cut])


@pytest.mark.parametrize("junk", [None, 5, b"abc", ["a"], {"a": 1}])
def test_parse_recipe_link_rejects_non_strings(junk):
    with pytest.raises(ValueError):
        rc.parse_recipe_link(junk)


def test_parse_recipe_link_refuses_decompression_bombs():
    bomb = pack_raw(b'"' + b"0" * 60_000_000 + b'"')
    assert len(bomb) < 100_000
    started = time.perf_counter()
    with pytest.raises(ValueError, match="oversized"):
        rc.parse_recipe_link(bomb)
    assert time.perf_counter() - started < 2.0


def test_a_take_travels_from_receipt_to_remix(clip, tmp_path):
    receipt = make_receipt()
    receipt["outputs"][0]["sha256"] = rc.sha256_file(clip)
    sealed = rc.seal(receipt)
    delivered = rc.embed_mp4(clip, tmp_path / "take.mp4", sealed)
    rc.write_sidecar(delivered, sealed)
    found, verified = rc.read_media(delivered)
    assert verified and found == sealed
    link = rc.recipe_link(rc.recipe_from_receipt(found))
    assert rc.parse_recipe_link(link)["seed"] == 1234


def test_scrub_redacts_a_key_quoted_inside_free_text():
    from openfield.engine.receipt import scrub

    # the fake keys are assembled at run time, so the release gate's own secret scan never mistakes this file for a leak
    key, token = "comfyui" + "-" + "ABCDEFGHIJKLMNOPQRST", "hf" + "_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    noisy = {"error": {"message": f"401 from the proxy with Authorization: Bearer sk-abcDEF0123456789xyz and key {key}, token {token}"}}
    clean = scrub(noisy)["error"]["message"]
    assert "sk-abcDEF" not in clean and key not in clean and token[:13] not in clean
    assert "Bearer [redacted]" in clean and clean.count("[redacted]") == 3
    assert scrub({"note": "a bearer of good news"})["note"] == "a bearer of good news", "ordinary words are left alone"
