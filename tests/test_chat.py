"""The Chat room: the agent's command line, who may use the room, and whole conversations with a stand-in agent."""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openfield.app import create_app
from openfield.chat import (
    Chat,
    ChatConfig,
    ChatError,
    EventLog,
    agent_command,
    mcp_config,
    tool_result,
)
from openfield.config import PACKAGE_DIR, Settings

FAKE = str(Path(__file__).with_name("fake_chat_agent.py"))
TAKE = "tk_20261025_120000_abcd"


def agent_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("OPENFIELD_")}
    return {**env, "OPENFIELD_CHAT_AGENT": "claude", "OPENFIELD_CHAT_CLAUDE": FAKE, "FAKE_AGENT_LOG": str(tmp_path / "agent-argv.json"), **extra}


def wait_for(chat: Chat, done, timeout: float = 30.0) -> list[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events = chat.log.after(0)
        if done(events):
            return events
        time.sleep(0.05)
    raise AssertionError(f"timed out; events so far: {[e['kind'] for e in chat.log.after(0)]}")


def turns(events: list[dict]) -> int:
    return sum(1 for e in events if e["kind"] == "turn")


@pytest.fixture
def chat(tmp_path):
    room = Chat(tmp_path / "data", "127.0.0.1", agent_env(tmp_path, FAKE_AGENT_SESSION="sess-1"))
    yield room
    room.close()


def test_the_agent_gets_the_studios_mcp_server_and_nothing_else():
    cmd = agent_command("claude", mcp_config=Path("m.json"), guide=Path("g.md"), model=None, resume=None)
    assert cmd[0] == "claude"
    pairs = dict(zip(cmd, cmd[1:], strict=False))
    assert "--strict-mcp-config" in cmd, "none of the person's own MCP servers"
    assert pairs["--tools"] == "", "no shell and no file tools"
    assert pairs["--allowedTools"] == "mcp__openfield" and pairs["--permission-mode"] == "dontAsk"
    assert pairs["--setting-sources"] == "local", "none of the person's hooks or settings"
    assert pairs["--input-format"] == pairs["--output-format"] == "stream-json"
    assert pairs["--append-system-prompt-file"] == "g.md" and "--resume" not in cmd and "--model" not in cmd
    again = agent_command("claude", mcp_config=Path("m.json"), guide=Path("g.md"), model="haiku", resume="s-9")
    assert dict(zip(again, again[1:], strict=False))["--resume"] == "s-9" and dict(zip(again, again[1:], strict=False))["--model"] == "haiku"
    server = mcp_config("http://127.0.0.1:8877", 6)["mcpServers"]["openfield"]
    assert server["args"] == ["-m", "openfield", "mcp", "--url", "http://127.0.0.1:8877", "--max-renders", "6"]


def test_a_python_stand_in_runs_with_this_python():
    cmd = agent_command("C:/x/fake.py", mcp_config=Path("m.json"), guide=Path("g.md"), model=None, resume=None)
    assert cmd[1] == "C:/x/fake.py" and cmd[2] == "-p"


def test_the_room_runs_only_on_a_local_studio_with_an_agent(tmp_path):
    local = {"OPENFIELD_CHAT_CLAUDE": FAKE, "OPENFIELD_CHAT_AGENT": "claude"}
    assert ChatConfig.read("127.0.0.1", local).unavailable() is None
    assert ChatConfig.read("127.0.0.1", {**local, "OPENFIELD_ALLOWED_HOSTS": "studio.example"}).unavailable()[0] == "exposed"
    assert ChatConfig.read("0.0.0.0", local).unavailable()[0] == "exposed"
    assert ChatConfig.read("0.0.0.0", {**local, "OPENFIELD_CHAT": "on"}).unavailable() is None, "said so on purpose"
    assert ChatConfig.read("127.0.0.1", {**local, "OPENFIELD_CHAT": "off"}).unavailable()[0] == "off"
    nothing = ChatConfig.read("127.0.0.1", {"PATH": str(tmp_path)})
    assert nothing.agent is None and nothing.unavailable()[0] == "no_agent"
    assert "npm install -g @anthropic-ai/claude-code" in nothing.unavailable()[1]
    assert ChatConfig.read("127.0.0.1", {**local, "OPENFIELD_CHAT_RENDERS": "0"}).renders == 0
    with pytest.raises(ValueError):
        ChatConfig.read("127.0.0.1", {"OPENFIELD_CHAT": "maybe"})
    with pytest.raises(ValueError):
        ChatConfig.read("127.0.0.1", {"OPENFIELD_CHAT_RENDERS": "lots"})


def test_only_this_computer_may_use_the_room():
    Chat.guard("127.0.0.1")
    Chat.guard("::1")
    with pytest.raises(ChatError) as refused:
        Chat.guard("203.0.113.5")  # a documentation address: any other computer
    assert refused.value.status == 403


def test_a_whole_conversation_streams_in_order_and_is_kept(chat, tmp_path):
    chat.send("hello", "http://127.0.0.1:9")
    events = wait_for(chat, lambda ev: turns(ev) == 1)
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "status" and kinds[1] == "user" and "ready" in kinds and kinds[-1] == "status"
    text = next(e for e in events if e["kind"] == "text")
    assert text["text"] == "You said: hello"
    assert not [e for e in events if e["kind"] == "delta" and e["id"] == text["id"]], "the whole text replaced its pieces"
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)
    info = chat.info()
    assert info["state"] == "idle" and info["session"] == "sess-1" and info["model"] == "fake-agent-1" and info["enabled"]
    saved = json.loads((tmp_path / "data" / "chat" / "chat.json").read_text(encoding="utf-8"))
    assert saved["session"] == "sess-1" and any(e["kind"] == "text" for e in saved["events"])
    argv = json.loads((tmp_path / "agent-argv.json").read_text(encoding="utf-8"))
    assert "--strict-mcp-config" in argv["argv"] and Path(argv["cwd"]) == tmp_path / "data" / "chat" / "agent"
    assert "This chat may start at most 6 renders" in (tmp_path / "data" / "chat" / "guide.md").read_text(encoding="utf-8")
    pid = chat.proc.pid

    chat.send("shoot a lighthouse", "http://127.0.0.1:9")
    events = wait_for(chat, lambda ev: turns(ev) == 2)
    tool = next(e for e in events if e["kind"] == "tool")
    assert tool["name"] == "direct_shot" and tool["input"] == {"subject": "A lighthouse at dusk"}
    result = next(e for e in events if e["kind"] == "result")
    assert result["id"] == tool["id"] and result["takes"] == [TAKE] and not result["error"]
    assert any(e["kind"] == "text" and TAKE in e["text"] for e in events)
    assert chat.proc.pid == pid, "one agent process for the whole conversation"


