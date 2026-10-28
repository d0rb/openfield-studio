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
    assert status["hero_take"] is None  # no hero.json in the test showcase
    assert status["hero_reel"] == []
    assert "OpenField" in client.get("/").text
    assert client.get("/dashboard", follow_redirects=False).status_code in {301, 302, 307}


def test_the_live_app_answers_the_hosted_replay_probe_quietly(client):
    answer = client.get("/static/manifest.json")
    assert answer.status_code == 200 and answer.json() == {"static": False}


def test_move_catalog_has_all_49_moves(client):
    data = client.get("/api/moves").json()
    assert len(data["moves"]) == 49 and len(data["groups"]) == 7
    assert all(m["path"] for m in data["moves"])


def test_plan_compiles_and_rejects_bad_rigs(client):
    ok = client.post("/api/direct/plan", json={"subject": "A bottle", "rig": {"movement": "orbit_360"}})
    assert ok.status_code == 200
    body = ok.json()
    assert len(body["plan"]["segments"]) == 1 and len(body["plan"]["segments"][0]["mids"]) == 3 and body["templates"]["ltx25_flf2v"] == "ready"  # one pass, three guided stills
    bad = client.post("/api/direct/plan", json={"subject": "A bottle", "rig": {"movement": "teleport"}})
    assert bad.status_code == 422 and "unsupported movement" in bad.json()["error"]["message"]
    typo = client.post("/api/direct/plan", json={"subject": "A bottle", "rig": {"zoom": 3}})
    assert typo.status_code == 422
    short = client.post("/api/direct/plan", json={"subject": "hi"})
    assert short.status_code == 422
    rainy = client.post("/api/direct/plan", json={"subject": "A bottle", "rig": {"movement": "static", "effect": "rain"}})
    assert rainy.status_code == 200 and "Heavy rain falls" in rainy.json()["plan"]["prompt"]
    snow = client.post("/api/direct/plan", json={"subject": "A bottle", "rig": {"movement": "static", "effect": "snow"}})
    assert snow.status_code == 422 and "unsupported effect" in snow.json()["error"]["message"]


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
    assert made.json()["replay"] is True, "a replay says so from its first snapshot, so the screen never shows Rendering"
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


def test_a_bundled_take_is_served_read_only(client, tmp_path):
    from .test_static_export import record

    take_id = "tk_20261020_150433_966e"
    folder = record(tmp_path / "showcase" / "takes", take_id, created="2026-10-20T15:04:33Z")
    take = client.get(f"/api/takes/{take_id}")
    assert take.status_code == 200 and take.json()["id"] == take_id
    assert client.get(f"/api/takes/{take_id}/receipt").status_code == 200
    media = client.get(f"/api/takes/{take_id}/media/take.mp4")
    assert media.status_code == 200 and media.content == b"mp4-bytes"
    assert client.get(f"/api/takes/{take_id}/workflows.zip").status_code == 200
    assert client.get("/api/status").json()["recorded_takes"] == 1
    client.delete(f"/api/takes/{take_id}")
    assert (folder / "take.json").is_file(), "a bundled take is never deleted through the API"
    assert client.get("/api/takes/tk_20261020_150433_966f").status_code in (400, 404)



