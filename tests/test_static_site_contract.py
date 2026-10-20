"""The hosted Replay end to end: a take rendered through the pipeline, exported, served over HTTP and
driven by the real JavaScript client in Node. Python and JS were written apart; this proves they agree."""
from __future__ import annotations

import functools
import http.server
import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from openfield.static_export import export_static

from .test_api import start_direct, wait_for

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")

API_STATIC = Path(__file__).resolve().parents[1] / "openfield" / "web" / "js" / "lib" / "api-static.js"

SCRIPT = """
import { createStaticApi } from %(module)s;

const api = await createStaticApi({ base: process.env.SITE_URL, playbackSeconds: 0.5 });
if (!api) throw new Error("the site was not recognised as a static export");
const recorded = await api.recorded();
const take = await api.recreate(recorded[0].id);
const types = [];
const status = await new Promise((resolve) => api.follow(take.id, { onEvent: (e) => types.push(e.type), onEnd: resolve }));
const done = await api.take(take.id);
const code = async (url) => {
  const res = await fetch(url);
  await res.arrayBuffer(); // always drain the body: an unread one trips a Node fetch assertion on close
  return res.status;
};
const view = await api.receipt(done);
console.log(JSON.stringify({
  kind: api.kind, status, types, recorded: recorded.length, takes: (await api.takes()).length,
  outputs: done.outputs.length, anchors: done.anchors.length, replayOf: done.replay_of,
  video: await code(api.media(done, "take.mp4")), poster: await code(api.media(done, "poster.png")),
  zip: await code(api.workflowsUrl(done)), snippet: await code(api.snippetUrl(done)),
  verified: view.verified, recipeLink: Boolean(view.recipe_link),
  locked: (await api.status()).backend.locked,
}));
"""


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep test output clean
        pass


@pytest.fixture
def site_url(client, tmp_path):
    take = start_direct(client, rig={"movement": "static"}, seed=31)
    assert wait_for(client, take["id"])["status"] == "succeeded"
    settings = client.app.state.openfield.settings
    site = tmp_path / "site"
    export_static(settings, site, takes_root=settings.takes_dir, web_dir=settings.web_dir)
    handler = functools.partial(QuietHandler, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()
    server.server_close()


def test_the_real_js_client_replays_an_exported_take(site_url):
    script = SCRIPT % {"module": json.dumps(API_STATIC.as_uri())}
    done = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=120,
        env={**__import__("os").environ, "SITE_URL": site_url}, check=False)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert result["kind"] == "static" and result["locked"] is True
    assert result["status"] == "succeeded" and result["recorded"] == 1 and result["takes"] == 2
    assert result["types"][0] == "take" and result["types"][-1] == "end" and "stage" in result["types"]
    assert result["outputs"] >= 2 and result["anchors"] == 0
    assert result["replayOf"].startswith("tk_")
    assert (result["video"], result["poster"], result["zip"], result["snippet"]) == (200, 200, 200, 200)
    assert result["verified"] is True and result["recipeLink"] is True