def test_stop_interrupts_a_turn_and_the_next_message_still_works(chat):
    chat.send("slow please", "http://127.0.0.1:9")
    wait_for(chat, lambda ev: any(e["kind"] == "delta" for e in ev))
    with pytest.raises(ChatError) as busy:
        chat.send("are you there", "http://127.0.0.1:9")
    assert busy.value.code == "chat_busy"
    assert chat.stop()["state"] == "stopping"
    events = wait_for(chat, lambda ev: turns(ev) == 1)
    turn = next(e for e in events if e["kind"] == "turn")
    assert turn["stopped"] and not turn["error"]
    assert chat.info()["state"] == "idle"
    chat.send("again", "http://127.0.0.1:9")
    events = wait_for(chat, lambda ev: turns(ev) == 2)
    assert any(e["kind"] == "text" and e["text"] == "You said: again" for e in events)


def test_an_empty_or_huge_message_is_refused(chat):
    with pytest.raises(ChatError) as empty:
        chat.send("   ", "http://127.0.0.1:9")
    assert empty.value.status == 422
    with pytest.raises(ChatError) as huge:
        chat.send("x" * 9000, "http://127.0.0.1:9")
    assert huge.value.code == "message_too_long"
    assert chat.proc is None, "nothing started for a refused message"


