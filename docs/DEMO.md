# Recording the demo video

The contest asks for a demo of two minutes or less that shows the real app. `scripts/record_demo.py` makes that
video from a script, so any fix to the interface can be re-taken in a minute instead of re-shot by hand.

It drives a real Chrome or Edge through the interface (cursor, clicks, typing, the Before/After drag), captures the
page, and encodes a silent 1920×1080, 30 fps MP4 plus a timed cue sheet for the voice-over. You record the voice
afterwards and lay it over the video in any editor, or pass it to the recorder with `--audio` and let ffmpeg mux it.
Captions, a title card and an end card are drawn in the browser overlay, so they are in the picture, not added later.

## Run it

You need Node, a Chrome or Edge (set `OPENFIELD_BROWSER` to point at a specific one), and the project installed
(`pip install -e .`; the encoder is the same ffmpeg the app uses).

```bash
# against the hosted Replay: recorded takes, no GPU, no keys
python scripts/record_demo.py --url http://127.0.0.1:8080/ --out data-dev/demo

# against a live app on a real backend, with your own scenario
python scripts/record_demo.py --url http://127.0.0.1:8080/ --scenario my.scenario.json --out data-dev/demo

# fill the card's links and lay your voice-over in from the first second
python scripts/record_demo.py --url http://127.0.0.1:8080/ --out data-dev/demo \
    --try-url https://try.example/ --repo-url https://example.com/repo \
    --audio 0=voice.wav --audio 62=music.wav
```

Flags:

| Flag | Does |
|---|---|
| `--try-url URL` | Fills `{try_url}` in card, caption and `say` text |
| `--repo-url URL` | Fills `{repo_url}` in card, caption and `say` text |
| `--audio VIDEO_S=PATH` | Lay this file's audio into the video from `VIDEO_S` seconds; repeatable. Fades in over 0.05 s and mixes all tracks; without it the video stays silent |
| `--clips DIR` | The folder a `film { src }` step plays from (served on a local port while recording); the same folder is where `film { src, sound: true }` reads the clip's own sound |
| `--takes-dir DIR` | Where a `film { take, sound: true }` finds the take's own sound (default `openfield/web/showcase/takes`) |

The frames go to disk before they are encoded: about 1 GB for two minutes. Two settings help a short disk. `OPENFIELD_FRAME_CAP=30` keeps at most about 30 frames a second (the cut is 30 fps, and a page playing video sends 60), which halves it: demo cut 11 needed 3,048 frames. `OPENFIELD_JPEG_QUALITY` (default 92) lowers the frames' quality.

Output in `--out`:

| File | What it is |
|---|---|
| `demo.mp4` | The silent video (or with audio, when `--audio` is given); `demo.FAKE.mp4` when the footage is a test pattern, see below |
| `cues.txt` | The narration lines with the time each should start, e.g. `0:14  Direct a shot…` |
| `captions.txt` | The on-screen captions with the time each starts, e.g. `0:14  One prompt becomes a shot`; a caption with a `tag` lists it first, e.g. `0:14  LTX 2.5 \| One take flies into the next` |
| `timeline.json` | The same, machine-readable, with the backend label and any time-lapse cuts. Every cue has `video_s`, `text`, `caption` and `tag` (`null` when there is none); a `film` cue also has `film` (the take id or clip name), `from`, `ms` (how long it runs), `sound` (the take whose sound goes with it) and `clip_sound` (the clip whose sound goes with it) |

The script prints a warning when the video runs over two minutes.

## The scenario

