"""The Chat room: talk to your own agent on this computer, and it works the studio for you.

A lane is a command-line agent the person has already signed in to (learned from bip-boop's adapter specs: each agent
described as data, its command line, how it resumes, how it reports):

    opencode   OpenCode with any model it is connected to; the open-weights lane (DeepSeek, Kimi, Qwen, GLM, MiniMax)
    claude     Claude Code, on the person's Claude plan
    codex      Codex, on the person's ChatGPT plan

Whatever the lane, the studio gives the agent one MCP server, `openfield mcp`, and nothing else it can use: no shell,
no file tools and none of the person's own MCP servers, hooks or settings, in a folder of its own. So the agent can do
what the studio's tools do (plan, direct, approve, edit, cut, read receipts) and no more; every render goes through the
same pipeline, approval gate, open-weights audit and receipts as a click in the app; and a chat has one render cap,
kept in a file so it holds across turns and restarts (`openfield mcp --max-renders N --budget-file F`); another agent
or New chat starts a new chat with a fresh cap. The studio holds no key: the agent runs on its own sign-in.

Claude Code runs as one long-lived process (`claude -p`, stream-json in and out). Codex and OpenCode run one process
per message and resume their own session. Their events become the room's numbered events, which the room follows as
server-sent events, so a reload or a second tab picks up the same conversation. The conversation is saved at the end
of every turn; after a restart the next message resumes the agent's session.

Only this computer may use it: the room answers loopback clients alone, and it is off when the studio is published to
other computers (OPENFIELD_ALLOWED_HOSTS or _ORIGINS, or a host other than loopback) unless OPENFIELD_CHAT=on says so.

    OPENFIELD_CHAT            auto | on | off   (auto: on when an agent is installed and the studio is local)
    OPENFIELD_CHAT_AGENT      opencode | claude | codex   (default: the first one installed, in that order)
    OPENFIELD_CHAT_MODEL      a model for the agent (its own default otherwise)
    OPENFIELD_CHAT_RENDERS    the most renders one chat may start (default 6; 0 = plan and review only)
    OPENFIELD_CHAT_CLAUDE / _CODEX / _OPENCODE   the agent to run instead of the one found (a .py file runs with Python)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SERVER = "openfield"  # the MCP server's name in the agent's config: Claude names its tools mcp__openfield__<tool>
TOOL_PREFIX = f"mcp__{SERVER}__"
TAKE_ID = re.compile(r"\btk_\d{8}_\d{6}_[0-9a-f]{4}\b")
LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
LOOPBACK_CLIENTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})  # testclient: the in-process test client
MAX_MESSAGE = 8000  # characters one message from the room may hold
MAX_TEXT = 6000  # characters of a tool's answer the room shows (the agent read all of it)
MAX_IMAGE = 900_000  # a picture a tool returned larger than this (base64 characters) stays with the agent
MAX_KEPT = 2000  # events a chat keeps; a long chat lets its oldest go
DEFAULT_RENDERS = 6
STOP_GRACE_S = 6.0  # an interrupted turn that has not ended by then is ended by stopping the agent

GUIDE = """You are the assistant director in OpenField Studio's Chat room, talking with the person who runs this studio on
their own computer. You work the studio only through the openfield tools; you have no shell and no files.

- studio_status says what is connected. In Replay nothing new renders: only recorded takes play back (replay_take).
  Say so plainly instead of trying.
- Read the guide (read_guide) before your first shot, and plan_shot before direct_shot; fix what its notes warn about.
- Renders take minutes and use the person's GPU time. Say what you will render before you start; when they asked for
  several, list them and wait for a yes. This chat may start at most {renders} renders.
- Stills wait for approval. Look at them, say what you see, and ask before approve_stills unless the person already
  told you to go ahead.
- Never say a take exists, rendered or passed a check unless a tool result says so, and never fill in what a tool
  would have said when it failed: say it failed. Write take ids exactly (tk_...): the room turns them into links.
- The person can also click: Lobby, Cast, Direct, Shots, Re-shoot and Takes are the studio's rooms.
- Answer briefly and plainly.
"""

# OpenCode 2 reaches MCP tools from code (its `execute` tool): name them, so a model never concludes there are none
CODE_MODE = """
The openfield tools are called from code, for example `await tools.openfield.studio_status({{}})` or
`await tools.openfield.plan_shot({{subject: "...", move: "dolly_in"}})`. They are: {tools}.
Never conclude the tools are gone: call them by name. If a call answers "Unknown tool" the studio is still
connecting, so wait two seconds (`await new Promise((r) => setTimeout(r, 2000))`) and call it again, up to five times,
before you say it failed. Begin every message that needs the studio with studio_status, and call one tool per step.
"""


# the first lines of every OpenCode message: its tools connect a few seconds into the turn, and a model that looks
# before they are there decides they are gone
OPENCODE_NOTE = ("(Studio note: the openfield tools connect a few seconds after this message arrives. Begin by calling "
                 "`await tools.openfield.studio_status({})`; if it answers \"Unknown tool\", wait two seconds and call it "
                 "again, up to five times. They are there.)")


class ChatError(Exception):
    """A request the room cannot do now: a status, a code and a sentence for the person."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Lane:
    id: str
    label: str
    install: str
    login: str  # what the person runs once to sign in
    open_weights: bool  # the models it runs can be open-weights ones
    models: tuple[tuple[str, str], ...]  # (value, label) offered in the room; "" is the agent's own default
    per_turn: bool  # one process per message (resumed by session) rather than one long-lived process