def test_new_chat_forgets_the_conversation_and_the_agents_session(chat, tmp_path):
    chat.send("hello", "http://127.0.0.1:9")
    wait_for(chat, lambda ev: turns(ev) == 1)
    chat.reset()
    assert [e["kind"] for e in chat.log.after(0)] == ["reset"]
    assert chat.info()["session"] is None and chat.proc is None
    assert not (tmp_path / "data" / "chat" / "chat.json").exists()


def test_after_a_restart_the_conversation_is_back_and_the_agent_resumes_its_session(tmp_path):
    first = Chat(tmp_path / "data", "127.0.0.1", agent_env(tmp_path, FAKE_AGENT_SESSION="sess-7"))
    first.send("hello", "http://127.0.0.1:9")
    wait_for(first, lambda ev: turns(ev) == 1)
    first.close()
    second = Chat(tmp_path / "data", "127.0.0.1", agent_env(tmp_path, FAKE_AGENT_SESSION="sess-7"))
    try:
        kept = second.log.after(0)
        assert [e["kind"] for e in kept if e["kind"] in {"user", "text"}] == ["user", "text"]
        assert second.info()["session"] == "sess-7"
        second.send("again", "http://127.0.0.1:9")
        wait_for(second, lambda ev: turns(ev) == 2)
        argv = json.loads((tmp_path / "agent-argv.json").read_text(encoding="utf-8"))["argv"]
        assert argv[argv.index("--resume") + 1] == "sess-7"
        assert min(e["seq"] for e in second.log.after(0) if e["kind"] == "user" and e["text"] == "again") > max(e["seq"] for e in kept)
    finally:
        second.close()


def test_a_tools_answer_keeps_its_pictures_small_and_names_its_takes():
    small = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}}
    huge = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "A" * 1_000_000}}
    seen = tool_result({"tool_use_id": "t1", "content": [{"type": "text", "text": f"Started {TAKE}.\n" + "y" * 7000}, small, huge]})
    assert seen["takes"] == [TAKE] and seen["images"] == ["data:image/jpeg;base64,QUJD"] and not seen["error"]
    assert len(seen["text"]) < 6100 and seen["text"].endswith("…")
    assert tool_result({"tool_use_id": "t2", "content": "plain words", "is_error": True})["error"]


def test_the_event_log_follows_new_events_and_keeps_only_a_texts_whole():
    log = EventLog()
    log.emit({"kind": "delta", "id": "m.1", "text": "Hel"})
    log.emit({"kind": "delta", "id": "m.1", "text": "lo"})
    log.emit({"kind": "text", "id": "m.1", "text": "Hello"})
    assert [e["kind"] for e in log.after(0)] == ["text"] and log.seq == 3

    async def follow() -> list[str]:
        got = []
        threading.Timer(0.2, lambda: log.emit({"kind": "user", "id": "u", "text": "next"})).start()
        async for event in log.follow(0, keepalive=5):
            if event is not None:
                got.append(event["kind"])
            if len(got) == 2:
                break
        return got

    assert asyncio.run(follow()) == ["text", "user"]


