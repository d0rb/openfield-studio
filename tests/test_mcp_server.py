"""The MCP server: the protocol itself, argument checks, and a whole take driven through it on the fake stack."""
from __future__ import annotations

import base64
import io
import json
import subprocess
import sys

import pytest
from PIL import Image

from openfield import mcp_server as mcp


def rpc(server, method, params=None, id_=1):
    message = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        message["params"] = params
    return server.handle(message)


def call(server, name, **args):
    reply = rpc(server, "tools/call", {"name": name, "arguments": args})
    assert "result" in reply, reply
    return reply["result"]


def texts(result):
    return [b["text"] for b in result["content"] if b["type"] == "text"]


def images(result):
    return [b for b in result["content"] if b["type"] == "image"]


def first_json(result):
    return json.loads(texts(result)[0])


@pytest.fixture
def offline():
    return mcp.Server(mcp.Studio("http://127.0.0.1:9"))  # nothing listens there


def test_initialize_negotiates_the_version_and_carries_instructions(offline):
    known = rpc(offline, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})["result"]
    assert known["protocolVersion"] == "2025-06-18"
    assert known["serverInfo"]["name"] == "openfield-studio"
    assert set(known["capabilities"]) == {"tools", "prompts", "resources"}
    assert "awaiting_approval" in known["instructions"] and "Replay" in known["instructions"]
    newer = rpc(offline, "initialize", {"protocolVersion": "2099-01-01"})["result"]
    assert newer["protocolVersion"] == mcp.PROTOCOL_VERSIONS[0]


def test_every_tool_is_listed_with_a_closed_object_schema(offline):
    tools = rpc(offline, "tools/list")["result"]["tools"]
    names = [t["name"] for t in tools]
    assert len(names) == len(set(names)) == len(mcp.TOOLS) >= 20
    for t in tools:
        schema = t["inputSchema"]
        assert t["description"] and t["title"]
        assert schema["type"] == "object" and schema["additionalProperties"] is False
        assert set(schema["required"]) <= set(schema["properties"])
        assert t["annotations"]["readOnlyHint"] in (True, False)
    by_name = {t["name"]: t for t in tools}
    assert by_name["studio_status"]["annotations"]["readOnlyHint"] is True
    assert by_name["direct_shot"]["annotations"]["openWorldHint"] is True  # it spends GPU time
    moves = by_name["direct_shot"]["inputSchema"]["properties"]["move"]["enum"]
    assert "dolly_in" in moves and "orbit_360" in moves