LANES: dict[str, Lane] = {
    "opencode": Lane("opencode", "OpenCode",
                     "Install OpenCode (https://opencode.ai) and connect a provider once (opencode auth login), then reload this page.",
                     "opencode auth login", True,
                     (("", "Its default model"), ("opencode-go/deepseek-v4.1-flash", "DeepSeek V4.1 Flash"),
                      ("opencode-go/kimi-k2.7-code", "Kimi K2.7"), ("opencode-go/qwen3.8-max", "Qwen 3.8 Max"),
                      ("minimax-coding-plan/MiniMax-M3.1-Flash", "MiniMax M3.1 Flash")), True),
    "claude": Lane("claude", "Claude Code",
                   "Install Claude Code and sign in once in a terminal (npm install -g @anthropic-ai/claude-code, then run "
                   "claude), then reload this page.",
                   "claude", False, (("", "Its default model"), ("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku")), False),
    "codex": Lane("codex", "Codex",
                  "Install Codex and sign in once (npm install -g @openai/codex, then codex login), then reload this page.",
                  "codex login", False, (("", "Its default model"),), True),
}
LANE_ORDER = ("opencode", "claude", "codex")  # the default is the first one installed: open weights first
LANE = LANES["claude"]


def _executable(env: Mapping[str, str], variable: str, name: str) -> tuple[str | None, str | None]:
    """(an explicit stand-in or its absence, the command found on the PATH)."""
    named = env.get(variable, "").strip()
    if named:
        return (named if Path(named).is_file() else shutil.which(named, path=env.get("PATH") or None)), None
    return None, shutil.which(name, path=env.get("PATH") or None)


def find_agent(env: Mapping[str, str] = os.environ) -> str | None:
    """Claude Code: OPENFIELD_CHAT_CLAUDE, else `claude` on the PATH (npm's shim resolved to its binary)."""
    named, found = _executable(env, "OPENFIELD_CHAT_CLAUDE", "claude")
    if named or env.get("OPENFIELD_CHAT_CLAUDE", "").strip():
        return named
    if not found:
        return None
    path = Path(found)
    # npm's shim (claude.cmd, or a shell script) wraps the real binary: start that, so no shell re-quotes an argument
    native = path.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / ("claude.exe" if os.name == "nt" else "claude")
    if path.suffix.lower() in {".cmd", ".bat", ".ps1", ""} and native.is_file():
        return str(native)
    return str(path)


def find_codex(env: Mapping[str, str] = os.environ) -> str | None:
    """Codex: OPENFIELD_CHAT_CODEX, else `codex` on the PATH, its npm shim resolved to the platform binary."""
    named, found = _executable(env, "OPENFIELD_CHAT_CODEX", "codex")
    if named or env.get("OPENFIELD_CHAT_CODEX", "").strip():
        return named
    if not found:
        return None
    path = Path(found)
    if path.suffix.lower() in {".cmd", ".bat", ".ps1", ""}:
        package = path.parent / "node_modules" / "@openai" / "codex"
        binary = "codex.exe" if os.name == "nt" else "codex"
        for candidate in sorted(package.glob(f"node_modules/@openai/codex-*/vendor/*/bin/{binary}")) if package.is_dir() else []:
            return str(candidate)
    return str(path)


def find_opencode(env: Mapping[str, str] = os.environ) -> str | None:
    """OpenCode: OPENFIELD_CHAT_OPENCODE, else `opencode` on the PATH, else its own installer's folder (~/.opencode/bin)."""
    named, found = _executable(env, "OPENFIELD_CHAT_OPENCODE", "opencode")
    if named or env.get("OPENFIELD_CHAT_OPENCODE", "").strip():
        return named
    if found:
        return found
    home = env.get("USERPROFILE") or env.get("HOME")
    if home:
        candidate = Path(home) / ".opencode" / "bin" / ("opencode.exe" if os.name == "nt" else "opencode")
        if candidate.is_file():
            return str(candidate)
    return None


FINDERS = {"claude": find_agent, "codex": find_codex, "opencode": find_opencode}


@dataclass(frozen=True)
class ChatConfig:
    mode: str  # auto | on | off
    model: str | None
    renders: int
    agent: str | None  # the chosen lane's executable (None: not installed)
    exposed: bool  # the studio answers other computers too
    lane: str = "claude"
    agents: tuple[tuple[str, str | None], ...] = ()  # every lane and its executable

    @classmethod
    def read(cls, host: str, env: Mapping[str, str] = os.environ, lane: str | None = None) -> ChatConfig:
        mode = env.get("OPENFIELD_CHAT", "auto").strip().lower() or "auto"
        if mode not in {"auto", "on", "off"}:
            raise ValueError("OPENFIELD_CHAT must be auto, on or off")
        try:
            renders = max(0, min(50, int(env.get("OPENFIELD_CHAT_RENDERS", DEFAULT_RENDERS))))
        except ValueError:
            raise ValueError("OPENFIELD_CHAT_RENDERS must be a whole number") from None
        exposed = (host.strip("[]").lower() not in LOCAL_HOSTS
                   or bool(env.get("OPENFIELD_ALLOWED_HOSTS", "").strip() or env.get("OPENFIELD_ALLOWED_ORIGINS", "").strip()))
        model = env.get("OPENFIELD_CHAT_MODEL", "").strip() or None
        wanted = (lane or env.get("OPENFIELD_CHAT_AGENT", "").strip().lower()) or None
        if wanted and wanted not in LANES:
            raise ValueError("OPENFIELD_CHAT_AGENT must be opencode, claude or codex")
        agents = tuple((lid, FINDERS[lid](env) if mode != "off" else None) for lid in LANE_ORDER)
        found = dict(agents)
        chosen = wanted or next((lid for lid in LANE_ORDER if found.get(lid)), "claude")
        return cls(mode, model, renders, found.get(chosen), exposed, chosen, agents)

    def unavailable(self) -> tuple[str, str] | None:
        """Why the room cannot run here (a code and a sentence), or None when it can."""
        if self.mode == "off":
            return "off", "The Chat room is turned off on this computer (OPENFIELD_CHAT=off)."
        if self.exposed and self.mode != "on":
            return "exposed", ("The Chat room is off because this studio answers other computers too: it drives your own "
                               "agent, so it runs only on a studio that listens on this computer alone.")
        if not self.agent:
            if any(path for _, path in self.agents):
                return "no_agent", f"{LANES[self.lane].label} is not installed on this computer. {LANES[self.lane].install}"
            return "no_agent", ("No agent on this computer. Any one of these will do: "
                                + " ".join(f"{LANES[lid].label}: {LANES[lid].install}" for lid in LANE_ORDER))
        return None