# -- the Connect panel: test a target, switch to it, remember its address, forget it -------------------------------
def test_connect_panel_tests_without_switching_then_connects_and_remembers(client, fake_api, tmp_path):
    assert client.post("/api/backend", json={"mode": "replay"}).json()["backend"]["locked"] is True
    probe = client.post("/api/backend/test", json={"base_url": fake_api.base_url}).json()
    assert probe["health"]["ok"] is True and probe["target"]["kind"] == "pod" and probe["preflight"] is None
    assert probe["warnings"] == [] and probe["target"]["host"] == f"127.0.0.1:{fake_api.port}"
    assert client.get("/api/status").json()["backend"]["locked"] is True, "a test never switches"

    fake_api.token = "secret"  # the box was started with --token
    needs = client.post("/api/backend/test", json={"base_url": fake_api.base_url}).json()["health"]
    assert needs["ok"] is False and needs["code"] == "missing_api_key" and "token" in needs["detail"]
    refused = client.post("/api/backend/connect", json={"base_url": fake_api.base_url, "api_key": "wrong"})
    assert refused.status_code == 401 and refused.json()["error"]["code"] == "unauthorized"
    assert "wrong" not in refused.text, "a rejected key is never echoed"
    assert client.get("/api/status").json()["backend"]["locked"] is True, "a refused connect leaves Replay in place"

    connected = client.post("/api/backend/connect", json={
        "base_url": fake_api.base_url, "api_key": "secret", "comfy_url": fake_api.base_url, "remember": True})
    assert connected.status_code == 200, connected.text
    b = connected.json()["backend"]
    assert b["kind"] == "pod" and b["locked"] is False and b["health"]["ok"] is True
    assert b["source"] == "saved" and b["configured"] is True and b["comfy_url"] is True
    assert b["target"] == {"kind": "pod", "label": "GPU box", "host": f"127.0.0.1:{fake_api.port}",
                           "url": fake_api.base_url, "comfy_url": fake_api.base_url}
    saved = json.loads((tmp_path / "data" / "connection.json").read_text(encoding="utf-8"))
    assert saved["base_url"] == fake_api.base_url and saved["comfy_url"] == fake_api.base_url
    assert "secret" not in json.dumps(saved) and "api_key" not in saved, "the address is remembered, never the key"
    assert "secret" not in connected.text

    take = start_direct(client)  # new takes render through the connected target, with its token
    assert wait_for(client, take["id"])["status"] == "succeeded"

    fake_api.token = None
    # back to Replay is still one switch away, and forgetting returns to the environment's target
    assert client.post("/api/backend", json={"mode": "replay"}).json()["backend"]["locked"] is True
    forgotten = client.post("/api/backend/forget").json()["backend"]
    assert forgotten["source"] == "env" and forgotten["kind"] == "pod"
    assert not (tmp_path / "data" / "connection.json").exists()


def test_a_remembered_address_is_used_again_and_can_be_forgotten(tmp_path, fake_api, monkeypatch):
    from fastapi.testclient import TestClient

    from openfield.app import create_app
    from openfield.config import Settings

    from .conftest import WORKFLOWS

    monkeypatch.delenv("COMFY_BASE_URL", raising=False)
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>OpenField</title>")
    settings = Settings(host="127.0.0.1", port=0, data_dir=tmp_path / "data", backend="auto", comfy_base_url=None,
                        has_api_key=False, workflow_dir=WORKFLOWS, showcase_dir=tmp_path / "showcase", web_dir=web)
    with TestClient(create_app(settings)) as first:
        assert first.get("/api/status").json()["backend"]["locked"] is True, "nothing configured: Replay"
        assert first.post("/api/backend", json={"mode": "sdk"}).status_code == 422
        assert first.post("/api/backend/connect", json={"base_url": fake_api.base_url}).status_code == 200
    with TestClient(create_app(settings)) as second:
        b = second.get("/api/status").json()["backend"]
        assert b["source"] == "saved" and b["kind"] == "pod" and b["locked"] is False
        gone = second.post("/api/backend/forget").json()["backend"]
        assert gone["locked"] is True and gone["source"] is None and gone["configured"] is False
    with TestClient(create_app(settings)) as third:
        assert third.get("/api/status").json()["backend"]["locked"] is True