def test_protocol_errors_and_notifications(offline):
    assert rpc(offline, "ping")["result"] == {}
    assert rpc(offline, "no/such/method")["error"]["code"] == -32601
    assert offline.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert offline.handle({"id": 1, "method": "ping"})["error"]["code"] == -32600  # no jsonrpc member
    assert offline.handle({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": [1]})["error"]["code"] == -32602
    assert rpc(offline, "tools/call", {"name": "no_such_tool", "arguments": {}})["error"]["code"] == -32602


def test_prompts_and_resources(offline):
    names = [p["name"] for p in rpc(offline, "prompts/list")["result"]["prompts"]]
    assert {"make_a_movie", "direct_a_shot", "check_a_take"} <= set(names)
    movie = rpc(offline, "prompts/get", {"name": "make_a_movie", "arguments": {"idea": "a kite over dunes",
                                                                               "format": "vertical"}})["result"]
    body = movie["messages"][0]["content"]["text"]
    assert "a kite over dunes" in body and "orientation portrait" in body
    assert rpc(offline, "prompts/get", {"name": "make_a_movie", "arguments": {}})["error"]["code"] == -32602
    uris = {r["uri"] for r in rpc(offline, "resources/list")["result"]["resources"]}
    assert uris == {"openfield://guide/prompting", "openfield://catalog"}
    guide = rpc(offline, "resources/read", {"uri": "openfield://guide/prompting"})["result"]["contents"][0]
    assert guide["mimeType"] == "text/markdown" and "## action" in guide["text"]
    catalog = rpc(offline, "resources/read", {"uri": "openfield://catalog"})["result"]["contents"][0]
    assert any(m["id"] == "dolly_in" for m in json.loads(catalog["text"])["moves"])  # the shipped catalog when down
    assert rpc(offline, "resources/read", {"uri": "openfield://nope"})["error"]["code"] == -32002


@pytest.mark.parametrize(("args", "message"), [
    ({"subject": "a lighthouse at dusk", "colour": "red"}, "unknown argument"),
    ({"move": "dolly_in"}, "missing: subject"),
    ({"subject": "a lighthouse at dusk", "move": "moonwalk"}, "is not one of"),
    ({"subject": "a lighthouse at dusk", "seconds": 11}, "between 2 and 10"),
    ({"subject": "a lighthouse at dusk", "seconds": True}, "expected integer"),
    ({"subject": "ab"}, "length must be"),
])
def test_bad_arguments_come_back_as_tool_errors(offline, args, message):
    result = call(offline, "plan_shot", **args)
    assert result["isError"] is True and message in texts(result)[0]


def test_a_studio_that_is_down_is_a_tool_error_not_a_crash(offline):
    result = call(offline, "studio_status")
    assert result["isError"] is True and "not answering" in texts(result)[0]


def test_local_files_must_be_absolute_and_exist(offline, tmp_path):
    rel = call(offline, "direct_shot", subject="a lighthouse at dusk", from_image="hero.png")
    assert rel["isError"] and "absolute path" in texts(rel)[0]
    missing = call(offline, "direct_shot", subject="a lighthouse at dusk", from_image=str(tmp_path / "none.png"))
    assert missing["isError"] and "no such file" in texts(missing)[0]


def test_a_whole_take_through_mcp(client, tmp_path):
    """Plan, direct, look at the stills, approve, look at the finished strip, read the receipt, save the video."""
    server = mcp.Server(mcp.Studio("http://testserver", client=client))
    status = first_json(call(server, "studio_status"))
    assert status["can_render"] is True and status["reliable"]["moves"].endswith("/49")

    plan = first_json(call(server, "plan_shot", subject="A lighthouse keeper stands on the gallery at dusk",
                           action="she lifts a lantern and swings it slowly", move="static"))
    assert plan["stills"] == 1 and "lifts a lantern" in plan["video_prompt"]

    started = first_json(call(server, "direct_shot", subject="A lighthouse at dusk", move="dolly_in", seed=5))
    take_id = started["take_id"]
    assert started["page"].endswith(f"#/takes/{take_id}")

    waiting = call(server, "wait_for_take", take_id=take_id, timeout_s=60)
    head = first_json(waiting)
    assert head["status"] == "awaiting_approval", head
    stills = images(waiting)
    assert len(stills) == 2 and all(b["mimeType"] == "image/jpeg" for b in stills)
    with Image.open(io.BytesIO(base64.b64decode(stills[0]["data"]))) as im:
        assert max(im.size) <= mcp.STILL_PX

    assert first_json(call(server, "approve_stills", take_id=take_id))["take_id"] == take_id
    done = call(server, "wait_for_take", take_id=take_id, timeout_s=60)
    head = first_json(done)
    assert head["status"] == "succeeded", head
    assert head["video"].endswith(f"/api/takes/{take_id}/media/take.mp4")
    strip = images(done)
    assert len(strip) == 1
    with Image.open(io.BytesIO(base64.b64decode(strip[0]["data"]))) as im:
        assert im.size[0] > im.size[1]  # 3 x 2 frames

    receipt = first_json(call(server, "get_receipt", take_id=take_id))
    assert receipt["checksum_holds"] is True and receipt["audit"]["result"] == "pass"

    target = tmp_path / "out" / "shot.mp4"
    saved = first_json(call(server, "save_take", take_id=take_id, path=str(target)))
    assert target.is_file() and saved["bytes"] == target.stat().st_size > 0
    again = call(server, "save_take", take_id=take_id, path=str(target))
    assert again["isError"] and "overwrite" in texts(again)[0]

    listed = first_json(call(server, "list_takes", limit=5))
    assert take_id in [t["take_id"] for t in listed]

    refused = call(server, "approve_stills", take_id=take_id)  # nothing is waiting any more
    assert refused["isError"] and "not waiting" in texts(refused)[0]


def test_two_takes_become_a_movie(client):
    server = mcp.Server(mcp.Studio("http://testserver", client=client))
    ids = []
    for subject in ("A lighthouse at dusk", "A harbour at night"):
        take_id = first_json(call(server, "direct_shot", subject=subject, move="static", seed=7,
                                  auto_approve=True))["take_id"]
        assert first_json(call(server, "wait_for_take", take_id=take_id, timeout_s=60,
                               show_images=False))["status"] == "succeeded"
        ids.append(take_id)
    movie = call(server, "make_movie", take_ids=ids, crossfade_s=0.2)
    head = first_json(movie)
    assert head["status"] == "succeeded" and head["kind"] == "export" and images(movie)


def test_stdio_answers_one_line_per_request(tmp_path):
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        "not json at all",
        {"jsonrpc": "2.0", "id": 3, "method": "ping"},
    ]
    payload = "".join((m if isinstance(m, str) else json.dumps(m)) + "\n" for m in lines).encode()
    done = subprocess.run([sys.executable, "-m", "openfield", "mcp", "--url", "http://127.0.0.1:9"],
                          input=payload, capture_output=True, timeout=60, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    replies = [json.loads(line) for line in done.stdout.decode("utf-8").splitlines()]
    assert sorted(str(r["id"]) for r in replies) == ["1", "2", "3", "None"]
    assert next(r for r in replies if r["id"] is None)["error"]["code"] == -32700


def test_the_render_budget_is_a_hard_cap(client):
    server = mcp.Server(mcp.Studio("http://testserver", client=client), max_renders=1)
    first = call(server, "direct_shot", subject="A lighthouse at dusk", move="static", seed=3)
    assert first["isError"] is False
    before = len(client.get("/api/takes").json())
    second = call(server, "direct_shot", subject="A harbour at night", move="static", seed=4)
    assert second["isError"] is True and "budget is spent" in texts(second)[0]
    assert len(client.get("/api/takes").json()) == before  # nothing was started
    budget = first_json(call(server, "studio_status"))["render_budget"]
    assert budget["used"] == 1 and budget["max"] == 1 and budget["left"] == 0


def test_a_refused_render_does_not_use_the_budget(client):
    server = mcp.Server(mcp.Studio("http://testserver", client=client), max_renders=1)
    refused = call(server, "direct_shot", subject="A lighthouse at dusk", cast_id="ca_00000000")
    assert refused["isError"] is True and server.renders_used == 0
    assert call(server, "direct_shot", subject="A lighthouse at dusk", move="static")["isError"] is False
    assert server.renders_used == 1


def test_approving_without_a_reroll_is_part_of_the_shot_not_a_new_render(client):
    server = mcp.Server(mcp.Studio("http://testserver", client=client), max_renders=1)
    take_id = first_json(call(server, "direct_shot", subject="A lighthouse at dusk", move="dolly_in", seed=5))["take_id"]
    assert first_json(call(server, "wait_for_take", take_id=take_id, timeout_s=60,
                           show_images=False))["status"] == "awaiting_approval"
    assert call(server, "approve_stills", take_id=take_id)["isError"] is False
    assert server.renders_used == 1


def test_read_guide_and_recovery_hints(offline):
    guide = texts(call(offline, "read_guide"))[0]
    assert guide.startswith("# Writing shots") and "end state" in guide
    assert "Next: wait_for_take" in mcp.with_hint("this take is not waiting for approval")
    assert "list_takes(where='recorded')" in mcp.with_hint("Replay plays recorded takes only")
    assert mcp.with_hint("something else") == "something else"


def test_reroll_indices_are_bounded_before_anything_is_sent(offline):
    result = call(offline, "approve_stills", take_id="tk_20261024_000000_0000", reroll=[-1])
    assert result["isError"] is True and "between 0 and 7" in texts(result)[0]


def test_waiting_on_a_canceled_take_ends_at_once(client):
    """The ledger writes "canceled"; a wait must see it as the end, not as "still rendering"."""
    server = mcp.Server(mcp.Studio("http://testserver", client=client))
    take_id = first_json(call(server, "direct_shot", subject="A lighthouse at dusk", move="dolly_in", seed=5))["take_id"]
    assert first_json(call(server, "wait_for_take", take_id=take_id, timeout_s=60,
                           show_images=False))["status"] == "awaiting_approval"
    assert first_json(call(server, "cancel_take", take_id=take_id))["status"] == "canceled"
    head = first_json(call(server, "wait_for_take", take_id=take_id, timeout_s=60, show_images=False))
    assert head["status"] == "canceled" and "next" not in head


def test_replay_through_mcp_plays_recorded_takes_and_cuts_them(client):
    server = mcp.Server(mcp.Studio("http://testserver", client=client))
    recorded = []
    for seed in (21, 22):
        tid = first_json(call(server, "direct_shot", subject="A lighthouse at dusk", move="static", seed=seed,
                              auto_approve=True))["take_id"]
        assert first_json(call(server, "wait_for_take", take_id=tid, timeout_s=60, show_images=False))["status"] == "succeeded"
        recorded.append(tid)
    live_renders = server.renders_used  # the two takes above rendered on the live backend
    client.post("/api/backend", json={"mode": "replay"})
    status = first_json(call(server, "studio_status"))
    assert status["can_render"] is False and "replay_take" in status["note"]
    shelf = [r["take_id"] for r in first_json(call(server, "list_takes", where="recorded"))]
    assert set(recorded) <= set(shelf)
    never = call(server, "direct_shot", subject="A recipe nobody rendered", move="orbit_90")
    played = []
    for tid in recorded:
        replay = first_json(call(server, "replay_take", take_id=tid))["take_id"]
        assert first_json(call(server, "wait_for_take", take_id=replay, timeout_s=60,
                               show_images=False))["status"] == "succeeded"
        played.append(replay)
    movie = first_json(call(server, "make_movie", take_ids=played, crossfade_s=0.2))
    assert movie["status"] == "succeeded" and movie["kind"] == "export"
    assert server.renders_used == live_renders, "Replay renders nothing and costs nothing"
    started = first_json(never) if not never["isError"] else None
    if started:  # Replay accepts the call, then the take fails as never rendered
        failed = first_json(call(server, "wait_for_take", take_id=started["take_id"], timeout_s=60, show_images=False))
        assert failed["status"] == "failed"


@pytest.mark.parametrize(("tool_name", "args", "message"), [
    ("cancel_take", {"take_id": "../backend/forget#"}, "not a valid take id"),
    ("approve_stills", {"take_id": "../models/face#"}, "not a valid take id"),
    ("save_take", {"take_id": "tk_20261024_000000_0000", "path": "C:/x/status.mp4", "file": "../../../status"},
     "not a valid file"),
    ("edit_take", {"take_id": "tk_20261024_000000_0000", "preset": "remove", "detail": "the cup", "still": "/etc/x"},
     "not a valid still"),
    ("make_movie", {"take_ids": ["tk_20261024_000000_0000", "../status"]}, "every item must match"),
    ("direct_shot", {"subject": "A lighthouse at dusk", "cast_id": "../../backend"}, "cast_id:"),
])
def test_ids_and_paths_cannot_reach_other_routes(offline, tool_name, args, message):
    result = call(offline, tool_name, **args)
    assert result["isError"] is True and message in texts(result)[0]


def test_local_files_network_paths_and_file_types(offline, tmp_path):
    unc = call(offline, "direct_shot", subject="A lighthouse at dusk", from_image=chr(92) * 2 + "fileserver" + chr(92) + "share" + chr(92) + "hero.png")
    assert unc["isError"] and "network paths" in texts(unc)[0]
    big = tmp_path / "huge.png"
    with open(big, "wb") as f:
        f.truncate((mcp.MAX_IMAGE_MB + 1) * 1024 * 1024)
    too_big = call(offline, "direct_shot", subject="A lighthouse at dusk", from_image=str(big))
    assert too_big["isError"] and "MB limit" in texts(too_big)[0]
    wrong_type = call(offline, "save_take", take_id="tk_20261024_000000_0000", path=str(tmp_path / "x.bat"))
    assert wrong_type["isError"] and "save a .mp4 file" in texts(wrong_type)[0]
    hints = {t["name"]: t["annotations"]["destructiveHint"] for t in rpc(offline, "tools/list")["result"]["tools"]}
    assert hints["save_take"] is True and hints["cancel_take"] is True and hints["direct_shot"] is False


def test_the_studio_makes_the_small_still_itself(client):
    take = client.post("/api/takes/direct", json={"subject": "A lighthouse at dusk", "rig": {"movement": "static"},
                                                   "seed": 3, "auto_approve": True}).json()
    studio = mcp.Studio("http://testserver", client=client)
    for _ in range(600):
        if client.get(f"/api/takes/{take['id']}").json()["status"] == "succeeded":
            break
        import time
        time.sleep(0.1)
    data = studio.thumb(take["id"], "poster.png", 40)
    with Image.open(io.BytesIO(data)) as im:
        assert im.format == "JPEG" and max(im.size) <= 40


def test_a_budget_file_keeps_one_cap_across_server_processes(client, tmp_path):
    # an agent that starts its MCP server anew every turn (Codex, OpenCode) must not get a fresh cap each turn
    budget = tmp_path / "budget.json"
    first = mcp.Server(mcp.Studio("http://testserver", client=client), max_renders=1, budget_file=budget)
    assert call(first, "direct_shot", subject="A lighthouse at dusk", move="static", seed=3)["isError"] is False
    assert json.loads(budget.read_text(encoding="utf-8"))["used"] == 1
    second = mcp.Server(mcp.Studio("http://testserver", client=client), max_renders=1, budget_file=budget)
    refused = call(second, "direct_shot", subject="A harbour at night", move="static", seed=4)
    assert refused["isError"] is True and "budget is spent" in texts(refused)[0], "the next process reads what was used"
