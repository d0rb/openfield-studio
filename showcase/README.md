# The showcase

Everything Replay plays and the hosted copy shows was rendered from the specs in this folder by `openfield showcase`, on a real backend. Nothing is staged. Each take's receipt names the models, seeds and workflow graphs behind it.

| File | What it is |
|---|---|
| `spec.json` | Five invented characters (Mara, Oskar and Ines from the first week, Noor and Tomas since October 23; all generated from text, so they are reproducible and nobody's likeness), ten shots across the promoted camera moves, a **sheet** of one shot under all 12 promoted moves (same subject, same seed, so the moves compare side by side. It is the Moves tab in Takes and the README's second image), and three re-shoots of one clip. Round 5 (Oct 22) adds the twelve angle takes of one subject (`angle-oskar-*`: the pier hero re-shot from a camera position, then a static shot from there), five transformations (`fx-ignite`, `fx-freeze`, `fx-gold`, `fx-bloom`, `fx-night`), two one-pass orbits (`sp-orbit-180`, `sp-orbit-360`, rendered with `--single-pass`), a prompt-only take for each of the seven signature moves plus the dolly zoom (`sig-*`), and a ten-second take. `openfield showcase --dry-run` prints the render count. |
| `round7.spec.json` | Round 7, the fifth and sixth sessions (Oct 23): the five characters, then 167 takes in blocks appended session by session (v1 to v6 on October 23, the v8 and v9 blocks on October 24 and 25). `openfield showcase --spec showcase/round7.spec.json --dry-run` prints the plan. |
| `experiment-keyframing.json` | The rig's question: planning anchor stills against one still and a camera instruction. Five moves, two characters, both ways, same seeds. 50 renders. |
| `assets/source.mp4` | The clip the re-shoots transfer motion from: the showcase's own `dance-source` take (an invented dancer on a rooftop, rendered with LTX 2.5). No real person's footage ships with the repo. Replace it with your own clip to re-shoot yourself. |
| `assets/mara-pier.mp4` | The clip the face-only re-shoot `v1b-reshoot-face-noor-pier` starts from: one of the showcase's own spoken-line takes (Mara on the pier, rendered with LTX 2.5). Nobody was filmed. |
| `assets/ref-mara.png`, `assets/ref-oskar.png`, `assets/ref-ines.png` | Full-body reference stills of the three characters, rendered by the `ref-*` takes (Qwen-Image 2.1 with the cast's own portraits as identity references). Wan Animate 2 follows the reference's framing. A dance needs a standing figure. A head-and-shoulders portrait does not work. |
| `report.json` | Written by the run: status and real render times per take. |

## The source clip

Re-shoot keeps a person's motion and swaps the character. The clip decides how good the three before/after pairs look. The bundled source is a render (the `dance-source` take: an invented dancer, prompt-only, 5 s. Its receipt is in `openfield/web/showcase/takes/`). Every re-shoot made from it says so in its notes and its receipt. To re-shoot yourself, film a clip (or have someone who agrees to appear in a public repository film one) and put it at the same path:

- one person, **full body in frame**, standing or walking, 6 to 10 seconds
- **vertical** (phone held upright) works best. The template works at 482x854 and centre-crops
- steady camera, plain or uncluttered background, even light, no other people, no logos or music
- one clear action: a turn, a walk toward the camera, a gesture. Big readable movement beats subtle movement

Save it as `showcase/assets/source.mp4`. Metadata such as location is stripped when it is prepared.

## Rendering

```bash
openfield showcase --dry-run              # validates the spec, lists every render
openfield showcase                        # needs COMFY_BASE_URL (a GPU box) or COMFY_API_KEY (Comfy Cloud)
openfield showcase --only mara-market-dolly-in,reshoot-mara     # a subset
openfield showcase --benchmarks docs/benchmarks.md              # also write the render-time table
openfield showcase --single-pass --only sp-orbit-180            # three or more stills guided inside one LTX pass
openfield showcase --spec showcase/round7.spec.json --dry-run   # round 7's plan, every render listed
openfield showcase --spec showcase/round7.spec.json --only v1-noor-mars,v1-shots-noor-mars   # a base take, then the board that starts from it
```

A flag in the code (a tested move, effect, angle, quality tier, transition style, Shots board, edit preset, face-only re-shoot, dub, extension, upscale or the one-pass render) is flipped by hand, and only after the take rendered for it was checked by eye. Until then the interface says the feature is not yet tested. The angle stills are judged first, from a contact sheet, so only the positions that held are rendered as takes.

A feature with no flag (Re-shoot's motion transfer) is called recorded, never tested. A take that starts from another (a board, a bridge, an edit, a dub, an extension, an upscale) reads it by name from the showcase folder, so record the base first. With `--only`, name the base too if it is not recorded yet.

Third session (Oct 22): the from-image take, the draft and fine tiers, all twelve angle stills and their takes, and the five transformations held, so their flags are on. Of the eight signature takes, six held (crash zoom in, eyes in, snorricam, through object, hyperlapse, lazy Susan). The crash zoom out lost its subject, and the dolly zoom rendered as a plain pull-out, so those two stay untested.

The two one-pass orbits rendered as one continuous shot each, with one soundtrack and the camera reaching every still. The subject blurred into a ghost near the guided stills at the template's guide strength, so `SINGLE_PASS` stayed off that night. The ten-second take held (208 s).

The same evening, the seven promoted moves the October 20 sheet rendered without a verdict were judged from their frames. Static, dolly out and optical zoom in read as their move and are tested now. The two-pass orbit 180 smeared at the anchor join.

Arc right, track left and crane down read mostly as the subject turning, so those stayed untested that night. Orbit 180 and orbit 360 became tested in the fourth session, as one-pass renders.

Fourth session (the evening of Oct 22, RTX 5090, about $3): three **spoken lines** (`dlg-*`) rendered and held. The lips move, the identity holds, and an open-weights speech recognizer (faster-whisper, small) transcribed each line word for word from the take's own audio, so `DIALOGUE_TESTED` is on.

A **guide-strength sweep** of the one-pass orbits (0.25, 0.4, 0.55) rendered clean continuous shots where the template's 0.7 had ghosted. 0.4 is the default now (`SINGLE_PASS`, `MID_GUIDE_STRENGTH`), and the bundled orbit-180 takes were re-rendered that way.

The **coverage gate** failed. `coverage.spec.json` re-shoots one dance performance with three references of Oskar re-angled by the rig's own directive (left, back, front-right). The stills held. Wan Animate 2 kept the source clip's viewpoint all three times, using the reference only for identity and clothing.

Coverage is therefore not a feature. The three takes are bundled as the record. Of ten takes on **new subjects**, three read as their move (the burning dome, the alley hyperlapse, the desert highway). Two are clean renders whose move is too subtle to read (the observatory push-in, the lighthouse rise). They stay bundled with their move labelled as planned, but out of the reel.

Five are kept out of the bundle and the reel, but stay in `report.json`: the rooftop orbit rolled the camera upside down, the crash zoom pulled back instead of in, the snorricam read as a pull-back, and the two kitchen takes carry a blown-white frame near the two-thirds mark. Two vision models (Claude Haiku 5.5 and GPT-6, through OpenCode, given the same contact sheets and neutral questions) reached the same verdicts independently, including the coverage failure and the orbit ghost. Their one doubt, Mara's lips in the spoken line, was settled at frame level: her mouth moves through the words.

Round 7 ran in two sessions on rented RTX 5090s on Vast.ai: the fifth on the night of October 22 to 23 (at $0.71 an hour, about $2.19) and the sixth on the morning of October 23 (in Estonia, at $0.79 an hour, about $3.20 projected for its lease). The blocks ran in order, to be cut from the end if time ran short. The first block's misses were re-rolled at the start of the sixth session (v1b) and again after v6 (v1c).

- **v1, features (23 takes).** Eight new base shots (`v1-oskar-kickflip`, `v1-noor-mars`, `v1-tomas-samurai`, `v1-ines-cyberpunk`, `v1-mara-skydive`, `v1-dragon-city`, `v1-lava-surfer`, `v1-cat-dj`). Two Shots boards (`v1-shots-noor-mars`, `v1-shots-tomas-samurai`). Four transitions, one per style (`v1-tr-mara-ines-morph`, `v1-tr-oskar-cat-whip`, `v1-tr-dragon-lava-push`, `v1-tr-noor-tomas-match`). Six edits, one per preset (`v1-edit-face-swap`, `v1-edit-person-swap`, `v1-edit-remove`, `v1-edit-outfit`, `v1-edit-relight`, `v1-edit-custom`). A face-only re-shoot of the dance clip (`v1-reshoot-face-noor`). Two dubs of `dlg-mara-calm`, into Spanish and French (`v1-dub-mara-es`, `v1-dub-mara-fr`). The boards, bridges and edits start from the new base takes, the dubs from a take that already ships.
- **v1b and v1c, re-rolls (18 planned, 16 rendered).** The base shots again, most with *What happens*, the cat's still framed wide for its crash zoom and Noor's orbit as a keyframed half orbit. The bridges with an idea of how one shot becomes the next. The face-only re-shoot on the pier take (`v1b-reshoot-face-noor-pier`). The Dutch angle, the super dolly in, ruin and fog once more.
- **v2, moves and effects (19).** The six new prompt-only moves (`v2-bullet-time`, `v2-aerial-pullback`, `v2-dutch-angle`, `v2-fisheye`, `v2-super-dolly-in`, `v2-yoyo-zoom`) and the 13 effects that were untested: the seven new transformations (`v2-fx-bts`, `v2-fx-vanish`, `v2-fx-clones`, `v2-fx-comic`, `v2-fx-painting`, `v2-fx-melt`, `v2-fx-flood`), the three older ones (`v2-fx-age`, `v2-fx-snowfall`, `v2-fx-ruin`), time freeze and fog (`v2-fx-time-freeze`, `v2-fx-fog`) and the new slow motion (`v2-fx-slow-motion`).
- **v3, loops (5).** Three loops (the loop move: `v3-loop-storm-waves`, `v3-loop-campfire`, `v3-loop-neon-rain`), a full orbit that ends where it began (`v3-loop-camera-dolly`) and a product spin (`v3-spin-sneaker`, lazy Susan).
- **v5 and v6 (3).** Two 3-second extensions (`v5-extend-lava`, `v5-extend-ines-canal`) and a Draft take upscaled to 2K (`v6-upscale-draft-2k`).
- **v4, the moves wall (26).** Every other untested move, once, on one subject and one seed (Noor on a dune, seed 620), at Draft quality (896×512): `v4-draft-pan-left` to `v4-draft-crash-zoom-out`. It did not run: the sixth session's box stopped when the account's credit ran out, during the ruin re-roll (`v1c-fx-ruin`) and before the fog one (`v1c-fx-fog`).

Every take was judged by eye at full size, from strips at 2 to 12 frames a second and close-up strips of the eyes cut with the app's own face detector. Two vision models (Claude Haiku 5.5 and GPT-6 Luna, through OpenCode) read a six-frame contact sheet of each take as a cross-check. Where they disagreed with the strips, the strips decided. Six frames miss a sub-second move such as a crash zoom or a whip streak, and one model failed the melt, age and ruin takes for showing no change and passed fog.

The dubs were also transcribed with faster-whisper (small). Of the 66 takes rendered, 43 held and are bundled. The 23 that did not are kept out.

- **Features.** Both Shots boards, all six edits, both dubs, both extensions and the upscale held, and so did the face-only re-shoot on the pier take. On the dance clip the face was about 40 px tall and could not be judged. `SHOTS_TESTED`, `EDITS_TESTED` (all six), `FACE_ONLY_TESTED`, `DUB_TESTED`, `EXTEND_TESTED` and `UPSCALE_TESTED` are on.
- **Transitions.** One bridge of nine held, `v1c-tr-rooftop-dragon-push`, so `TRANSITIONS_TESTED` holds push through only. The first four, with no idea, washed out, cut or dissolved. With an idea the morphs and whips moved the setting itself (clouds and dunes into lava, a lava wave into orange streaks) but still landed on the second take by a cut.
- **Base shots.** Two of the eight held (`v1-mara-skydive`, `v1-lava-surfer`). The others missed their action or their move (a vanishing skateboard, an orbit that came out as a pull-back, no katana draw, a parked bike, a dragon hanging frozen, a cat that started close and left the frame). The re-rolls held for the samurai (`v1b-tomas-samurai-draw`), the ride (`v1b-ines-ride`), the cat (`v1b-cat-dj-zoom`), Noor's orbit (`v1b-noor-mars-orbit`, one pass) and, at the third try, the skateboard (`v1c-oskar-skate-dolly`) and the dragon (`v1c-dragon-glide-wide`).
- **Moves.** Bullet time, aerial pullback, fisheye, YoYo zoom and the loop move held and joined `VALIDATED` (21 of 49). (October 24: bullet time was taken back after a closer look. See session 7.) The Dutch angle kept rolling past its tilt twice, and the super dolly in failed twice (a gentle push, then a face too small to carry the character), so both stay untested. (The super dolly in held on October 24 and the Dutch angle, made a new way, on October 25. See sessions 7 and 8.)
- **Effects.** Eleven of the 13 held (age, snowfall, behind the scenes, vanish, clones, comic book, oil painting, melt, flood, time freeze, slow motion), so 19 of 21 are tested. Ruin (a light stand drifted through the frame) and fog (a faint haze, a drifting camera, a figure appearing late) did not.
- **Loops.** The three loops close on their first frame, the full orbit (`v3-loop-camera-dolly`) returns to its first still in one pass with three guided stills, and the sneaker turns on the spot (`v3-spin-sneaker`).

Session 7 (October 24, a rented RTX 5090 in Seoul. The runner ran on the box, because the relay to it carried 25-200 KB/s):

- **v4 began, then stopped.** Under the old wording the keyframed pans and the tilt up failed the same way: their edited end still came out the same as the first, so LTX invented motion (the subject turning round, a tripod walking in because the words said tripod). The rest of v4 was cancelled and the moves were redrawn.
- **The prompt A/B.** Five recorded recipes again under prompt style 2 (`OPENFIELD_PROMPT_STYLE=2`, now the default): the samurai's dolly in held and travelled further, the cat's crash zoom and Noor's half orbit held, the super dolly in finally pushed all the way in (but the cast's face, a few pixels at the start, did not survive), and the Dutch angle still rolled.
- **v8 and v8b, every untested move once more (Draft, Noor on a dune, seed 620).** Thirteen held and joined `VALIDATED` (33 of 49): push in, pull out, truck right, pedestal up, low angle, over the shoulder, handheld, whip pan, crash zoom out, super dolly in (`v8-super-dolly-in`, no Cast), pan left, pan right and tilt down (the last three in v8b, after the words lost "tripod" and pans got a wide first frame). Each verdict comes from strips of 8 to 16 frames, two vision models (Claude Haiku 5.5, GPT-6 Luna) and the clip's optical flow (`motion_meter`: which way and how far the picture moves, how much it grows, how much it jitters, how big the face is). Arc right, which looked like an arc, measured as the subject turning in front of a still camera.
- **v8-rv and v8c, the tested moves again under style 2.** All held except bullet time: on a closer look the October 23 take (`v2-bullet-time`) and two re-renders move the dancer and hold the camera still, so bullet time is untested again. The full orbit rolled at Draft and held at Standard, where it was first tested. Rain, ignite, gold statue, behind the scenes and a spoken line (Whisper heard "We leave at first light") held under style 2.
- **v8d.** Ruin did not hold under style 2. Fog, with its new words, held.
- **The MCP film.** A headless Claude Code session made a three-shot film through `openfield mcp`. Its five takes (`tk_20261024_192756_a60e` is the film) are in the bundle. See `docs/MCP.md`.

Session 8 (the night of October 24 to 25, on the same rented RTX 5090 as session 7, Vast.ai instance 57539009, destroyed on the owner's word when the work was done. The account's credit went from $4.71 to $4.01 over the session's last hour and a half, about $0.70):

- **The Dutch angle, made in code (the v9 entries in `round7.spec.json`).** Turning only the first still failed twice: image models draw a level horizon, and LTX 2.5 levels a canted first frame back out within the shot. So a rolled move is now shot level and static, rendered larger than the frame (1856×1024 for Standard's 1280×704), and the finished video is turned 15 degrees in code and cropped back to the frame (`video.roll`, `rig.ROLLS`). The receipt's `inputs.roll` gives the degrees, the rendered size, the crop and the size. Nothing is upscaled. The LTX prompt uses the static move's words, and the hero still is framed wide with room above the head. All four renders stayed canted from the first frame to the last. The detective in the alley (`v9b-dutch-angle-noir`, take `tk_20261024_232528_8944`) holds clean: a still camera by the optical-flow meter, the action played, the face sharp. It is in the bundle, and the Dutch angle joined `VALIDATED` (34 of 49). Two samurai renders drifted in (LTX pushed toward him) and a subway render turned her face away, so those were not landed.
- **The interface art.** About 120 art renders and four loops for the new Lobby were rendered in the same session through the app's own audited templates. They are not showcase takes. Each of the 64 web files kept from them is listed with its prompt, seed, models and hashes in `openfield/web/art/manifest.json`.

It is resumable. A take already recorded from an unchanged spec entry is skipped (`--force` re-renders). One failing take never stops the others. The end of the run lists what failed and why. Finished takes land in `openfield/web/showcase/takes/` without the large intermediate video, ready for Replay and `openfield export-static`.

How long it takes and what it costs depends on the box and the queue. See `docs/POD.md` for setting a box up. `docs/benchmarks.md` (written by `--benchmarks`) has what each step actually took on the machine that rendered it.

## The keyframing experiment

```bash
openfield showcase --spec showcase/experiment-keyframing.json --out data-showcase/experiment
```

Compare each `-keyframed` take with its `-prompt` twin. Check that the camera moves cleanly, the character stays the same person, and the background stays put. Only moves that win belong in `VALIDATED` in `openfield/engine/rig.py`. Any that do not stay prompt-only, and the interface says so.

The judging is blind and the rule is written down before the run:

```bash
python scripts/judge_experiment.py sheet --run data-showcase/experiment --out data-showcase/experiment/judge --seed 7
# viewers fill in judge/verdicts.csv (pair, viewer, reads_as_move, no_seam, better_side) without seeing the key
python scripts/judge_experiment.py reveal --out data-showcase/experiment/judge --verdicts data-showcase/experiment/judge/verdicts.csv
```

A keyframed move is validated when every viewer says the keyframed take reads as the move and shows no seam at the anchor
join, a majority of viewers prefers it, and its identity score is not below its prompt-only twin by more than 0.05. The face
check varies by about that much between runs. The tolerance was added after the first run, whose twins differed by
0.009 and 0.016 on moves every viewer had preferred keyframed. A tie goes to prompt-only, because it costs less.

**Result, 2026-10-20 (RTX 5090, one viewer so far):** keyframing won `dolly_in` and `crane_up` and lost `arc_left`,
`track_right` and `orbit_90`, where the edited anchor stills turned the character instead of moving the camera. The two
winners keep their anchors. Track right and orbit 90 are prompt-only in the move table now and carry the tested mark; arc
left, which the later sessions measured standing still or arcing the wrong way, went back to two stills on October 26
(the end still's facing anchored to the scene) and waits for a render that holds.
Their anchor edits remain in `openfield/engine/rig.py` for a future re-test, which means flipping their mode back to
keyframed first. The first night-market take drifted to a different face inside the LTX clip while its stills held, so its
seed was changed and it was re-rendered.

**Session 10, 2026-10-26 (`round13.spec.json`, a rented RTX 5090 shared with the owner's own jobs).** The samurai draw
was re-rendered twelve ways (high guard, low guard, slow, the blade raised straight up) and bullet time six ways. None of the
draws met every rule written for it, because LTX 2.5 draws a blade in under 0.7 s whatever the words say; `r13-a4-draw-up-624`
is the new hero and dolly-in tile (the blade leaves the scabbard and rises vertical and clear of the face, the eyes found in
every sample), and `r13-b3-bt-from44ee-1167`, made from the still of the earlier bullet time, is the new bullet-time tile
(the camera circles him with the blade long until it passes behind him). Through object held for the first time, made as its
reverse (`r13-c-through-hut-1341`), and so did the dolly zoom with the window following the face (`r13-c-vertigo-corridor-1361`);
pedestal down made the same way came down but pulled back, the second through-object take read a garbled shop sign, the pier
dolly zoom pulled back past the window's cap, and the first keyframed arc turned the subject a full circle. The two takes they replaced (`v1b-tomas-samurai-draw`, `r11-bt5-samurai-a`) and the nineteen
renders that did not hold are set aside with their reasons in `report.json`; the owner's sheets are in the session folder.