def test_connect_panel_names_a_plain_comfyui_and_refuses_bad_addresses(client, fake_api):
    fake_api.plain_comfy = True
    health = client.post("/api/backend/test", json={"base_url": fake_api.base_url}).json()["health"]
    assert health["ok"] is False and health["code"] == "not_a_proxy" and "comfy-api-proxy" in health["detail"]
    refused = client.post("/api/backend/connect", json={"base_url": fake_api.base_url})
    assert refused.status_code == 502 and refused.json()["error"]["code"] == "not_a_proxy"
    fake_api.plain_comfy = False

    for bad in ("ftp://box:8189", "http://", "http://user:pw@box:8189", "http://box:8189/?x=1"):
        r = client.post("/api/backend/test", json={"base_url": bad})
        assert r.status_code == 422, bad
        assert "user:pw" not in r.text
    assert client.post("/api/backend/test", json={"base_url": fake_api.base_url, "api_key": "has space"}).status_code == 422
    down = client.post("/api/backend/test", json={"base_url": "http://127.0.0.1:9"}).json()["health"]
    assert down["ok"] is False and down["code"] == "unreachable"
    public = client.post("/api/backend/test", json={"base_url": "http://203.0.113.9:8189"}).json()
    assert any("token" in w for w in public["warnings"]), "an open address without a token is called out"


def test_connect_panel_checks_model_files_and_nodes_on_the_box(client, fake_api):
    ready = client.post("/api/backend/test", json={"base_url": fake_api.base_url, "comfy_url": fake_api.base_url}).json()
    pre = ready["preflight"]
    assert pre["ok"] is True and pre["summary"] == "6 of 6 workflows ready" and pre["missing_files"] == []
    assert pre["comfyui"] == {"version": "0.41.0", "device": "Fake GPU 32GB", "vram_total_gb": 34.4, "vram_free_gb": 31.0}
    assert [w["name"] for w in pre["workflows"]] == ["qwen21_t2i", "qwen21_edit", "ltx25_i2v", "ltx25_flf2v", "wan_animate2", "esrgan_upscale"]

    fake_api.missing_models = {"ltx-2.5-audio-vae-bf16.safetensors"}
    partial = client.post("/api/backend/test", json={"base_url": fake_api.base_url, "comfy_url": fake_api.base_url}).json()["preflight"]
    assert partial["ok"] is False and partial["missing_files"] == ["ltx-2.5-audio-vae-bf16.safetensors"]
    rows = {w["name"]: w for w in partial["workflows"]}
    assert rows["ltx25_i2v"]["state"] == "missing" and rows["ltx25_flf2v"]["state"] == "missing"
    assert rows["qwen21_t2i"]["state"] == "ready" and rows["wan_animate2"]["state"] == "ready"
    gap = rows["ltx25_i2v"]["missing"][0]
    assert gap["file"] == "ltx-2.5-audio-vae-bf16.safetensors" and gap["directory"] == "vae"
    assert gap["repo"] == "Lightricks/LTX-2.5" and gap["hint"] == "FETCH_ONLY=ltx bash /workspace/pod_setup.sh fetch"
    assert "1 model file(s) missing" in partial["summary"]

    unreachable = client.post("/api/backend/test", json={"base_url": fake_api.base_url, "comfy_url": "http://127.0.0.1:9"}).json()["preflight"]
    assert unreachable["state"] == "unreachable" and unreachable["ok"] is False and unreachable["workflows"] == []


