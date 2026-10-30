# Submission pack

Deadline Fri Oct 30 2026, 09:00 PT. One submission per person.

## Category

**Open Weights Only.** Every render runs through an open-weights check first: each node against the official templates and each model file against the registry. Partner nodes and paid APIs are refused, and every take's receipt records the result.

**LTX VFX bonus.** LTX 2.5 makes every shot and its sound: the camera moves, 15 changes on camera (fire, gold, ice, ruin and more; 15 of 15 hold), weather and light, spoken lines in any language, bridges between two takes (1 of 4 styles hold, push through), loops and extensions.

## The form, field by field

| Field | Answer |
|---|---|
| Project name | OpenField Studio |
| Description (100 characters) | Direct camera moves with open-weights models in ComfyUI. Every take keeps a receipt you can check. |
| Categories | Open Weights Only; VFX Workflow Built with LTX. Most Viral once the post is up. |
| Which parts of ComfyUI did you use? | The Comfy SDK: every render goes through `comfy-sdk` (`openfield/backends/sdk.py`), with Comfy's own workflow templates and no custom nodes. Not Comfy Cloud: no take was rendered there (a key passed the connection check on October 22). `openfield mcp` is our own MCP server for agents, not Comfy's. |
| Is your stack fully open? | Yes. Every model is open weights, and the app refuses partner nodes and paid APIs before each render. The code and `comfy-sdk` are MIT. Qwen-Image 2.1 is under the Qwen Research License (non-commercial), named below. |
| Models | LTX 2.5 (video and sound), Qwen-Image 2.1 (stills and edits, "Built with Qwen"), Wan Animate 2 (re-shoots), Real-ESRGAN x4plus (4K), YuNet and SFace (the local face check). Narration in the demo: Kokoro-82M. |
| Repository | the repository link (filled in by `scripts/fill_links.py` when the repo is public) |
| Demo video | the video link, under two minutes |
| Live link | the hosted copy: 137 recorded takes, every receipt verified, no GPU and no key needed |
| Anything else | The hosted copy plays all 137 recorded takes and checks each receipt in the browser. 5 of the 49 camera moves did not hold on a real render, and the app plays none of them. Agents can direct it through its MCP server (24 tools) and a skill file; the Chat room runs OpenCode with an open-weights model by default, and rendering never calls a closed API whichever agent asks. Every tile that shows a take plays it under the pointer or keyboard focus, and the studio's sounds are off until the person turns them on. |

The counts above are checked against `openfield verify` and [docs/EVIDENCE.md](docs/EVIDENCE.md) before the form is sent.

## Links

- Repository: `https://github.com/d0rb/openfield-studio`
- Demo video (2:00 maximum): `https://d0rb.github.io/openfield-studio/demo.mp4`
- Try it in your browser: `https://d0rb.github.io/openfield-studio/`
- Social post: the drafts are below.

## Description

**Short, for the form**

> OpenField Studio is a film studio that runs on open-weights models in ComfyUI. Pick one of 49 camera moves (44 of 49 hold) and LTX 2.5 renders the shot with its own sound. Every take keeps a receipt with its prompts, seed, workflows and model files, and you can check it in your browser. MIT, workflows included.

**Long**

> OpenField Studio is a film studio for short clips, built on the Comfy Developer Platform with open-weights models only: LTX 2.5 for video and sound, Qwen-Image 2.1 for stills and edits, Wan Animate 2 for motion transfer and Real-ESRGAN to upscale.
>
> You describe a shot and pick a camera move. A planned camera rides a small set so you see the move first. Qwen-Image renders the stills the move needs, you approve them, and LTX 2.5 renders the video from them. A 5-second shot costs 2 to 3 cents of rented GPU time, and the 136 takes whose receipts record GPU time took 5.6 GPU hours in all, about $3.97.
>
> Around that: a Cast that keeps a face in every shot, nine setups from one still, a re-shoot that puts a new dancer in your dance, edits with words, effects, transitions, dubs and a Chat room where an agent directs the studio for you.
>
> Every take is saved with a receipt: the prompts, the seed, the exact workflows with their hash, each model file with its licence and source, the hash of every output file, and the open-weights check. The hosted copy plays 137 recorded takes with no GPU and no key.

