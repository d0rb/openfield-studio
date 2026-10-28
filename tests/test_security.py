"""The local server must not be drivable by a web page on another origin, and must not hoard or choke on uploads."""
from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from openfield.security import MAX_BODY_BYTES, SameOriginOnly, foreign_origin

from .test_api import clip_bytes, png_bytes, start_direct, wait_for

EVIL = {"Origin": "https://evil.example"}


# -- the decision ---------------------------------------------------------------------------------

@pytest.mark.parametrize("headers, refused", [
    ({}, False),  # curl, scripts, the CLI: not a browser, nothing to compare
    ({"host": "127.0.0.1:8877", "origin": "http://127.0.0.1:8877"}, False),
    ({"host": "localhost:8877", "origin": "http://LOCALHOST:8877"}, False),
    ({"host": "127.0.0.1:8877", "origin": "https://evil.example"}, True),
    ({"host": "127.0.0.1:8877", "origin": "http://127.0.0.1:3000"}, True),   # another app on this machine
    ({"host": "127.0.0.1:8877", "origin": "null"}, True),                      # sandboxed frame, file:// page
    ({"host": "127.0.0.1:8877", "origin": "http://127.0.0.1:8877.evil.example"}, True),
    ({"sec-fetch-site": "same-origin"}, False),
    ({"sec-fetch-site": "none"}, False),
    ({"sec-fetch-site": "cross-site"}, True),
    ({"sec-fetch-site": "same-site"}, True),                                   # same machine, different port
    ({"sec-fetch-site": "same-origin", "origin": "https://evil.example"}, False),  # the browser's word wins
    ({"host": "127.0.0.1:8877"}, False),
])
def test_foreign_origin_decisions(headers, refused):
    assert (foreign_origin(headers) is not None) is refused


def test_a_configured_origin_is_allowed_for_reverse_proxies():
    allowed = frozenset({"https://studio.example.org"})
    assert foreign_origin({"host": "127.0.0.1:8877", "origin": "https://studio.example.org"}, allowed) is None
    assert foreign_origin({"host": "127.0.0.1:8877", "origin": "https://studio.example.org/"}, allowed) is None
    assert foreign_origin({"host": "127.0.0.1:8877", "origin": "https://other.example.org"}, allowed)


# -- the middleware, on its own ---------------------------------------------------------------------

async def run_middleware(method, headers, allowed=()):
    reached: list[str] = []
    sent: list[dict] = []

    async def app(scope, receive, send):
        reached.append(scope["method"])

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": method, "path": "/api/x",
             "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}
    await SameOriginOnly(app, allowed)(scope, receive, send)
    status = next((m["status"] for m in sent if m["type"] == "http.response.start"), None)
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return reached, status, (json.loads(body) if body else None)


async def test_the_middleware_only_gates_state_changing_requests():
    for method in ("GET", "HEAD", "OPTIONS"):
        reached, status, _ = await run_middleware(method, {"origin": "https://evil.example", "host": "x"})
        assert reached == [method] and status is None, method
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        reached, status, body = await run_middleware(method, {"origin": "https://evil.example", "host": "x"})
        assert reached == [] and status == 403 and body["error"]["code"] == "cross_origin", method
    reached, status, _ = await run_middleware("POST", {"origin": "http://x", "host": "x"})
    assert reached == ["POST"] and status is None


async def test_a_huge_declared_body_is_refused_unread():
    reached, status, body = await run_middleware("POST", {"content-length": str(MAX_BODY_BYTES + 1)})
    assert reached == [] and status == 413 and body["error"]["code"] == "too_large"
    reached, status, _ = await run_middleware("POST", {"content-length": str(MAX_BODY_BYTES)})
    assert reached == ["POST"] and status is None
    reached, status, _ = await run_middleware("POST", {"content-length": "not-a-number"})
    assert reached == ["POST"]


# -- the real app ---------------------------------------------------------------------------------