def test_the_chat_api_answers_this_computer(tmp_path, monkeypatch):
    for key in [k for k in os.environ if k.startswith("OPENFIELD_")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENFIELD_CHAT_CLAUDE", FAKE)
    monkeypatch.setenv("OPENFIELD_CHAT_AGENT", "claude")
    monkeypatch.setenv("FAKE_AGENT_SESSION", "sess-api")
    monkeypatch.delenv("COMFY_BASE_URL", raising=False)
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>OpenField</title>")
    settings = Settings(host="127.0.0.1", port=0, data_dir=tmp_path / "data", backend="replay", comfy_base_url=None,
                        has_api_key=False, workflow_dir=PACKAGE_DIR / "workflows", showcase_dir=tmp_path / "showcase", web_dir=web)
    app = create_app(settings)
    with TestClient(app) as client:
        info = client.get("/api/chat").json()
        assert info["enabled"] and info["lane"]["label"] == "Claude Code" and info["renders"] == 6
        assert client.post("/api/chat/messages", json={"text": ""}).status_code == 422
        sent = client.post("/api/chat/messages", json={"text": "hi"})
        assert sent.status_code == 202 and sent.json()["seq"] >= 1
        events = wait_for(app.state.chat, lambda ev: turns(ev) == 1)
        assert any(e["kind"] == "text" and e["text"] == "You said: hi" for e in events)
        assert client.post("/api/chat/stop").json()["state"] == "idle", "nothing to stop between turns"
        assert client.post("/api/chat/reset").json()["state"] == "idle"
        assert client.post("/api/chat/messages", json={"text": "x"}, headers={"Origin": "https://elsewhere.example"}).status_code == 403


# -- the agent lanes: OpenCode (open weights), Claude Code, Codex ------------------------------------------------------

def lane_env(tmp_path: Path, lane: str, session: str = "s1") -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("OPENFIELD_")}
    return {**env, "OPENFIELD_CHAT_AGENT": lane, f"OPENFIELD_CHAT_{lane.upper()}": FAKE, "FAKE_AGENT_SESSION": session,
            "FAKE_AGENT_LOG": str(tmp_path / "agent-argv.json")}


def argv_of(tmp_path: Path) -> list[str]:
    return json.loads((tmp_path / "agent-argv.json").read_text(encoding="utf-8"))["argv"]


def test_the_default_agent_is_the_first_installed_open_weights_first(tmp_path):
    both = {"PATH": str(tmp_path), "OPENFIELD_CHAT_OPENCODE": FAKE, "OPENFIELD_CHAT_CLAUDE": FAKE}
    cfg = ChatConfig.read("127.0.0.1", both)
    assert cfg.lane == "opencode" and cfg.agent == FAKE and cfg.unavailable() is None
    assert ChatConfig.read("127.0.0.1", {**both, "OPENFIELD_CHAT_AGENT": "claude"}).lane == "claude"
    codex = ChatConfig.read("127.0.0.1", {**both, "OPENFIELD_CHAT_AGENT": "codex"})
    assert codex.agent is None and codex.unavailable()[0] == "no_agent" and "codex login" in codex.unavailable()[1]
    with pytest.raises(ValueError):
        ChatConfig.read("127.0.0.1", {**both, "OPENFIELD_CHAT_AGENT": "gemini"})


def test_codex_runs_one_process_per_message_resumes_its_thread_and_gets_only_the_studio(tmp_path):
    room = Chat(tmp_path / "data", "127.0.0.1", lane_env(tmp_path, "codex", "thread-1"))
    try:
        assert room.info()["lane"] == {"id": "codex", "label": "Codex", "open_weights": False}
        room.send("hello", "http://127.0.0.1:9")
        events = wait_for(room, lambda ev: turns(ev) == 1)
        assert any(e["kind"] == "text" and e["text"] == "You said: hello" for e in events), "its brief is not shown as words"
        argv = argv_of(tmp_path)
        assert argv[:2] == ["exec", "-"] and "--json" in argv and argv[argv.index("--sandbox") + 1] == "read-only"
        servers = argv[argv.index("-c") + 1]
        assert servers.startswith("mcp_servers={openfield=") and "--budget-file" in servers and '"--max-renders", "6"' in servers
        assert 'approval_policy="never"' in argv
        assert room.info()["session"] == "thread-1" and room.proc is None, "the turn's process ended with the turn"
        room.send("shoot a lighthouse", "http://127.0.0.1:9")
        events = wait_for(room, lambda ev: turns(ev) == 2)
        assert argv_of(tmp_path)[:3] == ["exec", "resume", "thread-1"]
        tool = next(e for e in events if e["kind"] == "tool")
        assert tool["name"] == "direct_shot" and tool["input"] == {"subject": "A lighthouse at dusk"}
        result = next(e for e in events if e["kind"] == "result")
        assert result["id"] == tool["id"] and result["takes"] == [TAKE] and not result["error"]
    finally:
        room.close()


