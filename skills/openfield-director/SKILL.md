---
name: openfield-director
description: Direct a shot in OpenField Studio through its MCP server. Plan first, approve the stills, read the receipt. For Claude Code, Codex, OpenCode or any agent with the openfield MCP tools.
---

# Direct a shot in OpenField Studio

OpenField Studio is a film studio on open-weights models in ComfyUI. Its MCP server (`openfield mcp`) gives you 24 tools: plan and render shots, approve stills, edit takes, re-shoot, extend, dub, upscale, cut a movie, and read every take's receipt. Every render on a live backend spends GPU time on the owner's account, so you plan before you render and you look before you approve.

## Before you start

1. The studio must be running: `openfield serve` (a GPU box or Comfy Cloud renders for real) or `openfield demo` (recorded takes under Replay, no key, no GPU).
2. The server must be on your client. Claude Code: `claude mcp add openfield -- openfield mcp --url http://127.0.0.1:8877`. Other clients: see `docs/MCP.md`. `--url` defaults to `$OPENFIELD_URL`.
3. Call `studio_status` first. It says where renders go (Replay or a live backend), whether the backend is healthy, and how many moves, effects, transitions and edits are tested. On Replay, only recorded takes play (`list_takes`, `replay_take`); nothing new renders, and the tools say so.

## A shot, in order

1. `list_options`: pick a camera move whose `tested` flag is set unless the person asks for an untested one, and say which it is.
2. Write the shot as two parts. The **subject** is the first frame: who or what, where, the light, the weather, the lens feel. The **action** is what visibly happens during the shot and the state it ends in ("she lifts the lantern and holds it high"). A spoken **line** goes in `line`, in quotes, with its `delivery`. Sound goes in `audio`.
3. `plan_shot` with the same arguments: it compiles the exact prompts, counts the stills and passes, measures the time this install needs, and refuses impossible combinations (an action or a line on a move that is played backwards, a person who is not in the Cast). Read its notes and fix the shot before rendering.
4. `direct_shot`. People come only from the Cast (`list_cast`, `create_character`, `add_character`), where consent is recorded; a face from anywhere else is refused.
5. `wait_for_take`. While the take waits for approval it returns every still with its role and face-check score. Look at each one: the person is the same person, the setting is the one you asked for, nothing is cut off. `approve_stills` approves, or re-rolls the stills you name by index. Do not pass `auto_approve` unless the person asked for it.
6. `wait_for_take` again. A finished take returns a strip of six frames across the video. Check that the action happened, the camera moved the way the move says, and nothing morphed. If it did not hold, say so plainly and try once more with a changed subject or action, not the same words.
7. `get_receipt`: the model files and licences, the open-weights audit, the workflow hashes, the seed and the recipe link. Report the take id, the receipt's digest and the GPU seconds and cost to the person. The receipt is the proof; the clip alone is not.

## Afterwards

- `edit_take` (face or person from the Cast, outfit, remove, relight), `shots_board` (nine setups of one still), `transition` (a rendered bridge between two takes), `extend_take`, `dub_take`, `upscale_take`, `reshoot_video` (Wan Animate 2) and `make_movie` all start from takes that exist. Each spends renders; say what it will cost before you run it.
- `save_take` writes a video where the person says, nowhere else. `export_vertical` makes the 9:16 crop.
- A session has a render budget (`--max-renders`, default 20). When it is spent, stop and report; do not look for a way round it.

## Rules

- Plan at Draft when exploring; render Standard or Fine when the shot is right.
- Never claim a shot worked without looking at the strip. Never invent a take: on Replay, play a recorded one and say that is what it is.
- Say "open weights", not "open source", about models; the code is MIT.
- Report in plain words: what was asked, what was planned, what rendered, what held, what did not, and the receipt.