def _head(agent: str) -> list[str]:
    return [sys.executable, agent] if agent.endswith(".py") else [agent]


def agent_command(agent: str, *, mcp_config: Path, guide: Path, model: str | None, resume: str | None) -> list[str]:
    """Claude Code's command line: one MCP server, no other tools, none of the person's settings, stream-json both ways."""
    cmd = [*_head(agent), "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
           "--include-partial-messages", "--strict-mcp-config", "--mcp-config", str(mcp_config), "--tools", "",
           "--allowedTools", f"mcp__{SERVER}", "--permission-mode", "dontAsk", "--setting-sources", "local",
           "--append-system-prompt-file", str(guide)]
    if model:
        cmd += ["--model", model]
    if resume:
        cmd += ["--resume", resume]
    return cmd


def mcp_args(studio_url: str, renders: int, budget: Path | None = None) -> list[str]:
    args = ["-m", "openfield", "mcp", "--url", studio_url, "--max-renders", str(renders)]
    return args + (["--budget-file", str(budget)] if budget else [])


def mcp_config(studio_url: str, renders: int, budget: Path | None = None) -> dict[str, Any]:
    return {"mcpServers": {SERVER: {"command": sys.executable, "args": mcp_args(studio_url, renders, budget)}}}


def codex_command(agent: str, *, studio_url: str, renders: int, budget: Path | None, model: str | None,
                  resume: str | None) -> list[str]:
    """Codex for one message: read-only sandbox in an empty folder, no approvals, and the studio's MCP server as its only
    one (the whole `mcp_servers` table is replaced, so the person's own servers stay out). The message comes on stdin."""
    command = json.dumps(sys.executable.replace("\\", "/"))
    args = json.dumps([a.replace("\\", "/") for a in mcp_args(studio_url, renders, budget)])
    servers = f"mcp_servers={{{SERVER}={{command={command},args={args}}}}}"
    head = [*_head(agent), "exec"]
    if resume:
        head += ["resume", resume]
    cmd = [*head, "-", "--json", "--skip-git-repo-check", "-c", servers, "-c", 'approval_policy="never"',
           "-c", 'model_reasoning_effort="low"']
    if not resume:  # `exec resume` takes no sandbox flag; the session keeps the one it started with
        cmd += ["--sandbox", "read-only"]
    if model:
        cmd += ["-c", f"model={json.dumps(model)}"]
    return cmd


def opencode_command(agent: str, *, model: str | None, session: str | None, server: str | None = None) -> list[str]:
    """OpenCode for one message, sent to the chat's own OpenCode server (`server`; its own private one otherwise), with
    the studio's agent (only the studio's tools allowed) and the project config in the agent's folder. The message
    comes on stdin."""
    where = ["--server", server] if server else ["--standalone"]
    cmd = [*_head(agent), "run", "--format", "json", *where, "--agent", "openfield-chat", "--title", "OpenField chat"]
    if model:
        cmd += ["-m", model]
    if session:
        cmd += ["--session", session]
    return cmd


def _still_connecting(names: list[str], output: Any) -> bool:
    """Whether a code-mode call answered "Unknown tool" for one of the studio's own tools: in a new chat the tools reach
    OpenCode a few seconds after the first message (seen on the GPU box, Oct 25), the note tells the agent to call again,
    and the second call goes through. A name the studio does not have is still shown."""
    from .mcp_server import TOOLS  # noqa: PLC0415

    return str(output or "").startswith(f"Unknown tool '{SERVER}.") and all(n in TOOLS for n in names)


def prepare_opencode(folder: Path, studio_url: str, renders: int, budget: Path | None) -> None:
    """The OpenCode project the agent runs in: the studio's MCP server, and an agent that may use nothing but it."""
    from .mcp_server import TOOLS  # noqa: PLC0415 (only the OpenCode lane needs the tool list)

    command = [sys.executable.replace("\\", "/"), *[a.replace("\\", "/") for a in mcp_args(studio_url, renders, budget)]]
    # the timeouts make OpenCode wait for the studio's tools before the model starts (else its first calls race the
    # server's start), and let a render wait (wait_for_take answers within 110 s) run past the 5 s default
    server = {"type": "local", "command": command, "timeout": {"startup": 30000, "catalog": 30000, "execution": 180000}}
    (folder / "opencode.json").write_text(json.dumps({"$schema": "https://opencode.ai/config.json", "mcp": {
        "servers": {SERVER: server}}}, indent=1), encoding="utf-8")
    agents = folder / ".opencode" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    prompt = GUIDE.format(renders=renders) + CODE_MODE.format(tools=", ".join(sorted(TOOLS)))
    (agents / "openfield-chat.md").write_text(
        "---\ndescription: OpenField Studio's Chat room: works the studio through its tools only.\nmode: primary\n"
        "hidden: true\nsteps: 40\npermissions:\n"
        '  - { action: "*", resource: "*", effect: deny }\n'
        '  - { action: "execute", resource: "*", effect: allow }\n'
        '  - { action: "mcp", resource: "*", effect: allow }\n'
        f'  - {{ action: "{SERVER}_*", resource: "*", effect: allow }}\n'
        "---\n" + prompt, encoding="utf-8")