def test_opencode_is_the_open_weights_lane_with_the_studios_tools_and_nothing_else(tmp_path):
    room = Chat(tmp_path / "data", "127.0.0.1", lane_env(tmp_path, "opencode", "abc"))
    try:
        info = room.info()
        assert info["lane"]["open_weights"] and any(m["value"].startswith("opencode-go/") for m in next(
            lane for lane in info["lanes"] if lane["id"] == "opencode")["models"])
        room.send("hello", "http://127.0.0.1:9")
        wait_for(room, lambda ev: turns(ev) == 1)
        folder = tmp_path / "data" / "chat" / "agent-opencode"
        config = json.loads((folder / "opencode.json").read_text(encoding="utf-8"))
        command = config["mcp"]["servers"]["openfield"]["command"]
        assert command[1:4] == ["-m", "openfield", "mcp"] and "--budget-file" in command
        agent = (folder / ".opencode" / "agents" / "openfield-chat.md").read_text(encoding="utf-8")
        assert '{ action: "*", resource: "*", effect: deny }' in agent and '{ action: "openfield_*", resource: "*", effect: allow }' in agent
        assert "tools.openfield.studio_status" in agent and "direct_shot" in agent, "the code-mode tools are named"
        argv = argv_of(tmp_path)
        assert argv[:3] == ["run", "--format", "json"] and argv[argv.index("--agent") + 1] == "openfield-chat"
        assert argv[argv.index("--server") + 1].startswith("http://127.0.0.1:"), "turns go to the chat's own OpenCode server"
        room.choose(model="opencode-go/deepseek-v4.1-flash")
        room.send("shoot a lighthouse", "http://127.0.0.1:9")
        events = wait_for(room, lambda ev: turns(ev) == 2)
        argv = argv_of(tmp_path)
        assert argv[argv.index("--session") + 1] == "ses_abc" and argv[argv.index("-m") + 1] == "opencode-go/deepseek-v4.1-flash", \
            "on its warm server the session resumes, the studio's tools still connected"
        said = next(e for e in events if e["kind"] == "text" and TAKE in e["text"])
        assert said, "the second turn still knows the first: the conversation so far travels in the message"
        tools = [e for e in events if e["kind"] == "tool"]
        assert tools[0]["name"] == "direct_shot" and tools[0]["input"] == {"subject": "A lighthouse at dusk", "move": "dolly_in"}
        assert tools[1]["name"] == "read", "a refused tool is shown, not hidden"
        results = [e for e in events if e["kind"] == "result"]
        assert results[0]["takes"] == [TAKE] and not results[0]["error"] and results[1]["error"]
    finally:
        room.close()


def test_a_failed_agent_says_what_to_do_in_plain_words(tmp_path):
    for lane, message, words in (("codex", "nologin", "codex login"), ("opencode", "quota please", "usage limit"),
                                 ("claude", "nologin", "Run `claude`")):
        room = Chat(tmp_path / lane, "127.0.0.1", lane_env(tmp_path, lane))
        try:
            room.send(message, "http://127.0.0.1:9")
            turn = next(e for e in wait_for(room, lambda ev: turns(ev) == 1) if e["kind"] == "turn")
            assert turn["error"] and words in turn["text"], (lane, turn)
            assert "Traceback" not in turn["text"] and "auth::manager" not in turn["text"], "never the raw stderr"
        finally:
            room.close()


def test_stop_ends_a_per_turn_agents_turn_and_says_started_renders_keep_going(tmp_path):
    room = Chat(tmp_path / "data", "127.0.0.1", lane_env(tmp_path, "codex"))
    try:
        room.send("slow please", "http://127.0.0.1:9")
        wait_for(room, lambda ev: any(e["kind"] == "text" for e in ev))
        assert room.stop()["state"] == "stopping"
        events = wait_for(room, lambda ev: turns(ev) == 1)
        turn = next(e for e in events if e["kind"] == "turn")
        assert turn["stopped"] and not turn["error"]
        assert any(e["kind"] == "notice" and "Takes" in e["text"] for e in events)
        assert room.info()["state"] == "idle"
    finally:
        room.close()