def uploads(client):
    folder = client.app.state.openfield.settings.uploads_dir
    return sorted(folder.glob("*")) if folder.exists() else []


def test_a_page_on_another_origin_cannot_start_a_render_or_change_anything(client, tmp_path):
    files = {"source": ("a.mp4", clip_bytes(tmp_path), "video/mp4"), "reference": ("r.png", png_bytes(), "image/png")}
    refused = client.post("/api/takes/reshoot", data={"prompt": "a courier in a raincoat"}, files=files, headers=EVIL)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "cross_origin"
    assert client.get("/api/takes").json() == [] and uploads(client) == [], "nothing was started or saved"

    body = json.dumps({"subject": "A lighthouse at dusk", "rig": {"movement": "static"}})
    for headers in ({"Content-Type": "text/plain"}, {"Content-Type": "application/json"}):
        r = client.post("/api/takes/direct", content=body, headers={**EVIL, **headers})
        assert r.status_code == 403, headers  # even where an older FastAPI would parse text/plain as JSON
    assert client.post("/api/models/face", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/api/backend", json={"mode": "replay"}, headers={"Sec-Fetch-Site": "same-site"}).status_code == 403
    for path, body in (("/api/backend/test", {"base_url": "http://127.0.0.1:9"}),
                       ("/api/backend/connect", {"base_url": "http://127.0.0.1:9"}), ("/api/backend/forget", {})):
        assert client.post(path, json=body, headers={"Sec-Fetch-Site": "same-site"}).status_code == 403, path
    assert client.post("/api/cast", data={"name": "X", "kind": "character", "consent": "mine"},
                       files=[("files", ("x.png", png_bytes(), "image/png"))], headers=EVIL).status_code == 403
    assert client.delete("/api/cast/ca_12345678", headers=EVIL).status_code == 403
    assert client.get("/api/status").json()["backend"]["kind"] == "pod", "and the app itself is untouched"


def test_reads_and_our_own_pages_still_work(client):
    assert client.get("/api/status", headers=EVIL).status_code == 200, "reads are not gated: pages cannot read them anyway"
    assert client.get("/api/moves", headers=EVIL).status_code == 200
    ours = {"Origin": "http://testserver"}
    r = client.post("/api/direct/plan", json={"subject": "A lighthouse", "rig": {"movement": "static"}}, headers=ours)
    assert r.status_code == 200
    same = client.post("/api/direct/plan", json={"subject": "A lighthouse", "rig": {"movement": "static"}},
                       headers={"Sec-Fetch-Site": "same-origin", "Origin": "http://testserver"})
    assert same.status_code == 200


def test_an_origin_can_be_allowed_for_a_reverse_proxy(client, monkeypatch):
    from openfield.app import create_app

    settings = client.app.state.openfield.settings
    monkeypatch.setenv("OPENFIELD_ALLOWED_ORIGINS", "https://studio.example.org")
    from fastapi.testclient import TestClient

    with TestClient(create_app(settings)) as proxied:
        body = {"subject": "A lighthouse", "rig": {"movement": "static"}}
        assert proxied.post("/api/direct/plan", json=body,
                            headers={"Origin": "https://studio.example.org"}).status_code == 200
        assert proxied.post("/api/direct/plan", json=body, headers=EVIL).status_code == 403


# -- uploads ---------------------------------------------------------------------------------------

def test_a_refused_re_shoot_leaves_no_footage_behind(client, tmp_path):
    files = {"source": ("a.mp4", clip_bytes(tmp_path), "video/mp4"), "reference": ("r.png", png_bytes(), "image/png")}
    for data in ({"prompt": "   "}, {"prompt": "a nude dancer"}, {"prompt": "x"}):
        r = client.post("/api/takes/reshoot", data=data, files=files)
        assert r.status_code == 422, (data, r.text)
        assert uploads(client) == [], data
    bad_suffix = {"source": ("a.exe", b"MZ", "application/octet-stream"), "reference": ("r.png", png_bytes(), "image/png")}
    assert client.post("/api/takes/reshoot", data={"prompt": "a courier"}, files=bad_suffix).status_code == 422
    assert client.post("/api/takes/reshoot", data={"prompt": "a courier", "cast_id": "ca_00000000"},
                       files={"source": ("a.mp4", clip_bytes(tmp_path), "video/mp4")}).status_code == 422
    assert uploads(client) == []


def test_an_accepted_re_shoot_deletes_the_upload_once_the_take_is_over(client, tmp_path):
    files = {"source": ("a.mp4", clip_bytes(tmp_path), "video/mp4"), "reference": ("r.png", png_bytes(), "image/png")}
    started = client.post("/api/takes/reshoot", data={"prompt": "a courier in a raincoat"}, files=files)
    assert started.status_code == 202
    done = wait_for(client, started.json()["id"])
    assert done["status"] == "succeeded"
    assert uploads(client) == [], "the footage lives in the take, not in a forgotten uploads folder"


def test_leftover_uploads_from_a_crashed_run_are_cleared_at_start(tmp_path):
    import os
    import time

    from openfield.app import clear_stale_uploads

    folder = tmp_path / "uploads"
    folder.mkdir()
    old, fresh = folder / "old.mp4", folder / "fresh.mp4"
    old.write_bytes(b"x")
    fresh.write_bytes(b"x")
    two_days_ago = time.time() - 48 * 3600
    os.utime(old, (two_days_ago, two_days_ago))
    assert clear_stale_uploads(folder) == 1
    assert not old.exists() and fresh.exists()
    assert clear_stale_uploads(tmp_path / "missing") == 0


def png_of(size, mode="1"):
    buffer = io.BytesIO()
    Image.new(mode, size).save(buffer, "PNG")
    return buffer.getvalue()


def test_cast_uploads_are_bounded_before_they_are_trusted(client):
    def create(files):
        return client.post("/api/cast", data={"name": "Mara", "kind": "character", "consent": "fictional"}, files=files)

    too_many = [("files", (f"{i}.png", png_bytes(), "image/png")) for i in range(9)]
    assert create(too_many).status_code == 422
    big = [("files", ("big.png", b"\x89PNG" + b"0" * (13 * 1024 * 1024), "image/png"))]
    r = create(big)
    assert r.status_code == 422 and "12 MB" in r.json()["error"]["message"]
    # a tiny file that claims a gigantic canvas must not take the server down (the second one trips Pillow's own guard)
    for size in ((10000, 10000), (15000, 15000)):
        r = create([("files", ("canvas.png", png_of(size), "image/png"))])
        assert r.status_code == 422, size
        assert "pixels" in r.json()["error"]["message"] or "megapixels" in r.json()["error"]["message"]
    assert client.get("/api/cast").json() == []
    ok = create([("files", ("ok.png", png_bytes(), "image/png"))])
    assert ok.status_code == 201


def test_importing_an_odd_receipt_is_a_clean_422_or_200_never_a_500(client):
    for payload in ({"take": "x"}, {"take": 3, "inputs": []}, {"take": {"label": ["not", "text"]}}, {}, []):
        r = client.post("/api/receipts/import", files={"file": ("receipt.json", json.dumps(payload).encode(), "application/json")})
        assert r.status_code in {200, 422}, (payload, r.status_code, r.text[:200])
        if r.status_code == 200:
            assert r.json()["verified"] is False
            assert r.json()["label"] is None or isinstance(r.json()["label"], str)


def test_a_real_take_still_imports_after_the_hardening(client):
    take = start_direct(client, rig={"movement": "static"})
    wait_for(client, take["id"])
    receipt = client.get(f"/api/takes/{take['id']}/receipt").json()["receipt"]
    r = client.post("/api/receipts/import", files={"file": ("receipt.json", json.dumps(receipt).encode(), "application/json")})
    assert r.status_code == 200 and r.json()["verified"] is True and r.json()["recipe"]["kind"] == "direct"
    assert r.json()["label"] == receipt["take"]["label"]