# -- start from your own image, over multipart ----------------------------------------------------------------------
def uploads_left(client):
    folder = client.app.state.openfield.settings.uploads_dir
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def test_a_direct_take_can_start_from_an_uploaded_still(client, fake_api):
    body = {"subject": "Me on a pier at dusk", "rig": {"movement": "dolly_in"}, "seed": 3, "auto_approve": True}
    started = client.post("/api/takes/direct/from-image", data={"request": json.dumps(body)},
                          files={"source": ("me.png", png_bytes(size=(800, 500)), "image/png")})
    assert started.status_code == 202, started.text
    take = wait_for(client, started.json()["id"])
    assert take["status"] == "succeeded" and len(take["recipe"]["source_sha256"]) == 64
    assert client.get(f"/api/takes/{take['id']}/media/inputs/hero.png").status_code == 200
    view = client.get(f"/api/takes/{take['id']}/receipt").json()
    sealed = view.get("receipt", view)
    assert sealed["inputs"]["source"]["original_size"] == [800, 500] and view["verified"] is True
    assert client.get("/api/moves").json()["from_image_tested"] is True, "checked by eye on the Oct 22 render (from-image-mara); the label follows the flag"
    assert client.get("/api/moves").json()["face_only_tested"] is True, "the close-up face-only re-shoot of Oct 23 holds; the pill follows the flag"

    assert client.post("/api/takes/direct/from-image", data={"request": "{not json"},
                       files={"source": ("me.png", png_bytes(), "image/png")}).status_code == 422
    assert client.post("/api/takes/direct/from-image", data={"request": json.dumps(body)},
                       files={"source": ("me.txt", b"hello", "text/plain")}).status_code == 422
    assert client.post("/api/takes/direct/from-image", data={"request": json.dumps({"subject": "x"})},
                       files={"source": ("me.png", png_bytes(), "image/png")}).status_code == 422, "validated like the JSON route"
    huge = client.post("/api/takes/direct/from-image", data={"request": json.dumps(body)},
                       files={"source": ("big.png", b"0" * (21 << 20), "image/png")})
    assert huge.status_code == 413
    assert uploads_left(client) == [], "a refused or finished request leaves no upload behind"


# -- quality tiers and the measured estimate -------------------------------------------------------------------------
def test_quality_is_a_request_field_and_the_estimate_is_measured_or_null(client, fake_api):
    catalog = client.get("/api/moves").json()
    assert [t["id"] for t in catalog["quality"]] == ["draft", "standard", "fine"] and catalog["quality_tested"] == ["draft", "fine", "standard"]
    assert client.post("/api/takes/direct", json={"subject": "A lighthouse at dusk", "rig": {"movement": "dolly_in"}, "quality": "ultra"}).status_code == 422
    empty = client.get("/api/direct/estimate", params={"quality": "draft", "movement": "dolly_in", "duration_seconds": 5}).json()
    assert empty["seconds"] is None and empty["samples"] == 0 and empty["backend"] == "GPU box"

    take = start_direct(client, quality="draft")
    assert wait_for(client, take["id"])["recipe"]["quality"] == "draft"
    measured = client.get("/api/direct/estimate", params={"quality": "draft", "movement": "dolly_in", "duration_seconds": 5}).json()
    assert measured["samples"] == 1 and measured["seconds"] is not None
    assert client.get("/api/direct/estimate", params={"quality": "standard", "movement": "dolly_in", "duration_seconds": 5}).json()["samples"] == 0
    assert client.get("/api/direct/estimate", params={"quality": "draft", "movement": "no_such", "duration_seconds": 5}).status_code == 422

    client.post("/api/backend", json={"mode": "replay"})
    replay = client.get("/api/direct/estimate", params={"quality": "draft", "movement": "dolly_in", "duration_seconds": 5}).json()
    assert replay["seconds"] is None and "renders nothing" in replay["basis"]
    client.post("/api/backend", json={"mode": "sdk"})


def test_the_estimate_route_knows_a_shot_from_an_image(client, fake_api):
    params = {"quality": "standard", "movement": "dolly_in", "duration_seconds": 5, "source": "true"}
    assert client.get("/api/direct/estimate", params=params).json()["samples"] == 0
    started = client.post("/api/takes/direct/from-image", data={"request": json.dumps({"subject": "Me on a pier", "rig": {"movement": "dolly_in"}, "seed": 3, "auto_approve": True})},
                          files={"source": ("me.png", png_bytes(size=(640, 400)), "image/png")})
    assert wait_for(client, started.json()["id"])["status"] == "succeeded"
    assert client.get("/api/direct/estimate", params=params).json()["samples"] == 1
    assert client.get("/api/direct/estimate", params={**params, "source": "false"}).json()["samples"] == 0


