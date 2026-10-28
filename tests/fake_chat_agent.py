"""A stand-in for the Chat room's agents, for the Chat tests. It answers like the real command lines do:

- Claude Code (`-p --input-format stream-json --output-format stream-json`): reads messages from stdin (one JSON line
  each) and answers with a system init, the text in streamed pieces, the whole message, and a result.
- Codex (`exec ... --json`, one message on stdin per run): thread.started, items, turn.completed; `exec resume <id>`
  keeps the thread.
- OpenCode (`run --format json`, one message on stdin per run): step_start, text and tool_use parts with a sessionID;
  the studio's tools are called from its code mode (`execute`).

A message with "shoot" in it also uses a studio tool (naming a take id); "slow" keeps talking until it is stopped;
"nologin" fails the way an expired sign-in does; "quota" the way a spent plan does. It never calls the MCP server it is
given, and it records its own command line (each run) for the tests to read.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

SESSION = os.environ.get("FAKE_AGENT_SESSION") or str(uuid.uuid4())
TAKE = "tk_20261025_120000_abcd"


def out(event: dict) -> None:
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def say(text: str, message_id: str) -> None:
    out({"type": "stream_event", "event": {"type": "message_start", "message": {"id": message_id}}})
    out({"type": "stream_event", "event": {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}})
    for i in range(0, len(text), 7):
        out({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text[i:i + 7]}}})
    out({"type": "assistant", "message": {"id": message_id, "content": [{"type": "text", "text": text}]}})


def claude() -> int:
    turn = 0
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        message = json.loads(line)
        if message.get("type") == "control_request":
            out({"type": "control_response", "response": {"subtype": "success", "request_id": message.get("request_id")}})
            continue
        text = "".join(part.get("text", "") for part in message["message"]["content"])
        turn += 1
        out({"type": "system", "subtype": "init", "session_id": SESSION, "model": "fake-agent-1",
             "tools": ["mcp__openfield__studio_status", "mcp__openfield__direct_shot"], "mcp_servers": [{"name": "openfield", "status": "connected"}]})
        started = time.monotonic()
        if "slow" in text:
            # talk until the room interrupts (a control_request arrives on stdin while this turn runs)
            mid = f"msg_{turn}"
            out({"type": "stream_event", "event": {"type": "message_start", "message": {"id": mid}}})
            out({"type": "stream_event", "event": {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}})
            out({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Counting: 1"}}})
            interrupted = sys.stdin.readline()
            request = json.loads(interrupted) if interrupted.strip() else {}
            out({"type": "control_response", "response": {"subtype": "success", "request_id": request.get("request_id")}})
            out({"type": "result", "subtype": "error_during_execution", "is_error": True, "duration_ms": 50, "num_turns": 1,
                 "session_id": SESSION})
            continue
        if "nologin" in text:
            out({"type": "result", "subtype": "success", "is_error": True, "duration_ms": 5, "num_turns": 1, "session_id": SESSION,
                 "result": "Invalid API key · Please run /login"})
            continue
        if "shoot" in text:
            say("I'll start the shot.", f"msg_{turn}a")
            tool_id = f"toolu_{turn}"
            out({"type": "assistant", "message": {"id": f"msg_{turn}a", "content": [
                {"type": "tool_use", "id": tool_id, "name": "mcp__openfield__direct_shot", "input": {"subject": "A lighthouse at dusk"}}]}})
            out({"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tool_id, "content": [{"type": "text", "text": f"Started {TAKE}. Call wait_for_take."}]}]}})
            say(f"Started {TAKE}: the stills come first.", f"msg_{turn}b")
        else:
            say(f"You said: {text}", f"msg_{turn}")
        out({"type": "result", "subtype": "success", "is_error": False, "duration_ms": int((time.monotonic() - started) * 1000),
             "num_turns": 1, "session_id": SESSION, "result": "ok"})
    return 0


def last_part(text: str) -> str:
    """The person's words: Codex's first message carries the studio's brief before a --- line."""
    return text.rsplit("\n---\n\n", 1)[-1].strip()


