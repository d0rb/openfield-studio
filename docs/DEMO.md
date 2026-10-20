# Recording the demo video

The contest asks for a demo of two minutes or less that shows the real app. `scripts/record_demo.py` makes that
video from a script, so any fix to the interface can be re-taken in a minute instead of re-shot by hand.

It drives a real Chrome or Edge through the interface (cursor, clicks, typing, the Before/After drag), captures the
page, and encodes a silent 1920×1080, 30 fps MP4 plus a timed cue sheet for the voice-over. You record the voice
afterwards and lay it over the video in any editor.

## Run it

You need Node, a Chrome or Edge (set `OPENFIELD_BROWSER` to point at a specific one), and the project installed
(`pip install -e .`; the encoder is the same ffmpeg the app uses).

```bash
# against the hosted Replay: recorded takes, no GPU, no keys
python scripts/record_demo.py --url http://127.0.0.1:8080/ --out data-dev/demo

# against a live app on a real backend, with your own scenario
python scripts/record_demo.py --url http://127.0.0.1:8080/ --scenario my.scenario.json --out data-dev/demo
```

Output in `--out`:

| File | What it is |
|---|---|
| `demo.mp4` | The silent video (`demo.FAKE.mp4` when the footage is a test pattern, see below) |
| `cues.txt` | The narration lines with the time each should start, e.g. `0:14  Direct a shot…` |
| `timeline.json` | The same, machine-readable, with the backend label and any time-lapse cuts |

The script prints a warning when the video runs over two minutes.

## The scenario

`scripts/ui/demo.scenario.json` is the walk used for the submission: Re-shoot comparator, Cast, Direct with the Move
Pad, a recorded run, the receipt, Takes. It is plain JSON, a list of steps:

| Step | Does |
|---|---|
| `goto` `{route}` | Open a station: `direct`, `reshoot`, `cast`, `takes` (or `{url}` for any page) |
| `say` `{text}` | A narration cue, timed in the finished video and written to `cues.txt` |
| `hold` `{ms}` | Stay put; the recording keeps running |
| `click` `{selector, text?}` | Glide the cursor there and click; `text` picks the match containing it |
| `type` `{selector, text, cps?}` | Click a field and type at human speed |
| `key` `{key, ctrl?}` | Press a key |
| `drag` `{selector, by:[dx,dy]}` | Press, drag, release (the Before/After handle) |
| `scroll` `{selector, to}` | Scroll an element |
| `ring` `{selector, ms?}` | Draw attention to something for a moment |
| `until` `{expr, timeout?, speed?, label?}` | Wait for a condition in the page |
| `eval` `{expr}` | Run a snippet in the page |

Selectors are the interface's own class names and `data-` attributes, so when the interface changes a scenario stops
with the step number and the selector it could not find (`step 4 (click): nothing to point at: …`) instead of
recording the wrong thing.

## Two rules the recorder enforces

**Time-lapse is never hidden.** A real render takes minutes. Give an `until` step a `speed` (for example `8`) and
that wait plays eight times faster with an "8× time-lapse" badge on screen; the cut and its factor are also listed in
`cues.txt`. Do not trim a render out of the video any other way: the rules ask for the real app on real renders.

**Test-pattern footage cannot pass as a render.** The development stack (`scripts/dev_fake_stack.py`) answers with
a synthetic colour-bar clip so the interface can be built without a GPU. The recorder reads the backend label on the
page and the receipts of the takes listed there; if either says FAKE, the file is named `demo.FAKE.mp4` and the script
says so on the last line. Only record the submission video against takes rendered by the real models.

## Re-taking after a change

1. Fix the interface.
2. Run the recorder again. It runs in real time, so a two-minute video takes about two minutes.
3. Open `cues.txt`, adjust the voice-over timings if a beat moved, re-lay the audio.

The recorder itself is covered by `tests/test_demo_recorder.py`, which records a short walk against the offline fake
and checks the video, the cue timing and the FAKE guard.