def test_the_interface_files_are_always_revalidated_so_old_modules_never_mix_with_new_ones(client):
    web = client.app.state.openfield.settings.web_dir
    (web / "js").mkdir(exist_ok=True)
    (web / "js" / "main.js").write_text("export {};\n", encoding="utf-8")
    assert client.get("/").headers.get("cache-control") == "no-cache"
    first = client.get("/js/main.js")
    assert first.status_code == 200 and first.headers.get("cache-control") == "no-cache" and first.headers.get("etag")
    assert client.get("/js/main.js", headers={"If-None-Match": first.headers["etag"]}).status_code == 304, "cached, but checked"
    assert "no-cache" not in client.get("/api/status").headers.get("cache-control", ""), "the API is untouched"


def test_the_plan_and_the_estimate_know_an_angle_and_a_transformation(client, fake_api):
    catalog = client.get("/api/moves").json()
    assert catalog["angles"]["default"] == "front/eye/medium" and len(catalog["angles"]["azimuths"]) == 8
    assert {e["id"]: e["kind"] for e in catalog["effects"]}["gold"] == "keyframed" and "grade" in catalog["options"]
    plan = client.post("/api/direct/plan", json={"subject": "A bottle", "rig": {"movement": "static", "angle": "back/high/wide", "effect": "ignite"}}).json()
    assert plan["plan"]["angle"]["label"] == "Back · High angle · Wide" and plan["plan"]["transformation"] == "ignite"
    assert [a["role"] for a in plan["plan"]["anchors"]] == ["hero", "transform"]
    bad = client.post("/api/direct/plan", json={"subject": "A bottle", "rig": {"movement": "static", "angle": "nowhere"}})
    assert bad.status_code == 422 and "unsupported angle" in bad.json()["error"]["message"]
    params = {"quality": "standard", "movement": "static", "duration_seconds": 5, "angle": "back/high/wide", "effect": "ignite"}
    assert client.get("/api/direct/estimate", params=params).json()["samples"] == 0
    assert client.get("/api/direct/estimate", params={**params, "angle": "nowhere"}).status_code == 422


def test_a_plan_with_a_spoken_line_quotes_it_and_says_whether_a_render_checked_it(client):
    spoken = client.post("/api/direct/plan", json={"subject": "Mara at the pier", "rig": {"movement": "static"},
                                                    "line": "We leave at first light.", "delivery": "calm", "language": "English"})
    assert spoken.status_code == 200, spoken.text
    plan = spoken.json()["plan"] if "plan" in spoken.json() else spoken.json()
    assert '"We leave at first light."' in plan["prompt"] and "in English, in a calm, low voice" in plan["prompt"]
    assert plan["dialogue"]["delivery"] == "calm" and plan["dialogue"]["tested"] is True, "three spoken lines checked on Oct 22"
    silent = client.post("/api/direct/plan", json={"subject": "Mara at the pier", "rig": {"movement": "static"}})
    assert silent.json().get("plan", silent.json())["dialogue"] is None
    long = client.post("/api/direct/plan", json={"subject": "Mara at the pier", "line": "x" * 201})
    assert long.status_code == 422
    sung = client.post("/api/direct/plan", json={"subject": "Mara at the pier", "line": "hi", "delivery": "sing"})
    assert sung.status_code in (400, 422), sung.text
    assert client.get("/api/moves").json()["dialogue"]["tested"] is True


def test_an_action_reaches_the_shot_prompt_but_not_the_still_and_a_bad_one_gets_a_422(client):
    action = "He draws the katana in one swift motion"
    body = {"subject": "A samurai in a bamboo grove", "rig": {"movement": "static"}, "action": action}
    planned = client.post("/api/direct/plan", json=body)
    assert planned.status_code == 200, planned.text
    assert f"A samurai in a bamboo grove. {action}." in planned.json()["plan"]["prompt"]
    assert action not in planned.json()["still_prompt"] and planned.json()["plan"]["action"] == action
    take = start_direct(client, **body)  # 202
    done = wait_for(client, take["id"])
    assert done["status"] == "succeeded", done["error"]
    assert done["recipe"]["action"] == action
    assert client.post("/api/takes/direct", json=body | {"action": "x" * 400}).status_code == 422
    short = client.post("/api/takes/direct", json=body | {"action": "ab"})
    assert short.status_code == 422 and "3 to 300 characters" in short.json()["error"]["message"]
    assert client.get("/api/moves").json()["action_max"] == 300


