# Direct OpenField Studio from Claude (MCP)

`openfield mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server. Claude Code, Claude Desktop or any MCP client can drive a running studio with it: plan and direct shots, check stills before video, approve or re-roll, then edit, add transitions, extend, dub or upscale, and cut the takes into one movie. It adds no dependency, speaks JSON-RPC on stdin and stdout, and uses the same HTTP API as the web app. Every render goes through the same pipeline, approval gate, open-weights audit and receipts as one started from the browser. Replay still refuses a recipe that was never rendered.

## Set it up

1. Install and start a studio (see [the README](../README.md#run-it)). `openfield serve` with a GPU box or Comfy Cloud renders for real. `openfield demo` serves recorded takes under Replay, with no key and no GPU. The model replays them with `replay_take` or cuts them into a movie, all free.
2. Add the server to your client.

   Claude Code, from the repository (the repo's `.mcp.json` does the same, and Claude Code asks once before starting a project server):

   ```bash
   claude mcp add openfield -- openfield mcp --url http://127.0.0.1:8877
   ```

   Claude Desktop, in `claude_desktop_config.json` (use the full path of `openfield` from your environment, for example `.venv/Scripts/openfield.exe` on Windows or `.venv/bin/openfield` elsewhere):

   ```json
   {"mcpServers": {"openfield": {"command": "/path/to/.venv/bin/openfield", "args": ["mcp", "--url", "http://127.0.0.1:8877"]}}}
   ```

   `--url` defaults to `$OPENFIELD_URL`, else `http://127.0.0.1:<OPENFIELD_PORT or 8877>`.
3. Ask for a shot or a movie. The prompt *make_a_movie* (in Claude Code: `/mcp__openfield__make_a_movie`) walks the path: shot list, characters, plans, stills, checks, transitions, the cut.

## Inside the app: the Chat room