## What judges can check in five minutes

| Claim | How to check it |
|---|---|
| It runs with no key and no GPU | `pip install -e .`, then `openfield demo`. The recorded takes play with their receipts. |
| It uses the Comfy Developer Platform | `openfield/backends/sdk.py` sends every render through `comfy-sdk`. |
| Open weights only | `openfield audit <workflow.api.json>` on any graph. Every receipt carries the audit result. |
| Every receipt is intact | `openfield verify`, or *Check it in this browser* on any take, which hashes the receipt in your own browser. |
| A receipt shows what changed | *Compare…* on any take plays it beside another and lists what the two receipts say differently, word by word. |
| Each camera move is a real render | The Lobby's camera moves gallery plays the take behind each move. [docs/EVIDENCE.md](docs/EVIDENCE.md) says how each one was judged, including the optical-flow check of every take. |
| The hosted copy never invents a take | Change a recorded recipe there and it says it cannot render it. |
| It is tested | `pytest` covers the engine, the API and a browser run of the live app and the hosted copy. `node --test tests/js` covers the interface logic. |

## The demo video

Under two minutes, recorded from the real app with `python scripts/record_demo.py` ([docs/DEMO.md](docs/DEMO.md)). Every take on screen is a recorded take with its receipt. The narration is an open-weights voice (Kokoro-82M), named on the end card, and the characters speak in their own LTX 2.5 voices. The end card carries "Built with Qwen", as the Qwen-Image 2.1 licence requires.

## Social posts

**Short (X, under 280 characters with the link)**

> I built a film studio that runs on open-weights models in ComfyUI. Pick a camera move, check the stills, and LTX 2.5 shoots it with sound. Every take keeps a receipt you can check in your browser. https://d0rb.github.io/openfield-studio/demo.mp4 #ComfyUI

**Long**

> OpenField Studio is a film studio that runs on open-weights models in ComfyUI. You pick one of 49 camera moves and watch the planned camera ride a small set. Two stills come first, and LTX 2.5 renders the shot with its own sound once you approve them. A 5-second shot costs 2 to 3 cents of rented GPU time. Every take keeps a receipt with the prompts, the seed, the workflows and every model file, and you can check it in your browser. The hosted copy plays 137 recorded takes with no GPU and no key. MIT, workflows included. Demo: https://d0rb.github.io/openfield-studio/demo.mp4 Code: https://github.com/d0rb/openfield-studio #ComfyUI

## What does not work yet

- 5 of the 49 moves did not hold on a real render: arc left, arc right, orbit 360, rack focus and pedestal down. The app plays no loop for them. On October 26 two more held for the first time: through object, made as its reverse (a dolly out from just inside the door, played backwards), and the dolly zoom, made as a dolly out with a window that follows the face and keeps it at its size. Pedestal down made as its reverse still pulled back, and the keyframed arcs still turned the subject, so those stay off until a render holds.
- 65 of the 96 camera positions hold on a still. A shot that starts from a re-angled still drifts away from the angle.
- Of the four transition styles, only the push holds.
- Comfy Cloud: the connection was checked on October 22 with a key; no take has been rendered there yet. Every take was rendered on rented RTX 5090s.
- A receipt is a checksum. It shows edits but does not prove who made the file.

The full record of what was rendered and how it was judged is in [docs/EVIDENCE.md](docs/EVIDENCE.md).

## Models

LTX 2.5 (LTX-2.x Community License), Qwen-Image 2.1 (Qwen Research License, non-commercial, "Built with Qwen"), Wan Animate 2 (Apache-2.0), Real-ESRGAN x4plus (BSD-3-Clause), and YuNet and SFace for the local face check (MIT, Apache-2.0). Judging aids outside the app: faster-whisper to transcribe spoken lines back, and two vision models through OpenCode for a second reading of contact sheets. Details in [THIRD_PARTY_MODELS.md](THIRD_PARTY_MODELS.md).