def test_a_transition_between_two_takes_runs_through_the_api(client):
    first = wait_for(client, start_direct(client, rig={"movement": "static"})["id"])
    second = wait_for(client, start_direct(client, rig={"movement": "static"}, seed=6)["id"])
    response = client.post("/api/takes/transition", json={"first": first["id"], "second": second["id"], "style": "push"})
    assert response.status_code == 202, response.text
    done = wait_for(client, response.json()["id"])
    assert done["status"] == "succeeded" and done["kind"] == "transition"
    assert client.post("/api/takes/transition", json={"first": first["id"], "second": second["id"], "seconds": 9}).status_code == 422
    assert client.post("/api/takes/transition", json={"first": first["id"], "second": first["id"]}).status_code == 422
    styles = client.get("/api/moves").json()["transitions"]
    assert [s["id"] for s in styles["styles"]] == ["morph", "whip", "push", "match"] and styles["seconds"] == [2, 3, 4]
    assert {s["id"] for s in styles["styles"] if s["tested"]} == {"push"}, "the push bridge of Oct 23 (v1c-tr-rooftop-dragon-push) holds; the other styles do not yet"


def test_an_extend_continues_a_take_through_the_api(client):
    source = wait_for(client, start_direct(client, rig={"movement": "static"})["id"])
    response = client.post("/api/takes/extend", json={"take": source["id"], "seconds": 3})
    assert response.status_code == 202, response.text
    done = wait_for(client, response.json()["id"])
    assert done["status"] == "succeeded" and done["kind"] == "extend"
    assert client.post("/api/takes/extend", json={"take": source["id"], "seconds": 9}).status_code == 422
    extend = client.get("/api/moves").json()["extend"]
    assert extend["seconds"] == [3, 5] and extend["tested"] is True, "two extensions held on Oct 23 (v5-extend-*)"


def test_a_shots_board_runs_through_the_api_from_a_take_or_an_upload(client, tmp_path):
    source = wait_for(client, start_direct(client, rig={"movement": "static"})["id"])
    response = client.post("/api/takes/shots", data={"request": json.dumps({"take": source["id"]})})
    assert response.status_code == 202, response.text
    done = wait_for(client, response.json()["id"])
    assert done["status"] == "succeeded" and done["kind"] == "shots" and len(done["shots"]) == 9
    image = tmp_path / "me.png"
    Image.new("RGB", (120, 80), "purple").save(image)
    with image.open("rb") as handle:
        uploaded = client.post("/api/takes/shots", data={"request": "{}"}, files={"source": ("me.png", handle, "image/png")})
    assert uploaded.status_code == 202, uploaded.text
    assert client.post("/api/takes/shots", data={"request": "{}"}).status_code == 422  # neither a take nor an image
    board = client.get("/api/moves").json()["shots"]
    assert len(board["board"]) == 9 and all(s["angle_tested"] for s in board["board"]) and board["tested"] is True


def test_an_edit_runs_through_the_api_and_a_swap_needs_a_cast(client):
    source = wait_for(client, start_direct(client, rig={"movement": "static"})["id"])
    ok = client.post("/api/takes/edit", data={"request": json.dumps({"preset": "remove", "detail": "the lantern", "take": source["id"]})})
    assert ok.status_code == 202, ok.text
    assert wait_for(client, ok.json()["id"])["status"] == "succeeded"
    assert client.post("/api/takes/edit", data={"request": json.dumps({"preset": "face_swap", "take": source["id"]})}).status_code == 422
    assert client.post("/api/takes/edit", data={"request": json.dumps({"preset": "melt", "take": source["id"]})}).status_code == 422
    edits = client.get("/api/moves").json()["edits"]
    assert len(edits["presets"]) == 6 and all(p["tested"] for p in edits["presets"]) and len(edits["lights"]) == 8


