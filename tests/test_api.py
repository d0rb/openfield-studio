from __future__ import annotations

import io
import json
import subprocess
import time
import zipfile
from pathlib import Path

import imageio_ffmpeg
from PIL import Image

DONE = {"succeeded", "failed", "canceled"}


def png_bytes(color="red", size=(96, 54)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def clip_bytes(tmp_path: Path) -> bytes:
    path = tmp_path / "phone.mp4"
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=330:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
    return path.read_bytes()


def wait_for(client, take_id, states=DONE, timeout=60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        take = client.get(f"/api/takes/{take_id}").json()
        if take["status"] in states:
            return take
        time.sleep(0.1)
    raise AssertionError(f"take {take_id} never reached {states}: {take}")


def start_direct(client, **body):
    payload = {"subject": "A lighthouse at dusk", "rig": {"movement": "dolly_in"}, "seed": 5,
               "auto_approve": True, **body}
    response = client.post("/api/takes/direct", json=payload)
    assert response.status_code == 202, response.text
    return response.json()


def test_status_reports_backend_policy_and_ui(client):
    status = client.get("/api/status").json()
    assert status["policy"] == "open-weights-only" and status["version"]
    assert status["backend"]["kind"] == "pod" and status["backend"]["health"]["ok"] is True
    assert status["backend"]["locked"] is False
    assert "OpenField" in client.get("/").text
    assert client.get("/dashboard", follow_redirects=False).status_code in {301, 302, 307}


def test_the_live_app_answers_the_hosted_replay_probe_quietly(client):
    answer = client.get("/static/manifest.json")
    assert answer.status_code == 200 and answer.json() == {"static": False}


def test_move_catalog_has_all_35_moves(client):
    data = client.get("/api/moves").json()
    assert len(data["moves"]) == 35 and len(data["groups"]) == 7
    assert all(m["path"] for m in data["moves"])


def test_plan_compiles_and_rejects_bad_rigs(client):
    ok = client.post("/api/direct/plan", json={"subject": "A bottle", "rig": {"movement": "orbit_360"}})
    assert ok.status_code == 200
    body = ok.json()
    assert len(body["plan"]["segments"]) == 4 and body["templates"]["ltx25_flf2v"] == "ready"
    bad = client.post("/api/direct/plan", json={"subject": "A bottle", "rig": {"movement": "teleport"}})
    assert bad.status_code == 422 and "unsupported movement" in bad.json()["error"]["message"]
    typo = client.post("/api/direct/plan", json={"subject": "A bottle", "rig": {"zoom": 3}})
    assert typo.status_code == 422
    short = client.post("/api/direct/plan", json={"subject": "hi"})
    assert short.status_code == 422


def test_direct_take_end_to_end_over_http(client):
    take = start_direct(client)
    done = wait_for(client, take["id"])
    assert done["status"] == "succeeded", done["error"]
    base = f"/api/takes/{take['id']}"

    poster = client.get(f"{base}/media/poster.png")
    assert poster.status_code == 200 and poster.headers["content-type"] == "image/png"
    video = client.get(f"{base}/media/take.mp4", headers={"Range": "bytes=0-99"})
    assert video.status_code in {200, 206} and len(video.content) >= 1

    info = client.get(f"{base}/receipt").json()
    assert info["verified"] is True and info["recipe_link"]
    assert info["receipt"]["audit"]["result"] == "pass"

    archive = zipfile.ZipFile(io.BytesIO(client.get(f"{base}/workflows.zip").content))
    names = archive.namelist()
    assert "README.txt" in names and len([n for n in names if n.endswith(".api.json")]) == 3
    assert "COMFY_BASE_URL" in client.get(f"{base}/sdk-snippet").text
    assert [t["id"] for t in client.get("/api/takes").json()] == [take["id"]]


def test_quick_mode_over_http_changes_the_plan(client):
    body = {"subject": "A lighthouse at dusk", "rig": {"movement": "dolly_in"}}
    full = client.post("/api/direct/plan", json=body).json()["plan"]
    quick = client.post("/api/direct/plan", json=body | {"prompt_only": True}).json()["plan"]
    assert full["mode"] == "keyframed" and len(full["anchors"]) == 2
    assert quick["mode"] == "prompt_only" and len(quick["anchors"]) == 1
    take = start_direct(client, rig={"movement": "dolly_in"}, prompt_only=True)
    done = wait_for(client, take["id"])
    assert done["status"] == "succeeded" and done["recipe"]["prompt_only"] is True


def test_events_stream_ends_with_the_final_status(client):
    take = start_direct(client, rig={"movement": "static"})
    lines = []
    with client.stream("GET", f"/api/takes/{take['id']}/events") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        lines = [ln for ln in response.iter_lines() if ln.startswith("data: ")]
    events = [json.loads(ln[6:]) for ln in lines]
    assert events[-1] == {**events[-1], "type": "end", "status": "succeeded"}
    assert {"stage", "run", "take"} <= {e["type"] for e in events}


def test_approval_over_http(client):
    take = start_direct(client, auto_approve=False)
    waiting = wait_for(client, take["id"], {"awaiting_approval", *DONE})
    assert waiting["status"] == "awaiting_approval" and len(waiting["anchors"]) == 2
    assert client.get(f"/api/takes/{take['id']}/media/{waiting['anchors'][1]['file']}").status_code == 200
    assert client.post(f"/api/takes/{take['id']}/approve", json={"reroll": []}).status_code == 200
    assert wait_for(client, take["id"])["status"] == "succeeded"
    assert client.post(f"/api/takes/{take['id']}/approve", json={}).status_code == 422


def test_cast_requires_consent_and_feeds_the_take(client):
    files = [("files", ("a.png", png_bytes("red"), "image/png")),
             ("files", ("b.png", png_bytes("blue"), "image/png"))]
    no_consent = client.post("/api/cast", data={"name": "Mara", "kind": "character"}, files=files)
    assert no_consent.status_code == 422
    wrong = client.post("/api/cast", data={"name": "Mara", "kind": "character", "consent": "whatever"},
                        files=files)
    assert wrong.status_code == 422 and "consent" in wrong.json()["error"]["message"]
    created = client.post("/api/cast", data={"name": "Mara", "kind": "character", "consent": "fictional"},
                          files=files)
    assert created.status_code == 201
    cast = created.json()
    assert cast["id"].startswith("ca_") and len(cast["refs"]) == 2 and cast["consent"] == "fictional"
    assert client.get(f"/api/cast/{cast['id']}/refs/ref_1.png").headers["content-type"] == "image/png"
    assert client.get(f"/api/cast/{cast['id']}/refs/..%2Fcast.json").status_code in {404, 422}
    assert [c["id"] for c in client.get("/api/cast").json()] == [cast["id"]]

    take = start_direct(client, rig={"movement": "static"}, cast_id=cast["id"])
    done = wait_for(client, take["id"])
    assert done["status"] == "succeeded", done["error"]
    receipt = client.get(f"/api/takes/{take['id']}/receipt").json()["receipt"]
    assert len(receipt["inputs"]["cast"]["refs"]) == 2 and receipt["inputs"]["cast"]["name"] == "Mara"
    assert client.delete(f"/api/cast/{cast['id']}").status_code == 204
    bad_image = client.post("/api/cast", data={"name": "X", "kind": "product", "consent": "mine"},
                            files=[("files", ("x.png", b"not an image", "image/png"))])
    assert bad_image.status_code == 422


def test_reshoot_over_http_and_upload_rules(client, tmp_path):
    clip = clip_bytes(tmp_path)
    ok = client.post(
        "/api/takes/reshoot", data={"prompt": "A robot dancing", "seed": "3"},
        files={"source": ("phone.mp4", clip, "video/mp4"), "reference": ("hero.png", png_bytes(), "image/png")})
    assert ok.status_code == 202, ok.text
    done = wait_for(client, ok.json()["id"])
    assert done["status"] == "succeeded", done["error"]
    base = f"/api/takes/{done['id']}/media"
    assert client.get(f"{base}/inputs/source.mp4").status_code == 200
    assert client.get(f"{base}/inputs/reference.png").status_code == 200

    wrong_type = client.post(
        "/api/takes/reshoot", data={"prompt": "x"},
        files={"source": ("run.exe", b"MZ", "application/octet-stream"),
               "reference": ("hero.png", png_bytes(), "image/png")})
    assert wrong_type.status_code == 422
    no_ref = client.post("/api/takes/reshoot", data={"prompt": "x"},
                         files={"source": ("phone.mp4", clip, "video/mp4")})
    assert no_ref.status_code == 422


def test_media_endpoint_cannot_escape_a_take_folder(client):
    take = start_direct(client, rig={"movement": "static"})
    wait_for(client, take["id"])
    for path in ("../../take.json", "..%2F..%2Fsecret", "runs/../../../pyproject.toml", "nope.bin", "a/b/c/d.png"):
        assert client.get(f"/api/takes/{take['id']}/media/{path}").status_code in {404, 422}, path
    assert client.get("/api/takes/not-a-take").status_code == 404
    assert client.get("/api/takes/tk_20260101_000000_abcd/media/take.mp4").status_code == 404


def test_replay_mode_refuses_unrecorded_recipes_and_switching_back_works(client):
    assert client.post("/api/backend", json={"mode": "replay"}).json()["backend"]["locked"] is True
    take = start_direct(client)
    failed = wait_for(client, take["id"])
    assert failed["status"] == "failed" and failed["error"]["code"] == "replay_unavailable"
    assert client.post("/api/backend", json={"mode": "sdk"}).json()["backend"]["kind"] == "pod"
    assert client.post("/api/backend", json={"mode": "banana"}).status_code == 422


def test_a_recorded_take_can_be_recreated_in_replay_mode(client):
    original = start_direct(client, rig={"movement": "static"}, seed=21)
    assert wait_for(client, original["id"])["status"] == "succeeded"

    # with a live backend, recreate is refused and points at Remix
    refused = client.post("/api/replay/recreate", json={"id": original["id"]})
    assert refused.status_code == 409 and "Remix" in refused.json()["error"]["message"]

    client.post("/api/backend", json={"mode": "replay"})
    shelf = client.get("/api/replay/recorded").json()
    assert [r["id"] for r in shelf] == [original["id"]]
    assert shelf[0]["media_base"] == f"/api/takes/{original['id']}/media"
    assert shelf[0]["recipe"]["rig"]["movement"] == "static"

    made = client.post("/api/replay/recreate", json={"id": original["id"]})
    assert made.status_code == 202
    done = wait_for(client, made.json()["id"])
    assert done["status"] == "succeeded" and done["replay"] is True and done["replay_of"] == original["id"]
    assert done["label"].endswith("(replay)") and done["backend"]["kind"] == "replay"
    assert client.get(f"/api/takes/{done['id']}/media/take.mp4").status_code == 200
    assert client.get(f"/api/takes/{done['id']}/receipt").json()["verified"] is True

    missing = client.post("/api/replay/recreate", json={"id": "tk_20260101_000000_ffff"})
    assert missing.status_code == 409 and missing.json()["error"]["code"] == "replay_unavailable"
    assert client.post("/api/replay/recreate", json={}).status_code == 409


def test_a_generated_character_becomes_a_cast_with_its_provenance(client):
    made = client.post("/api/cast/generate",
                       json={"description": "a courier with a yellow raincoat", "count": 2, "seed": 9})
    assert made.status_code == 202
    take = wait_for(client, made.json()["id"])
    assert take["status"] == "succeeded" and take["kind"] == "portrait" and len(take["candidates"]) == 2
    assert client.get(f"/api/takes/{take['id']}/media/candidates/02.png").status_code == 200
    assert [t["id"] for t in client.get("/api/takes", params={"kind": "portrait"}).json()] == [take["id"]]

    kept = client.post("/api/cast/from-take", json={"take_id": take["id"], "candidate": 2, "name": "Courier"})
    assert kept.status_code == 201, kept.text
    cast = kept.json()
    assert cast["kind"] == "character" and cast["consent"] == "fictional" and len(cast["refs"]) == 1
    origin = cast["origin"]
    assert origin["generated"] is True and origin["take"] == take["id"] and origin["seed"] == 10
    assert origin["prompt"].startswith("A photographic head-and-shoulders portrait of a courier")
    assert origin["disclosure"] == "AI-generated fictional character"
    assert any(m["file"].startswith("qwen_image") for m in origin["models"])
    assert client.get(f"/api/cast/{cast['id']}/refs/ref_1.png").status_code == 200
    assert [c["id"] for c in client.get("/api/cast").json()] == [cast["id"]]

    # a generated character works as a reference for a Direct take, like any other cast
    shot = start_direct(client, rig={"movement": "static"}, cast_id=cast["id"])
    done = wait_for(client, shot["id"])
    assert done["status"] == "succeeded", done["error"]
    receipt = client.get(f"/api/takes/{shot['id']}/receipt").json()["receipt"]
    assert receipt["inputs"]["cast"]["name"] == "Courier" and len(receipt["inputs"]["cast"]["refs"]) == 1


def test_generating_and_keeping_a_character_rejects_bad_input(client):
    assert client.post("/api/cast/generate", json={"description": "ab"}).status_code == 422
    assert client.post("/api/cast/generate", json={"description": "a calm sailor", "count": 9}).status_code == 422
    refused = client.post("/api/cast/generate", json={"description": "a nude figure study"})
    assert refused.status_code == 422 and "safe-for-work" in refused.json()["error"]["message"]

    take = start_direct(client, rig={"movement": "static"})
    wait_for(client, take["id"])
    not_a_portrait = client.post("/api/cast/from-take", json={"take_id": take["id"], "candidate": 1, "name": "X"})
    assert not_a_portrait.status_code == 422
    unknown = client.post("/api/cast/from-take",
                          json={"take_id": "tk_20260101_000000_ffff", "candidate": 1, "name": "X"})
    assert unknown.status_code == 404

    made = client.post("/api/cast/generate", json={"description": "a calm sailor", "count": 1}).json()
    wait_for(client, made["id"])
    missing = client.post("/api/cast/from-take", json={"take_id": made["id"], "candidate": 3, "name": "Sailor"})
    assert missing.status_code == 404
    assert client.get("/api/cast").json() == []


def test_unsafe_direct_and_plan_requests_get_a_plain_422(client):
    body = {"subject": "two people having sex", "rig": {"movement": "static"}}
    for path in ("/api/direct/plan", "/api/takes/direct"):
        response = client.post(path, json=body)
        assert response.status_code == 422 and "safe-for-work" in response.json()["error"]["message"], path


def test_importing_a_receipt_restores_the_recipe(client, tmp_path):
    take = start_direct(client, rig={"movement": "static"}, seed=11)
    done = wait_for(client, take["id"])
    base = f"/api/takes/{done['id']}"
    video = client.get(f"{base}/media/take.mp4").content
    imported = client.post("/api/receipts/import", files={"file": ("take.mp4", video, "video/mp4")})
    assert imported.status_code == 200
    body = imported.json()
    assert body["verified"] is True and body["recipe"]["inputs"]["seed"] == 11 and body["recipe_link"]
    stripped = client.post("/api/receipts/import", files={"file": ("clip.mp4", clip_bytes(tmp_path), "video/mp4")})
    assert stripped.status_code == 422 and "strip" in stripped.json()["error"]["message"]
    assert client.post("/api/receipts/import", files={"file": ("a.exe", b"x", "x/y")}).status_code == 422


def test_delete_and_cancel(client, fake_api):
    fake_api.delay = 0.4
    take = start_direct(client, rig={"movement": "static"})
    cancelled = client.post(f"/api/takes/{take['id']}/cancel").json()
    assert cancelled["status"] == "canceled"
    assert client.delete(f"/api/takes/{take['id']}").status_code == 204
    assert client.get(f"/api/takes/{take['id']}").status_code == 404


def test_hostile_host_headers_are_rejected(client):
    assert client.get("/api/status", headers={"Host": "evil.example"}).status_code == 400
