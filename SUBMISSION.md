# Open Source Higgsfield: submission pack

Contest: https://comfy.org/open-source-higgsfield. Deadline: **2026-10-30 09:00 PT**. One submission per person.

## Before you submit

- [ ] Public GitHub repo with the MIT licence, workflow files (`openfield/workflows/`) and run-it-locally instructions (`README.md`)
- [ ] Demo video, 2:00 maximum, showing the real app on real renders and explaining the models, the tools and how it was built
- [ ] Social post with the video, tagged `#OpenSourceHiggsfield` (Reddit, X, IG, LinkedIn, YouTube or TikTok)
- [ ] "Try it" link (strongly encouraged): the static Replay build, no keys involved
- [ ] On the form: main category and bonus choices (the form decides whether several main categories may be ticked)
- [ ] Re-read the live contest page for rule changes the day you submit

## What judges can verify in five minutes

| Claim | How to check it |
|---|---|
| Runs with no key and no GPU | `pip install -e .` then `openfield demo`: recorded takes play with their receipts |
| Built on the Comfy Developer Platform | `openfield/backends/sdk.py` uses `comfy-sdk`; target chosen by `COMFY_BASE_URL` / `COMFY_API_KEY` only |
| Open weights only | `openfield audit <workflow.api.json>`; every take's receipt carries the audit result; `THIRD_PARTY_MODELS.md` |
| Every take is reproducible | `receipt.json` next to each take: prompts, seeds, workflow hash, exact model files |
| Replay never fakes a render | Edit a recorded recipe in Replay and it is refused with an explanation (`tests/test_pipeline.py`) |
| Tests | `pytest` (CI runs on Windows and Linux): the engine and API against a faithful fake of the Comfy API, and a browser test that drives the real interface and the exported hosted Replay |

## Claims we must not make

- That a take was rendered live when it was replayed (the UI labels Replay takes).
- That the face check proves identity. It reports a similarity score against the references; faceless shots read "n/a".
- That the models are "open source". They are open **weights**, each under its own licence (`THIRD_PARTY_MODELS.md`).
- That a camera move works unless it appears with a real render in the showcase.
- Any render time, price or benchmark that is not measured and recorded in `docs/benchmarks.md`.

## Demo video (2:00)

Real app, real renders, screen capture scripted so it can be re-taken after any fix: `python scripts/record_demo.py`
writes the silent video and a timed cue sheet for the voice-over (`docs/DEMO.md`). It refuses to pass off the
development test pattern as a render: that file is named `demo.FAKE.mp4`.

| Time | Beat | On screen |
|---|---|---|
| 0:00 | Hook: same motion, new character | A Re-shoot before/after, then the 9:16 export |
| 0:20 | Cast with consent | Reference set, consent choice, face check |
| 0:35 | Direct | Rig, Move Pad with the live path, approve the stills, the shot with synced sound |
| 1:05 | Proof | Identity result, the receipt, drop the file back in to remix, download the workflow for ComfyUI |
| 1:25 | Why it is different (about 15 s) | Cheap stills before video; the receipt travels with the file; the open-weights audit |
| 1:40 | How it is built | `comfy-sdk` code, the audit, the licence table, the repo and its licence |

Say aloud: which models were used (LTX 2.5, Qwen-Image 2.1, Wan Animate 2), that rendering runs through the
Comfy Developer Platform, what was run where, and how it was built.

## Social post (draft)

> Open-weights film studio on @ComfyUI: cast a character, direct a shot with a virtual camera rig, re-shoot a phone
> clip with a new character. Every take carries a receipt (prompts, seeds, models, licences) you can drop back in
> to remix. MIT. #OpenSourceHiggsfield

## Models and tools used

LTX 2.5 (video and audio), Qwen-Image 2.1 (stills), Wan Animate 2 (motion transfer), all open weights, run through
the Comfy Developer Platform. Local tools: ffmpeg, OpenCV (YuNet and SFace face check). Built with an AI coding
assistant (Claude Code); say so in the video, since the rules ask for other tools to be explained.
