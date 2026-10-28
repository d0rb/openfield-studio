from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openfield.app import create_app
from openfield.config import Settings

from .fake_comfy_api import FakeComfyApi

WORKFLOWS = Path(__file__).resolve().parents[1] / "openfield" / "workflows"


@pytest.fixture(scope="session")
def _fake_server(tmp_path_factory):
    server = FakeComfyApi(tmp=tmp_path_factory.mktemp("fake_api"))
    server.start()
    yield server
    server.stop()


@pytest.fixture
def fake_api(_fake_server, monkeypatch):
    """The fake Comfy API, reset to a clean state and set as COMFY_BASE_URL for the test."""
    server = _fake_server
    server.token = None
    server.delay = 0.05
    server.previews = True
    server.proxy_quirks = True
    server.fail_with = None
    server.end_with = None
    server.reject_next_submit = None
    server.plain_comfy = False
    server.missing_models = set()
    server.uploads.clear()
    server.jobs.clear()
    monkeypatch.setenv("COMFY_BASE_URL", server.base_url)
    monkeypatch.delenv("COMFY_API_KEY", raising=False)
    return server


@pytest.fixture
def client(tmp_path, fake_api):
    """The whole app on mini templates, rendering through the fake Comfy API."""
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>OpenField</title>")
    settings = Settings(
        host="127.0.0.1", port=0, data_dir=tmp_path / "data", backend="sdk",
        comfy_base_url=fake_api.base_url, has_api_key=False, workflow_dir=WORKFLOWS,
        showcase_dir=tmp_path / "showcase", web_dir=web)
    with TestClient(create_app(settings)) as test_client:
        yield test_client