def test_an_upscale_runs_through_the_api_and_the_catalog_names_its_targets(client):
    source = wait_for(client, start_direct(client, rig={"movement": "static"})["id"])
    response = client.post("/api/takes/upscale", json={"take": source["id"], "target": "2k"})
    assert response.status_code == 202, response.text
    done = wait_for(client, response.json()["id"])
    assert done["status"] == "succeeded" and done["kind"] == "upscale"
    assert done["recipe"] == {"kind": "upscale", "take": source["id"], "target": "2k"}
    default = client.post("/api/takes/upscale", json={"take": source["id"]})
    assert default.status_code == 202 and default.json()["recipe"]["target"] == "4k", "4k unless the body says otherwise"
    assert wait_for(client, default.json()["id"])["status"] == "succeeded"

    before = len(client.get("/api/takes").json())
    unknown_target = client.post("/api/takes/upscale", json={"take": source["id"], "target": "8k"})
    assert unknown_target.status_code == 422 and "2k, 4k" in unknown_target.json()["error"]["message"]
    assert client.post("/api/takes/upscale", json={"take": "tk_20990101_000000_abcd"}).status_code == 422
    assert client.post("/api/takes/upscale", json={"take": "../../etc"}).status_code == 422
    assert client.post("/api/takes/upscale", json={"target": "2k"}).status_code == 422  # a take is required
    again = client.post("/api/takes/upscale", json={"take": done["id"], "target": "4k"})
    assert again.status_code == 422 and "already an upscale" in again.json()["error"]["message"]
    assert len(client.get("/api/takes").json()) == before, "a refused request makes no take"

    catalog = client.get("/api/moves").json()["upscale"]
    assert catalog["targets"] == [{"id": "2k", "label": "2K", "long_side": 2560}, {"id": "4k", "label": "4K", "long_side": 3840}]
    assert catalog["tested"] is True, "the Draft-to-2K upscale of Oct 23 (v6-upscale-draft-2k) holds by eye"


def test_previews_for_slow_links_a_small_still_and_a_strip_of_the_take(client):
    take = wait_for(client, start_direct(client)["id"])
    assert take["status"] == "succeeded", take["error"]
    full = client.get(f"/api/takes/{take['id']}/media/poster.png")
    assert full.headers["content-type"] == "image/png"
    small = client.get(f"/api/takes/{take['id']}/media/poster.png", params={"w": 64})
    assert small.status_code == 200 and small.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(small.content)) as im:
        assert max(im.size) <= 64
    strip = client.get(f"/api/takes/{take['id']}/strip.jpg", params={"frames": 6, "w": 120})
    assert strip.status_code == 200 and strip.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(strip.content)) as im:
        assert im.size[0] <= 3 * 120 and im.size[0] > im.size[1], "six frames, three to a row"
    video = client.get(f"/api/takes/{take['id']}/media/take.mp4", params={"w": 64})
    assert video.headers["content-type"] == "video/mp4", "w only shrinks images"
    assert client.get("/api/takes/tk_20990101_000000_dead/strip.jpg").status_code == 404


def test_approve_refuses_a_still_index_out_of_range(client):
    take = start_direct(client, auto_approve=False)
    waiting = wait_for(client, take["id"], {"awaiting_approval", *DONE})
    assert waiting["status"] == "awaiting_approval"
    assert client.post(f"/api/takes/{take['id']}/approve", json={"reroll": [-1]}).status_code == 422
    assert client.post(f"/api/takes/{take['id']}/approve", json={"reroll": [99]}).status_code == 422
    assert client.post(f"/api/takes/{take['id']}/approve", json={"reroll": []}).status_code == 200