`scripts/ui/demo.scenario.json` is the walk the submission video is cut from (cut 12d, recorded October 27; the scenario now carries the cut 12f trims, 5 s shorter, for the next recording on the round-15 front, where the trailer runs across the Lobby): the take an agent shot in the
Chat room, the hook on a recorded take, the Lobby, Direct with the stills strip and the planned camera, the Shots board, a
transition, the edits, Re-shoot, a dubbed line, an effect, the receipt checked in the browser, two takes compared, the
workflows, a live render sped up eight times, Replay's refusal and the end card. Six short narration
lines carry it; everything else is a tagged caption. It opens on the work (the agent's take, then the hook) before the
Lobby, and the `_comment` in the file has the record command. It is plain JSON, a list of steps:

| Step | Does |
|---|---|
| `goto` `{route}` | Open a station: `direct`, `reshoot`, `cast`, `takes` (or `{url}` for any page) |
| `say` `{text, caption?, tag?}` | A narration cue, timed in the finished video and written to `cues.txt`; `caption` (a string, or `null` to clear) also prints it on screen, with `tag` (a short label such as `"LTX 2.5"`) above the line |
| `caption` `{text \| null, tag?}` | Print a caption, or clear it with `null`, without adding a narration cue. A `null` text clears the tag with it, and a caption with no `tag` shows none (it never keeps the last one) |
| `card` `{title, lines?, mono?, ms?, hold?}` | A title or end card: a rule, the title, up to four `lines` in grey and an optional `mono` link line. Shows for `ms` (default 3000) then goes; `hold: true` keeps it until the next card or `card {clear: true}` |
| `hold` `{ms}` | Stay put; the recording keeps running |
| `click` `{selector, text?}` | Glide the cursor there and click; `text` picks the match containing it |
| `type` `{selector, text, cps?}` | Click a field and type at human speed |
| `key` `{key, ctrl?}` | Press a key |
| `drag` `{selector, by:[dx,dy]}` | Press, drag, release (the Before/After handle) |
| `scroll` `{selector, to}` | Scroll an element |
| `ring` `{selector, ms?}` | Draw attention to something for a moment |
| `hover` `{selector, text?, ms?}` | Glide the cursor onto something and stay; Move Pad tiles and the Moves sheet play their render on hover |
| `sweep` `{selector, from?, to?, ms?, back?}` | Run the cursor across something without a click, from `from` to `to` of its width; a frame in the Lobby's camera moves gallery scrubs its take under it |
| `film` `{take \| src, from?, ms?, caption?, captionTag?, captionAt?, chip?, chipAt?, sound?, loop?, hold?}` | Play a take's own video, or a clip from `--clips`, full frame, from `from` seconds for `ms` (default 5000). `caption` and `captionTag` print a caption `captionAt` ms in. `sound` lays the file's own sound in at the cue (a take's from `--takes-dir`, a clip's from `--clips`), from `from` and cut to the film: `ms` plus 0.25 s, with a 0.2 s fade out. A file with no audio track is reported and stays silent. The cue records `ms`, and `clip_sound` for a clip |
| `until` `{expr, timeout?, speed?, label?}` | Wait for a condition in the page |
| `eval` `{expr}` | Run a snippet in the page |

Selectors are the interface's own class names and `data-` attributes, so when the interface changes a scenario stops
with the step number and the selector it could not find (`step 4 (click): nothing to point at: …`) instead of
recording the wrong thing.

Captions and cards are drawn in the same browser overlay as the cursor, so they are baked into the frames. A caption
is a headline in the promo's form: bottom-left, 64 px in, 88 px condensed capitals over a gradient scrim that fades out
150 px above the text, at most 74% of the width; a ` / ` in the text breaks it into two lines, the second in orange. Its
`tag`, when it has one, prints above the headline in 17 px orange mono capitals behind a dot. The receipt chip
(`film { chip }`) sits bottom-right, 60 px up. A card covers the viewport with the title, up to four grey lines, an
optional `statement` (condensed capitals, ` / ` splitting its two lines as in a caption) and a mono block that keeps its
line breaks. Use `card` with `hold: true` for the opening title and clear or replace it when the walk
starts; the same step at the end is the end card. Every card, caption and `say` text may hold `{try_url}` and
`{repo_url}`, filled from `--try-url` and `--repo-url`; when a value is empty, a `lines` entry or a `mono` line that
still holds that placeholder is dropped, so the card never shows a blank link.

## Two rules the recorder enforces

**Time-lapse is never hidden.** A real render takes minutes. Give an `until` step a `speed` (for example `8`) and
that wait plays eight times faster with an "8× time-lapse" badge on screen; the cut and its factor are also listed in
`cues.txt`. Do not trim a render out of the video any other way: the rules ask for the real app on real renders.

**The scenarios in `scripts/ui/`.** `demo.scenario.json` is the whole cut on the Replay app (above). Its six lines are a
synthetic voice, Kokoro-82M (Apache-2.0, open weights), synthesized from the `say` lines and laid in after the recording
at the cue times the recorder writes to `timeline.json`, with the takes' own sound under their beats; the end card says
so. The two films it plays from `scripts/ui/clips` are real too: the bullet-time take saved with its camera path from
the move page, and twelve seconds of a live render sped up eight times (the badge on it says so). `hero.scenario.json` is the README's loop; `live.scenario.json`
is the beat recorded against a real box on October 21 (a crane-up render at 8×), and `live3.scenario.json` the longer
version planned for the third session (connecting the box from the header, the five-row readiness check, a draft-tier
render with its measured time), which timed out at the readiness check before the box was returned, so the cut keeps
the October 21 clip. A live clip is spliced into the main cut at its beat, so the badge on screen says which seconds
were skipped.

**Test-pattern footage cannot pass as a render.** The development stack (`scripts/dev_fake_stack.py`) answers with
a synthetic colour-bar clip so the interface can be built without a GPU. The recorder reads the backend label on the
page and the receipts of the takes listed there; if either says FAKE, the file is named `demo.FAKE.mp4` and the script
says so on the last line. Only record the submission video against takes rendered by the real models.

## Re-taking after a change

1. Fix the interface.
2. Run the recorder again. It runs in real time, so a two-minute video takes about two minutes.
3. Open `cues.txt`, adjust the voice-over timings if a beat moved, re-lay the audio.

The recorder itself is covered by `tests/test_demo_recorder.py`, which records a short walk against the offline fake
and checks the video, the cue timing, the captions and their tags, the FAKE guard, and that a film's sound is cut to the
length of the film.