def short_tool(name: str) -> str:
    """A tool's name as the room shows it, whatever the lane calls it (mcp__openfield__x, openfield.x, openfield_x)."""
    for prefix in (TOOL_PREFIX, f"{SERVER}.", f"{SERVER}_", f"{SERVER}/"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def tool_result(block: Mapping[str, Any]) -> dict[str, Any]:
    """A tool's answer as the room shows it: its text (shortened), its pictures (when small enough), the takes it names.
    Content parts come in Claude's shape ({type: image, source: {data, media_type}}) or MCP's ({type: image, data, mimeType})."""
    content = block.get("content")
    parts = content if isinstance(content, list) else [{"type": "text", "text": str(content or "")}]
    texts: list[str] = []
    images: list[str] = []
    for part in parts:
        if not isinstance(part, Mapping):
            continue
        if part.get("type") == "text":
            texts.append(str(part.get("text", "")))
        elif part.get("type") == "image":
            source = part.get("source") or part
            data = source.get("data")
            mime = source.get("media_type") or source.get("mimeType") or "image/jpeg"
            if isinstance(data, str) and len(data) <= MAX_IMAGE and str(mime).startswith("image/"):
                images.append(f"data:{mime};base64,{data}")
    text = "\n".join(t for t in texts if t)
    takes = list(dict.fromkeys(TAKE_ID.findall(text)))
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT].rstrip() + "\n…"
    return {"id": block.get("tool_use_id"), "text": text, "images": images[:6], "takes": takes,
            "error": bool(block.get("is_error"))}


def explain(lane: Lane, text: str) -> str:
    """An agent's failure in plain words with what to do about it; unknown ones say only that the agent stopped."""
    low = (text or "").lower()
    if any(k in low for k in ("sign in again", "log in again", "not logged in", "please run /login", "unauthorized",
                              "(401)", " 401", "invalid api key", "authentication", "not authenticated", "login")):
        return f"{lane.label} is not signed in on this computer. Run `{lane.login}` once in a terminal, then send the message again."
    if any(k in low for k in ("usage limit", "rate limit", "quota", "(429)", " 429", "credit balance", "insufficient")):
        return f"{lane.label} has reached its usage limit for now. Wait a while, or pick another agent above."
    if "model" in low and any(k in low for k in ("not found", "unknown", "not supported", "does not exist")):
        return f"{lane.label} does not know that model. Pick another model above."
    return f"{lane.label} stopped before it finished. The next message starts it again."


# a studio tool called from OpenCode's code: tools.openfield.x(...), tools["openfield"].x(...) or tools["openfield"]["x"](...)
_SERVER_REF = rf"tools(?:\.{SERVER}|\[\s*[\"']{SERVER}[\"']\s*\])"
CALL = re.compile(_SERVER_REF + r"""(?:\.([A-Za-z_]\w*)|\[\s*["']([A-Za-z_]\w*)["']\s*\])\s*\(""")


def _calls(code: str) -> list[str]:
    """The studio tools a piece of OpenCode's code calls, in order, each once."""
    return list(dict.fromkeys(a or b for a, b in CALL.findall(code)))


def _call_input(code: str, name: str) -> dict[str, Any]:
    """The arguments of a studio tool call in OpenCode's code, best effort ({} when they are not a literal)."""
    found = re.search(_SERVER_REF + rf"""(?:\.{name}|\[\s*["']{name}["']\s*\])\s*\(\s*(\{{.*?\}})\s*\)""", code, re.S)
    if not found:
        return {}
    literal = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', found.group(1)).replace("'", '"')
    try:
        value = json.loads(literal)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