def codex(argv: list[str]) -> int:
    thread = argv[argv.index("resume") + 1] if "resume" in argv else SESSION
    text = last_part(sys.stdin.read())
    out({"type": "thread.started", "thread_id": thread})
    out({"type": "turn.started"})
    if "nologin" in text:
        out({"type": "error", "message": "Reconnecting... 1/5 (workspace routing discovery unauthorized (401))"})
        out({"type": "turn.failed", "error": {"message": "workspace routing discovery unauthorized (401)"}})
        sys.stderr.write("ERROR codex_login::auth::manager: Failed to refresh token: Please log out and sign in again.\n")
        return 1
    if "slow" in text:
        out({"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": "Counting: 1"}})
        time.sleep(60)  # until the room stops this turn
        return 0
    if "shoot" in text:
        call = {"id": "item_1", "type": "mcp_tool_call", "server": "openfield", "tool": "direct_shot",
                "arguments": {"subject": "A lighthouse at dusk"}, "status": "in_progress"}
        out({"type": "item.started", "item": call})
        out({"type": "item.completed", "item": {**call, "status": "completed",
                                                "result": {"content": [{"type": "text", "text": f"Started {TAKE}. Call wait_for_take."}]}}})
        out({"type": "item.completed", "item": {"id": "item_2", "type": "agent_message", "text": f"Started {TAKE}: the stills come first."}})
    else:
        out({"type": "item.completed", "item": {"id": "item_3", "type": "agent_message", "text": f"You said: {text}"}})
    out({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}})
    return 0


def opencode(argv: list[str]) -> int:
    session = argv[argv.index("--session") + 1] if "--session" in argv else f"ses_{SESSION}"
    text = sys.stdin.read().strip()
    base = {"sessionID": session}

    def part(kind: str, **fields) -> dict:
        return {"id": f"prt_{uuid.uuid4().hex[:8]}", "sessionID": session, "type": kind, **fields}

    out({"type": "step_start", **base, "part": part("step-start")})
    if "quota" in text:
        out({"type": "error", **base, "error": {"name": "APIError", "data": {"message": "429: rate limit exceeded for this plan"}}})
        return 1
    if "slow" in text:
        out({"type": "text", **base, "part": part("text", text="Counting: 1")})
        time.sleep(60)  # until the room stops this turn
        return 0
    if "shoot" in text:
        code = 'const r = await tools.openfield.direct_shot({subject: "A lighthouse at dusk", move: "dolly_in"});\nreturn r;'
        out({"type": "tool_use", **base, "part": part("tool", tool="execute", state={
            "status": "completed", "input": {"code": code}, "output": f"Started {TAKE}. Call wait_for_take."})})
        out({"type": "tool_use", **base, "part": part("tool", tool="read", state={
            "status": "error", "input": {"path": "C:/"}, "error": "Permission denied: read"})})
        out({"type": "text", **base, "part": part("text", text=f"Started {TAKE}: the stills come first.")})
    else:
        out({"type": "text", **base, "part": part("text", text=f"You said: {text}")})
    out({"type": "step_finish", **base, "part": part("step-finish")})
    return 0


def main() -> int:
    argv = sys.argv[1:]
    log = os.environ.get("FAKE_AGENT_LOG")
    if log:
        Path(log).write_text(json.dumps({"argv": argv, "cwd": os.getcwd()}), encoding="utf-8")
    if argv[:1] == ["exec"]:
        return codex(argv)
    if argv[:1] == ["run"]:
        if "--server" in argv and not os.environ.get("OPENCODE_SERVER_PASSWORD"):
            sys.stderr.write("UnauthorizedError: Authentication required\n")
            return 1
        return opencode(argv)
    if argv[:1] == ["serve"]:  # the chat's OpenCode server: it says it listens, then waits to be stopped
        print(f"server listening on http://127.0.0.1:{argv[argv.index('--port') + 1]}", flush=True)
        time.sleep(3600)
        return 0
    return claude()


if __name__ == "__main__":
    raise SystemExit(main())