def test_one_render_cap_for_the_whole_chat_and_another_agent_is_a_new_chat(tmp_path):
    room = Chat(tmp_path / "data", "127.0.0.1", lane_env(tmp_path, "claude"))
    try:
        room.budget.parent.mkdir(parents=True, exist_ok=True)
        room.budget.write_text(json.dumps({"used": 2, "max": 6}), encoding="utf-8")
        assert room.info()["renders_left"] == 4, "renders already started by earlier turns count"
        room.send("hello", "http://127.0.0.1:9")
        wait_for(room, lambda ev: turns(ev) == 1)
        assert room.info()["renders_left"] == 4, "a restart, a resume or a new turn keeps the count"
        room.choose(model="haiku")
        assert room.proc is None and room.info()["choice"] == "haiku" and room.info()["session"], "same conversation, new model"
        room.choose(lane="codex")
        assert [e["kind"] for e in room.log.after(0)] == ["reset"] and room.info()["session"] is None
        assert room.info()["lane"]["id"] == "codex" and room.info()["renders_left"] == 6 and not room.budget.exists()
        with pytest.raises(ChatError):
            room.choose(lane="gemini")
    finally:
        room.close()


def test_after_a_restart_opencode_starts_a_fresh_session_told_the_conversation_so_far(tmp_path):
    first = Chat(tmp_path / "data", "127.0.0.1", lane_env(tmp_path, "opencode", "abc"))
    first.send("hello there", "http://127.0.0.1:9")
    wait_for(first, lambda ev: turns(ev) == 1)
    first.close()  # the studio stops: the chat's OpenCode server goes with it
    second = Chat(tmp_path / "data", "127.0.0.1", lane_env(tmp_path, "opencode", "xyz"))
    try:
        second.send("and again", "http://127.0.0.1:9")
        events = wait_for(second, lambda ev: turns(ev) == 2)
        argv = argv_of(tmp_path)
        assert "--session" not in argv, "a session resumed on a fresh server comes back without the studio's tools"
        reply = [e for e in events if e["kind"] == "text"][-1]["text"]
        assert "Person: hello there" in reply and "and again" in reply, "the conversation so far travelled in the message"
    finally:
        second.close()


def test_every_way_opencode_writes_a_studio_call_shows_as_that_tool():
    from openfield.chat import _call_input, _calls
    assert _calls('await tools.openfield.studio_status({})') == ["studio_status"]
    assert _calls('await tools["openfield"].plan_shot({subject: "A keeper", move: "dolly_in"})') == ["plan_shot"]
    assert _calls("await tools['openfield']['wait_for_take']({take_id: 'tk_1'})") == ["wait_for_take"]
    assert _calls('search({query: "plan"})') == [], "a look at the catalog is not a studio call"
    assert _call_input('await tools["openfield"].plan_shot({subject: "A keeper", move: "dolly_in"})', "plan_shot") == {"subject": "A keeper", "move": "dolly_in"}


def test_a_call_made_before_the_studios_tools_connect_is_not_shown_as_a_failure():
    """Oct 25 on the GPU box: the first call of a new chat answered "Unknown tool" (the tools reach OpenCode a few
    seconds after the message); the agent called again and it went through. Only the second call is the room's."""
    from openfield.chat import _still_connecting
    early = "Unknown tool 'openfield.studio_status'.\nUse search to find available tools."
    assert _still_connecting(["studio_status"], early)
    assert not _still_connecting(["render_film"], "Unknown tool 'openfield.render_film'."), "a name the studio lacks still shows"
    assert not _still_connecting(["studio_status"], '{"studio": "http://127.0.0.1:8765"}')