The **Chat** room also runs this server, on one of three lanes. **OpenCode** with an open-weights model (its own default, DeepSeek V4.1 Flash, Kimi K2.7, Qwen 3.8 Max or MiniMax M3.1 Flash, through the person's OpenCode providers) is the installed default. **Claude Code** uses the person's Claude plan. **Codex** uses the person's ChatGPT plan. The chat bar has Agent and Model pickers. Agent starts a new chat, Model keeps the conversation. Every lane gets `openfield mcp` as its only MCP server, with no shell, file or web tools, and none of the person's own MCP servers or settings.

Claude Code runs headless (`claude -p`, stream-json in and out) with `--strict-mcp-config`, `--tools ""` and `--setting-sources local`, in its own folder. Codex runs `exec ... --sandbox read-only` in an empty folder, with its `mcp_servers` table replaced. OpenCode runs in a private OpenCode server the chat starts (loopback, a random password in memory), and its agent may use only the studio's tools. OpenCode 2 reaches MCP tools from code (its `execute` tool). Its prompt names every studio tool and shows the call shape `await tools.openfield.<tool>({...})`, for example `await tools.openfield.studio_status({})` or `await tools.openfield.plan_shot({subject: "...", move: "dolly_in"})`. An "Unknown tool" answer while the server connects is retried.

A chat's render cap (`OPENFIELD_CHAT_RENDERS`, default 6) is passed as `--max-renders` and kept in a budget file (`--budget-file`), so it holds across turns and restarts. Another agent or New chat gets a fresh cap. Failures say what to do in plain words (`explain()` in `openfield/chat.py`). Stop lets started renders finish. The room answers loopback clients only and is off when the studio is published to other computers. Settings: `OPENFIELD_CHAT` (auto, on or off), `OPENFIELD_CHAT_AGENT` (opencode, claude or codex), `OPENFIELD_CHAT_MODEL`, `OPENFIELD_CHAT_RENDERS`.

## What the model gets

On connect, the server sends instructions: check where renders go, plan before rendering, write a shot as a subject (the first frame) and an action (what visibly happens, with its end state). Approve stills only after looking, and check every finished take before building on it. `openfield://guide/prompting` holds the longer guide, `openfield://catalog` the compact catalog.

Three tools return pictures (`wait_for_take`, and `make_movie` and `export_vertical` once their take is done), so the model works from renders and status fields. The studio makes the previews itself, `/api/takes/{id}/strip.jpg` and `?w=` on a still, so a slow client gets ~30 KB instead of the full PNG or MP4:

- `wait_for_take` returns every still as an image, with its role and face-check score, while a take waits for approval.
- On a finished take, `wait_for_take` returns a strip of six frames across the video. That shows whether the action happened, the camera moved and nothing morphed. Portrait candidates come back as images too.

| Tool | What it does |
|---|---|
| `studio_status` | Where renders go (Replay or live backend), its health, and how many moves, effects, transitions and edits are tested |
| `read_guide` | The prompting guide: how to write a shot for these models (subject, action, moves, sound and speech, effects, transitions, edits) and how to check a take |
| `list_options` | Compact catalog: moves with mode and tested flag, effects, look, dialogue, edits, transitions, angles, extend and upscale |
| `list_cast` | Cast: characters, products and places, with consent for each |
| `create_character` | Paint 1-4 portrait candidates of a fictional character from words |
| `add_character` | Keep a candidate in the Cast, or add photos from disk with consent |
| `plan_shot` | Compile a shot without rendering: exact video and still prompts, still and pass counts, notes, measured time |
| `direct_shot` | Render a shot. Stills, then video after approval. Can start from a disk image |
| `wait_for_take` | Wait for a take. Shows stills to approve, the finished strip, or the error |
| `approve_stills` | Approve stills, or re-roll some by index |
| `edit_take` | Edit with words: swap a face or person (Cast), change an outfit, remove something, relight |
| `shots_board` | Nine camera setups of one still, face kept |
| `transition` | Rendered bridge from one take's last frame to another's first |
| `extend_take` | Continue a take from its last frame |
| `dub_take` | Re-render a talking take speaking a translated line |
| `upscale_take` | Real-ESRGAN x4 to 2K or 4K |
| `reshoot_video` | Wan Animate 2: a new character in a filmed clip, or a new face only |
| `make_movie` | Join 2-8 takes into one movie, crossfades, matched loudness |
| `export_vertical` | 9:16 crop for Reels, Shorts and TikTok |
| `list_takes` | Recent takes, or recorded takes Replay can play |
| `replay_take` | On Replay, play a recorded take as a new take (free), to wait on, cut or save |
| `get_receipt` | Receipt: checksum, model files and licences, audit, graph hashes, recipe link |
| `save_take` | Download a take's video to a path on this computer |
| `cancel_take` | Stop a take |

Prompts: `make_a_movie`, `direct_a_shot`, `check_a_take`.

## A skill for coding agents

`skills/openfield-director/SKILL.md` teaches a coding agent the order of a good shot through these tools: status first, plan before rendering, look at the stills before approving, read the receipt, stop at the render budget. Claude Code reads it as a skill once the folder is copied to `~/.claude/skills/openfield-director/` (or to a project's `.claude/skills/`); Codex and OpenCode read it as plain instructions when you point them at the file.

## What it will and will not do

- On a live backend, every render spends GPU time on the owner's account. The model is told to plan first and explore at Draft. The approval gate stays on unless the model passes `auto_approve`.
- Faces and people come only from the Cast, where consent is recorded. Swaps refuse anything else.
- The server reads the local files you name (a Cast photo, a first frame, a clip to re-shoot) and writes only where `save_take` is told. It sends them to the studio at `--url`, nowhere else.
- Errors come back as tool results the model can read ("Replay plays recorded takes only…", "this take is not waiting for approval"), with the next step, not as a crashed server.
- A session has a hard render budget (`--max-renders`, default 20, 0 means plan and review only). A render past it is refused before it starts.
- Take ids, cast ids and take paths are checked against strict patterns, and every URL segment is quoted, so a tool call cannot reach another route. Network paths are refused. A file over the upload limit is refused before it is read. `save_take` writes only a file of the same type.
- For a headless run, give the client only these tools: `claude -p ... --mcp-config mcp.json --strict-mcp-config --allowedTools mcp__openfield --disallowedTools Bash PowerShell`. The server never runs a shell.

## Checked

`tests/test_mcp_server.py` runs the protocol (version negotiation, each tool's schema, errors, prompts, resources), the argument checks, a whole take on the fake stack (plan, direct, stills as images, approve, strip, receipt, saved video) and a two-take movie. It starts `openfield mcp` as a subprocess to check stdio framing.

Two headless Claude Code sessions (`claude -p` with `--mcp-config`) used the server. One ran against the Replay studio, called `studio_status` and `wait_for_take`, and read a recorded transition from the strip. The other used a studio on a rented RTX 5090 and made a 17.5-second, three-shot film with sound: it planned three shots with `plan_shot`, looked at every still before approving, re-rolled three, re-rendered two, bridged two takes and joined them with `make_movie`. The full account is in [docs/EVIDENCE.md](EVIDENCE.md).