class EventLog:
    """The chat's events in order, each with a number; written from the agent's reader thread, followed from the loop."""

    def __init__(self, events: list[dict[str, Any]] | None = None, seq: int = 0):
        self.events: list[dict[str, Any]] = list(events or [])
        self.seq = max([seq, *(e.get("seq", 0) for e in self.events)])
        self.lock = threading.Lock()
        self.waiters: set[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = set()

    def emit(self, event: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self.seq += 1
            event = {"seq": self.seq, "at": round(time.time(), 3), **event}
            if event.get("kind") == "text":  # the whole text replaces its pieces
                self.events = [e for e in self.events if not (e.get("kind") == "delta" and e.get("id") == event.get("id"))]
            self.events.append(event)
            if len(self.events) > MAX_KEPT:
                del self.events[: len(self.events) - MAX_KEPT]
            waiters = list(self.waiters)
        for loop, flag in waiters:
            loop.call_soon_threadsafe(flag.set)
        return event

    def clear(self) -> None:
        with self.lock:
            self.events = []

    def after(self, since: int) -> list[dict[str, Any]]:
        with self.lock:
            return [e for e in self.events if e["seq"] > since]

    def kept(self) -> list[dict[str, Any]]:
        with self.lock:
            return [e for e in self.events if e.get("kind") != "delta"]

    async def follow(self, since: int, keepalive: float = 15.0) -> AsyncIterator[dict[str, Any] | None]:
        """Every event after `since`, then each new one as it comes; None now and then keeps the connection open."""
        flag = asyncio.Event()
        entry = (asyncio.get_running_loop(), flag)
        with self.lock:
            self.waiters.add(entry)
        try:
            while True:
                batch = self.after(since)
                if batch:
                    for event in batch:
                        since = event["seq"]
                        yield event
                    continue
                flag.clear()
                if self.after(since):
                    continue
                try:
                    await asyncio.wait_for(flag.wait(), keepalive)
                except asyncio.TimeoutError:
                    yield None
        finally:
            with self.lock:
                self.waiters.discard(entry)


class Chat:
    """The studio's one chat: the agent process, its events, and what the room may ask of it."""

    def __init__(self, data_dir: Path, host: str, env: Mapping[str, str] | None = None):
        self.env = dict(os.environ if env is None else env)
        self.host = host
        self.folder = data_dir / "chat"
        self.saved = self.folder / "chat.json"
        self.budget = self.folder / "budget.json"  # renders this chat started, kept across turns, restarts and lanes
        self.lock = threading.RLock()
        self.proc: subprocess.Popen[bytes] | None = None
        self.state = "idle"  # idle | starting | busy | stopping
        self.session: str | None = None
        self.model: str | None = None  # the model the agent reported (Claude) or the person picked
        self.choice: str | None = None  # the model the person picked in the room (None: the agent's default)
        self.lane: str | None = None  # the lane the person picked (None: the configured default)
        self.stderr: list[str] = []
        self.turn_started = 0.0
        self._message = ""  # the agent message the stream is in
        self._texts: dict[str, int] = {}  # text blocks seen per message, in the stream and in the whole messages
        self._finals: dict[str, int] = {}
        self._turn_error: str | None = None  # what a per-turn agent reported going wrong this turn
        self._seen_tools: set[str] = set()
        self._run = 0  # one per message sent: Codex numbers its items per run, so the room's ids carry the run too
        # the chat's own OpenCode server: started with the first OpenCode message, ended with the chat; its password is
        # random and lives only here and in the environment of the processes that talk to it
        self._oc_server: subprocess.Popen[bytes] | None = None
        self._oc_url: str | None = None
        self._oc_token: str | None = None
        self._oc_warm = False  # a turn has run on this server: its tools are connected and its sessions resume
        events, saved = self._load()
        self.session = saved.get("session")
        self.lane = saved.get("lane") if saved.get("lane") in LANES else None
        self.choice = saved.get("choice") or None
        self.log = EventLog(events)

    # -- what the room sees ------------------------------------------------------------------------------------------
    def config(self) -> ChatConfig:
        return ChatConfig.read(self.host, self.env, lane=self.lane)

    def used(self) -> int:
        try:
            return max(0, int(json.loads(self.budget.read_text(encoding="utf-8")).get("used", 0)))
        except (OSError, ValueError, TypeError, AttributeError):
            return 0

    def info(self) -> dict[str, Any]:
        cfg = self.config()
        why = cfg.unavailable()
        lane = LANES[cfg.lane]
        lanes = [{"id": lid, "label": LANES[lid].label, "installed": bool(path), "open_weights": LANES[lid].open_weights,
                  "models": [{"value": v, "label": label} for v, label in LANES[lid].models]} for lid, path in cfg.agents]
        return {"enabled": why is None, "code": why[0] if why else None, "message": why[1] if why else None,
                "lane": {"id": lane.id, "label": lane.label, "open_weights": lane.open_weights}, "lanes": lanes,
                "model": self.model or self.choice or cfg.model, "choice": self.choice or "", "renders": cfg.renders,
                "renders_left": max(cfg.renders - self.used(), 0), "state": self.state, "session": self.session,
                "seq": self.log.seq}

    @staticmethod
    def guard(client_host: str | None) -> None:
        if (client_host or "") not in LOOPBACK_CLIENTS:
            raise ChatError(403, "chat_local_only", "The Chat room answers this computer only.")

    # -- what the room asks --------------------------------------------------------------------------------------------
    def choose(self, lane: str | None = None, model: str | None = None) -> dict[str, Any]:
        """Pick the agent and its model. Another agent is another conversation; another model keeps this one."""
        with self.lock:
            if self.state != "idle":
                raise ChatError(409, "chat_busy", "The agent is still answering. Wait for it, or press Stop.")
            if lane is not None and lane not in LANES:
                raise ChatError(422, "unknown_agent", "Pick OpenCode, Claude Code or Codex.")
            if model is not None and len(model) > 120:
                raise ChatError(422, "unknown_model", "That model name is too long.")
            current = self.config().lane
            if lane is not None and lane != current:
                self._kill()
                self._stop_server()
                self.session, self.model, self.choice, self.lane = None, None, None, lane
                self.budget.unlink(missing_ok=True)
                self.log.clear()
                self.log.emit({"kind": "reset"})
            if model is not None and (model or None) != self.choice:
                self.choice = model or None
                self.model = None
                if not LANES[self.config().lane].per_turn:
                    self._kill()  # the long-lived agent starts again on the next message, resuming with the new model
            self._save()
        return self.info()

    def send(self, text: str, studio_url: str) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise ChatError(422, "empty_message", "Write something to send.")
        if len(text) > MAX_MESSAGE:
            raise ChatError(422, "message_too_long", f"A message holds up to {MAX_MESSAGE} characters.")
        cfg = self.config()
        why = cfg.unavailable()
        if why:
            raise ChatError(409, f"chat_{why[0]}", why[1])
        with self.lock:
            if self.state in {"busy", "starting", "stopping"}:
                raise ChatError(409, "chat_busy", "The agent is still answering. Wait for it, or press Stop.")
            if LANES[cfg.lane].per_turn:
                earlier = self._transcript()  # what was said before this message (OpenCode is told it each turn)
                event = self.log.emit({"kind": "user", "id": uuid.uuid4().hex[:12], "text": text})
                self._start_turn(cfg, studio_url, text, earlier)
            else:
                if self.proc is None or self.proc.poll() is not None:
                    self._start(cfg, studio_url)
                event = self.log.emit({"kind": "user", "id": uuid.uuid4().hex[:12], "text": text})
                line = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]},
                        "parent_tool_use_id": None, "session_id": self.session or ""}
                try:
                    assert self.proc is not None and self.proc.stdin is not None
                    self.proc.stdin.write((json.dumps(line, ensure_ascii=False) + "\n").encode("utf-8"))
                    self.proc.stdin.flush()
                except (OSError, AssertionError, ValueError):
                    self._ended("The agent could not take the message: it stopped. Send it again to start a new one.")
                    raise ChatError(502, "chat_agent_gone", "The agent stopped before it read the message. Send it again.") from None
            self.state = "busy"
            self.turn_started = time.monotonic()
            self.log.emit({"kind": "status", "state": "busy"})
            return {"seq": event["seq"]}

    def stop(self) -> dict[str, Any]:
        with self.lock:
            if self.state not in {"busy", "starting"} or self.proc is None:
                return {"state": self.state}
            self.state = "stopping"
            self.log.emit({"kind": "status", "state": "stopping"})
            proc = self.proc
            if LANES[self.config().lane].per_turn:  # a turn of its own: ending the process ends the turn
                try:
                    proc.terminate()
                except OSError:
                    pass
                return {"state": "stopping"}
            request = {"type": "control_request", "request_id": uuid.uuid4().hex, "request": {"subtype": "interrupt"}}
            try:
                assert proc.stdin is not None
                proc.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
                proc.stdin.flush()
            except (OSError, AssertionError, ValueError):
                pass
        threading.Timer(STOP_GRACE_S, self._stop_overdue, args=(proc,)).start()
        return {"state": "stopping"}

    def reset(self) -> dict[str, Any]:
        with self.lock:
            self._kill()
            self._stop_server()
            self.session = None
            self.model = None
            self.state = "idle"
            self.log.clear()
            self.saved.unlink(missing_ok=True)
            self.budget.unlink(missing_ok=True)
            if self.lane or self.choice:
                self._save()  # the agent and model the person picked stay
        self.log.emit({"kind": "reset"})
        return {"state": "idle"}

    def close(self) -> None:
        with self.lock:
            self._kill()
            self._stop_server()

    # -- the agent process ---------------------------------------------------------------------------------------------
    def _popen(self, cmd: list[str], workdir: Path, extra: Mapping[str, str] | None = None) -> subprocess.Popen[bytes]:
        env = {**self.env, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PWD": str(workdir), **(extra or {})}  # PWD: OpenCode reads it first
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        return subprocess.Popen(cmd, cwd=workdir, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, creationflags=flags)

    def _start(self, cfg: ChatConfig, studio_url: str) -> None:
        workdir = self.folder / "agent"  # an empty room of its own: no project settings, no files to reach
        workdir.mkdir(parents=True, exist_ok=True)
        config_file = self.folder / "mcp.json"
        config_file.write_text(json.dumps(mcp_config(studio_url, cfg.renders, self.budget), indent=1), encoding="utf-8")
        guide_file = self.folder / "guide.md"
        guide_file.write_text(GUIDE.format(renders=cfg.renders), encoding="utf-8")
        assert cfg.agent is not None
        cmd = agent_command(cfg.agent, mcp_config=config_file, guide=guide_file, model=self.choice or cfg.model,
                            resume=self.session)
        self.state = "starting"
        self.stderr = []
        self.log.emit({"kind": "status", "state": "starting"})
        try:
            self.proc = self._popen(cmd, workdir)
        except OSError as error:
            self.state = "idle"
            self.log.emit({"kind": "error", "text": f"The agent did not start: {error}."})
            raise ChatError(502, "chat_agent_failed", f"The agent did not start: {error}.") from None
        proc = self.proc
        threading.Thread(target=self._read, args=(proc,), name="chat-agent-out", daemon=True).start()
        threading.Thread(target=self._read_errors, args=(proc,), name="chat-agent-err", daemon=True).start()

    def _transcript(self, limit: int = 9000) -> str:
        """The conversation so far as plain lines, newest kept: what the person said, what the agent said, the tools it
        used and what they answered (with the take ids), for an agent that starts each turn afresh."""
        lines: list[str] = []
        for event in self.log.kept():
            kind = event.get("kind")
            if kind == "user":
                lines.append(f"Person: {event.get('text', '')}")
            elif kind == "text":
                lines.append(f"You: {event.get('text', '')[:1500]}")
            elif kind == "tool":
                lines.append(f"(you called {event.get('name')} {json.dumps(event.get('input') or {}, ensure_ascii=False)[:300]})")
            elif kind == "result":
                said = " ".join(str(event.get("text") or "").split())[:400]
                takes = f" takes: {', '.join(event.get('takes') or [])}" if event.get("takes") else ""
                lines.append(f"(it answered{' with an error' if event.get('error') else ''}: {said}{takes})")
        text = "\n".join(lines)
        return text[-limit:] if len(text) > limit else text

    def _start_turn(self, cfg: ChatConfig, studio_url: str, text: str, earlier: str = "") -> None:
        """One message to a per-turn agent (Codex, OpenCode): its process runs the turn and resumes the session."""
        lane = LANES[cfg.lane]
        workdir = self.folder / f"agent-{lane.id}"
        workdir.mkdir(parents=True, exist_ok=True)
        assert cfg.agent is not None
        model = self.choice or cfg.model
        if lane.id == "codex":
            message = text if self.session else f"{GUIDE.format(renders=cfg.renders)}\n---\n\n{text}"  # its brief, once
            cmd = codex_command(cfg.agent, studio_url=studio_url, renders=cfg.renders, budget=self.budget, model=model,
                                resume=self.session)
        else:
            prepare_opencode(workdir, studio_url, cfg.renders, self.budget)
            self._opencode_server(cfg.agent, workdir)
            # on a server that has run a turn the session resumes with its tools connected; a new server (the first
            # message, or after a restart) starts a fresh session and is told the conversation so far, because a
            # session resumed on a fresh server comes back without them (bip-boop replays OpenCode the same way)
            resume = self.session if self._oc_warm else None
            message = text if resume or not earlier else (
                f"The conversation so far, for context:\n{earlier}\n\nThe person's new message: {text}")
            message = f"{OPENCODE_NOTE}\n\n{message}"
            cmd = opencode_command(cfg.agent, model=model, session=resume, server=self._oc_url)
        self.stderr = []
        self._turn_error = None
        self._seen_tools = set()
        self._run += 1
        try:
            proc = self._popen(cmd, workdir, {"OPENCODE_SERVER_PASSWORD": self._oc_token} if lane.id == "opencode" and self._oc_token else None)
            assert proc.stdin is not None
            proc.stdin.write(message.encode("utf-8"))
            proc.stdin.close()
        except (OSError, AssertionError, ValueError) as error:
            self.log.emit({"kind": "error", "text": f"The agent did not start: {error}."})
            raise ChatError(502, "chat_agent_failed", f"{lane.label} did not start: {error}.") from None
        self.proc = proc
        if model:
            self.model = model
        threading.Thread(target=self._read_turn, args=(proc, lane), name="chat-agent-out", daemon=True).start()
        threading.Thread(target=self._read_errors, args=(proc,), name="chat-agent-err", daemon=True).start()

    def _opencode_server(self, agent: str, workdir: Path, wait: float = 30.0) -> None:
        """Start the chat's OpenCode server once (loopback, a free port, a random password) and wait until it listens."""
        if self._oc_server is not None and self._oc_server.poll() is None:
            return
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        token = secrets.token_urlsafe(24)
        server = self._popen([*_head(agent), "serve", "--hostname", "127.0.0.1", "--port", str(port)], workdir,
                             {"OPENCODE_SERVER_PASSWORD": token})
        server.stdin.close()
        ready = threading.Event()

        def watch() -> None:  # the server says when it listens; everything it prints after that is drained, not kept
            for raw in server.stdout:
                if b"listening" in raw:
                    ready.set()
            ready.set()

        threading.Thread(target=watch, name="chat-opencode-serve", daemon=True).start()
        threading.Thread(target=lambda: [None for _ in server.stderr], name="chat-opencode-serve-err", daemon=True).start()
        if not ready.wait(wait) or server.poll() is not None:
            try:
                server.kill()
            except OSError:
                pass
            raise ChatError(502, "chat_agent_failed", "OpenCode did not start its server. Is it installed and signed in?")
        self._oc_server, self._oc_url, self._oc_token, self._oc_warm = server, f"http://127.0.0.1:{port}", token, False

    def _stop_server(self) -> None:
        server, self._oc_server, self._oc_url, self._oc_token, self._oc_warm = self._oc_server, None, None, None, False
        if server is not None and server.poll() is None:
            try:
                server.terminate()
                server.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    server.kill()
                except OSError:
                    pass

    def _kill(self) -> None:
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass

    def _stop_overdue(self, proc: subprocess.Popen[bytes]) -> None:
        with self.lock:
            if self.proc is proc and self.state == "stopping":
                self._kill()
                self._ended("Stopped. The next message starts the agent again, with this conversation.")

    def _ended(self, why: str) -> None:
        self.state = "idle"
        self.log.emit({"kind": "notice", "text": why})
        self.log.emit({"kind": "status", "state": "idle"})
        self._save()

    def _read_errors(self, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stderr is not None
        for raw in proc.stderr:
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                self.stderr = [*self.stderr[-30:], line]

    def _lines(self, proc: subprocess.Popen[bytes]):
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("{"):
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue

    def _read(self, proc: subprocess.Popen[bytes]) -> None:
        for event in self._lines(proc):
            try:
                self._on_event(event)
            except Exception as error:  # an event the room does not understand must never end the chat
                self.log.emit({"kind": "notice", "text": f"An agent event was skipped ({type(error).__name__})."})
        proc.wait()
        with self.lock:
            if self.proc is not proc:
                return  # reset or stopped on purpose
            self.proc = None
            if self.state != "idle":
                self._ended(explain(LANE, " ".join(self.stderr[-6:])) if self.stderr else
                            "The agent stopped. The next message starts it again.")

    def _read_turn(self, proc: subprocess.Popen[bytes], lane: Lane) -> None:
        handle = self._on_codex if lane.id == "codex" else self._on_opencode
        for event in self._lines(proc):
            try:
                handle(event)
            except Exception as error:  # an event the room does not understand must never end the chat
                self.log.emit({"kind": "notice", "text": f"An agent event was skipped ({type(error).__name__})."})
        code = proc.wait()
        with self.lock:
            if self.proc is not proc:
                return  # reset or switched on purpose
            self.proc = None
            stopped = self.state == "stopping"
            problem = None if stopped else (self._turn_error or (" ".join(self.stderr[-6:]) if code not in (0, None) else None))
            if lane.id == "opencode" and not problem and self._oc_server is not None:
                self._oc_warm = True
            self.state = "idle"
            self.log.emit({"kind": "turn", "ms": int((time.monotonic() - self.turn_started) * 1000), "turns": 1,
                           "error": bool(problem), "stopped": stopped, "text": explain(lane, problem) if problem else None})
            if stopped:
                self.log.emit({"kind": "notice", "text": "Stopped. Renders it had already started keep going: find them in Takes."})
            self.log.emit({"kind": "status", "state": "idle"})
            self._save()

    def _ready_once(self, session: str | None, model: str | None) -> None:
        if session and session != self.session:
            self.session = session
            self.log.emit({"kind": "ready", "model": model, "tools": None})
        if self.state == "starting":
            self.state = "busy"

    def _on_codex(self, event: Mapping[str, Any]) -> None:
        kind = event.get("type")
        if kind == "thread.started":
            self._ready_once(event.get("thread_id"), self.choice or "Codex")
        elif kind in {"item.started", "item.updated", "item.completed"}:
            item = event.get("item") or {}
            what = item.get("type")
            # Codex numbers its items per run (item_0, item_1...) and each message is a run: the run number keeps a later
            # turn's call or answer from folding into an earlier card with the same id
            iid = f"r{self._run}.{item.get('id') or uuid.uuid4().hex[:8]}"
            if what == "agent_message" and kind == "item.completed" and item.get("text"):
                self.log.emit({"kind": "text", "id": f"cx.{iid}", "text": str(item["text"])})
            elif what == "mcp_tool_call":
                if iid not in self._seen_tools:
                    self._seen_tools.add(iid)
                    self.log.emit({"kind": "tool", "id": iid, "name": short_tool(str(item.get("tool") or "tool")),
                                   "input": item.get("arguments") if isinstance(item.get("arguments"), dict) else {}})
                if kind == "item.completed":
                    result = item.get("result") if isinstance(item.get("result"), dict) else {}
                    error = item.get("error") if isinstance(item.get("error"), dict) else {}
                    content = result.get("content") or [{"type": "text", "text": str(error.get("message") or "")}]
                    failed = item.get("status") == "failed" or bool(error) or bool(result.get("isError"))
                    self.log.emit({"kind": "result", **tool_result({"tool_use_id": iid, "content": content, "is_error": failed})})
            elif what == "command_execution" and kind == "item.completed":  # its sandbox is read-only and its folder empty
                self.log.emit({"kind": "tool", "id": iid, "name": "shell", "input": {"command": str(item.get("command") or "")}})
                self.log.emit({"kind": "result", **tool_result({"tool_use_id": iid, "content": str(item.get("aggregated_output") or "")[:2000],
                                                                "is_error": item.get("exit_code") not in (0, None)})})
        elif kind == "turn.failed":
            self._turn_error = str((event.get("error") or {}).get("message") or "the turn failed")
        elif kind == "error":
            message = str(event.get("message") or "")
            if message and not message.startswith("Reconnecting"):
                self._turn_error = message

    def _on_opencode(self, event: Mapping[str, Any]) -> None:
        part = event.get("part") if isinstance(event.get("part"), Mapping) else {}
        self._ready_once(event.get("sessionID") or part.get("sessionID"), self.choice or "OpenCode")
        kind = event.get("type")
        if kind == "text" and part.get("text"):
            self.log.emit({"kind": "text", "id": f"oc.{part.get('id') or uuid.uuid4().hex[:8]}", "text": str(part["text"])})
        elif kind == "tool_use":
            state = part.get("state") if isinstance(part.get("state"), Mapping) else {}
            tool = str(part.get("tool") or "tool")
            pid = str(part.get("id") or uuid.uuid4().hex[:8])
            failed = state.get("status") == "error"
            output = state.get("error") if failed else state.get("output")
            # the part arrives again as the call runs (pending, running, completed): its answer is reported once, at the end
            finished = state.get("status") in ("completed", "error") or ("status" not in state and output is not None)
            if tool == "execute":  # OpenCode's code mode: the studio's tools are called inside it
                code = str((state.get("input") or {}).get("code") or "")
                names = _calls(code)
                if not names:  # a look at the tool catalog, no studio call: nothing for the room to show
                    return
                if _still_connecting(names, output):  # the call never reached the studio; the agent tries again
                    return
                for i, name in enumerate(names):
                    self.log.emit({"kind": "tool", "id": f"{pid}.{i}", "name": name, "input": _call_input(code, name)})
                if finished:
                    self.log.emit({"kind": "result", **tool_result({"tool_use_id": f"{pid}.0", "content": str(output or ""),
                                                                    "is_error": failed or "Unable to execute" in str(output or "")})})
            else:  # anything outside the studio is refused by the agent's permissions: shown, so nothing is hidden
                self.log.emit({"kind": "tool", "id": pid, "name": tool, "input": state.get("input") if isinstance(state.get("input"), dict) else {}})
                if finished:
                    self.log.emit({"kind": "result", **tool_result({"tool_use_id": pid, "content": str(output or ""), "is_error": failed})})
        elif kind == "error":
            error = event.get("error") if isinstance(event.get("error"), Mapping) else {}
            data = error.get("data") if isinstance(error.get("data"), Mapping) else {}
            self._turn_error = str(error.get("message") or data.get("message") or error.get("name") or "the agent reported an error")

    def _on_event(self, event: Mapping[str, Any]) -> None:
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            first = self.session is None or event.get("model") != self.model
            self.session = event.get("session_id") or self.session
            self.model = event.get("model") or self.model
            if first:
                tools = [t for t in event.get("tools", []) if str(t).startswith(TOOL_PREFIX)]
                self.log.emit({"kind": "ready", "model": self.model, "tools": len(tools)})
            if self.state == "starting":
                self.state = "busy"
        elif kind == "stream_event":
            self._on_stream(event.get("event") or {})
        elif kind == "assistant":
            message = event.get("message") or {}
            mid = str(message.get("id") or "m")
            for block in message.get("content") or []:
                if block.get("type") == "text" and block.get("text"):
                    n = self._finals.get(mid, 0) + 1
                    self._finals[mid] = n
                    self.log.emit({"kind": "text", "id": f"{mid}.{n}", "text": block["text"]})
                elif block.get("type") == "tool_use":
                    self.log.emit({"kind": "tool", "id": block.get("id"), "name": short_tool(str(block.get("name", ""))),
                                   "input": block.get("input") or {}})
        elif kind == "user":
            message = event.get("message") or {}
            content = message.get("content")
            for block in content if isinstance(content, list) else []:
                if isinstance(block, Mapping) and block.get("type") == "tool_result":
                    self.log.emit({"kind": "result", **tool_result(block)})
        elif kind == "result":
            with self.lock:
                stopped = self.state == "stopping"
                self.state = "idle"
            failed = bool(event.get("is_error")) and not stopped
            self.log.emit({"kind": "turn", "ms": event.get("duration_ms"), "turns": event.get("num_turns"),
                           "error": failed, "stopped": stopped,
                           "text": explain(LANE, str(event.get("result") or "")) if failed else None})
            if stopped:
                self.log.emit({"kind": "notice", "text": "Stopped. Renders it had already started keep going: find them in Takes."})
            self.log.emit({"kind": "status", "state": "idle"})
            self._texts.clear()
            self._finals.clear()
            self._save()

    def _on_stream(self, inner: Mapping[str, Any]) -> None:
        kind = inner.get("type")
        if kind == "message_start":
            self._message = str((inner.get("message") or {}).get("id") or "m")
        elif kind == "content_block_start" and (inner.get("content_block") or {}).get("type") == "text":
            self._texts[self._message] = self._texts.get(self._message, 0) + 1
        elif kind == "content_block_delta":
            delta = inner.get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                n = max(1, self._texts.get(self._message, 1))
                self.log.emit({"kind": "delta", "id": f"{self._message}.{n}", "text": delta["text"]})

    # -- the saved conversation ------------------------------------------------------------------------------------------
    def _load(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        try:
            data = json.loads(self.saved.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return [], {}
        events = [e for e in data.get("events", []) if isinstance(e, dict) and isinstance(e.get("seq"), int)]
        saved = {k: data.get(k) for k in ("session", "lane", "choice") if isinstance(data.get(k), str)}
        return events[-MAX_KEPT:], saved

    def _save(self) -> None:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self.saved.with_suffix(".tmp")
            tmp.write_text(json.dumps({"session": self.session, "lane": self.lane, "choice": self.choice,
                                       "events": self.log.kept()}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.saved)
        except OSError:
            pass
