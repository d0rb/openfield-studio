# The showcase

Everything Replay plays and the hosted copy shows was rendered from the specs in this folder, by `openfield showcase`,
on a real backend. Nothing is staged: each take's receipt names the models, seeds and workflow graphs that made it.

| File | What it is |
|---|---|
| `spec.json` | Three invented characters (generated from text, so they are reproducible and nobody's likeness), ten shots with the 12 promoted camera moves, and three re-shoots of one clip. 43 ComfyUI renders. |
| `experiment-keyframing.json` | The question behind the rig: does planning anchor stills beat one still and a camera instruction? Five moves, two characters, both ways, same seeds. 54 renders. |
| `assets/source.mp4` | **You add this.** The clip the re-shoots transfer motion from. |
| `report.json` | Written by the run: status and real render times per take. |

## The source clip

Re-shoot keeps a person's motion and swaps the character, so the clip decides how good the three before/after pairs look.
Film it yourself (or with someone who agrees to appear in a public repository):

- one person, **full body in frame**, standing or walking; 6 to 10 seconds
- **vertical** (phone held upright) works best; the template works at 482x854 and centre-crops
- steady camera, plain or uncluttered background, even light, no other people, no logos or music
- one clear action: a turn, a walk toward the camera, a gesture. Big readable movement beats subtle movement

Save it as `showcase/assets/source.mp4`. Metadata such as location is stripped when it is prepared.

## Rendering

```bash
openfield showcase --dry-run              # validates the spec, lists every render
openfield showcase                        # needs COMFY_BASE_URL (a GPU box) or COMFY_API_KEY (Comfy Cloud)
openfield showcase --only mara-market-dolly-in,reshoot-mara     # a subset
openfield showcase --benchmarks docs/benchmarks.md              # also write the render-time table
```

It is resumable: a take already recorded from an unchanged spec entry is skipped (`--force` re-renders). One failing
take never stops the others; the end of the run lists what failed and why. Finished takes land in
`openfield/web/showcase/takes/` without the large intermediate video, ready for Replay and `openfield export-static`.

How long it takes and what it costs depends on the box and the queue. See `docs/POD.md` for setting a box up, and
`docs/benchmarks.md` (written by `--benchmarks`) for what each step actually took on the machine that rendered it.

## The keyframing experiment

```bash
openfield showcase --spec showcase/experiment-keyframing.json --out data-showcase/experiment
```

Compare each `-keyframed` take with its `-prompt` twin: does the camera move cleanly, does the character stay the same
person, does the background stay put? Only moves that win belong in `VALIDATED` in `openfield/engine/rig.py`; any that do
not stay prompt-only, and the interface says so.
