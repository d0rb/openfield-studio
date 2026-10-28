# Evidence

This is the plain record of what OpenField Studio rendered, what held, what did not, and how it was checked. The README is short. The dates, counts, take names and measurements live here.

Where two files disagree, the newest dated statement wins. Moves went from 34 of 49 to 42 of 49 after GPU session 9 on October 25. Effects went from 20 of 21 to 21 of 21 when ruin held that day. The take count went from 142 receipts to 135 bundled, because 21 takes landed and 28 earlier ones left; on October 26 it went to 137 and the moves to 44 of 49 (session 10: four takes landed, two left, through object and the dolly zoom held).

## How things were checked

Every take was rendered on a rented GPU through comfy-api-proxy, with open-weights models only. The machine and its price are under Render times and cost.

**Judged by eye.** Each take was watched at full size, from strips of 2 to 12 frames a second and from close-up strips of the eyes cut with the app's own face detector. This was the deciding check.

**Two vision models.** Claude Haiku 5.5 and GPT-6 Luna, through OpenCode, each read a six-frame contact sheet. It was a cross-check, and the strips decided. Six frames miss a sub-second move such as a crash zoom, so one model failed the melt, age and ruin takes and passed fog, and the strips overruled it.

**The camera measured with optical flow on October 25.** Session 9 ran the motion meter over every bundled take. It reads which way and how far the picture moves, how much it grows and how big the face is. It caught what six-frame sheets missed: most bundled orbit takes were the subject turning in front of a still camera.

**A blind keyframing experiment.** The rule was written down before the run. One viewer so far, and keyframing won two of five.

`openfield verify` reads the code and the bundled files:

```text
[ ok ] Workflows: 6/6 templates pass
[ ok ] Receipts: 137 take(s), 137 seal(s) verified
[ ok ] Models: 17 model file(s), all open-weights
[ ok ] Proof counts: moves 44/49, angles 65/96, effects 21/21, quality 3/3, from-image yes, single-pass on
[ ok ] Replay: refused an unrecorded recipe

VERIFIED: 5 ok, 0 failed
```

The tested flags live in `openfield/engine/rig.py`. A flag is turned on by hand only after a render for it was checked by eye. A feature with no flag, which is Re-shoot's motion transfer and Cast, is called recorded rather than tested.

The open-weights audit runs before every render and refuses a graph using a partner node or a paid API. The identity check is local: YuNet detection and SFace embeddings, cosine similarity, threshold 0.363.

## Check a take yourself

Three ways, from quickest to most thorough.

- **In the browser.** Open a take, then *Check it in this browser* under its receipt. The page fetches `receipt.json`, writes it as canonical JSON (keys sorted, no spaces, numbers as written) without its `integrity` field, hashes it with SHA-256 and compares the result with the seal. It is the same check `openfield verify` runs, done by your own browser.
- **On the command line.** `openfield verify` checks every workflow, every receipt seal, the model files and the proof counts.
- **By hand.** Every take folder holds the exact workflows it ran as JSON you can load in ComfyUI, and the receipt names the workflow with its hash, every model file with its licence and source, and the hash of every output file.

The receipt also records how long the GPU worked on the take (`backend.timings.total_s`). The app shows that time and what it costs at $0.71 an hour, the rate of the rented RTX 5090. 136 of the 137 bundled receipts record it. The MCP film (tk_20261024_192756_a60e) is the one that does not.

## Camera moves

The rig has 49 moves in 7 groups: lock and aim, dolly and push, zoom and focus, orbit and arc, track and truck, crane and altitude, handheld and story. Twelve are promoted in the interface.

**44 of the 49 are tested.** The count moved from 16 on October 22 to 44 on October 26: 21 by October 23, 33 on October 24, 34 with the Dutch angle, 42 after session 9, and 44 after session 10 (through object and the dolly zoom).

**How a move is built.**

- **One still.** Prompt-only: one approved still and a precise camera instruction. Quick mode renders any keyframed move this way. On October 25 the pans, tilts, trucks, pedestals, arc right, track left and crane down were redrawn this way, because their edited end still came out the same as the first and LTX filled the shot with its own motion.
- **Keyframed.** The rig plans two to five still frames along the path, you approve them, and LTX 2.5 renders between them. A move of three or more stills renders as one generation with the middle stills guided inside it. The template's guide strength of 0.7 ghosted the subject, a sweep found 0.4 clean, and 0.4 is the default.
- **Mirrored.** Track left and truck left were made from their twins on the flipped still, then flipped back.
- **Made in code.** The optical zooms are a window tightening over a still camera's render, and the Dutch angle is turned after the render.
- **Rolled.** A rolled move is shot level and static, rendered larger than the frame at 1856×1024 for Standard's 1280×704, and the finished video is turned 15 degrees and cropped back to the frame (`video.roll`, `rig.ROLLS`, receipt `inputs.roll`). At Fine the template renders at most 1920 wide, so the turned frame is scaled up about 1.44 times and the receipt records it as `inputs.roll.scaled`.

The Dutch angle was rebuilt this way because image models draw a level horizon and LTX 2.5 levels a canted first frame back out within the shot. Turning only the first still failed twice on October 25. All four renders stayed canted from the first frame to the last, and the detective in the alley (`v9b-dutch-angle-noir`) holds clean. Two samurai renders drifted in and a subway render turned her face away.

**The five that do not hold.**

- **Arc left.** On three takes it stood still or arced right, so the words do not set the arc's direction. Arc right is not claimed either: until October 26 it was made from arc left, and now both are keyframed the same way (next entry). Three keyframed arcs rendered that night failed three ways: the camera went the wrong way while she turned a full circle in place, her face was lost as she turned, and the camera barely moved. Both arcs wait for a construction that holds.
- **The arcs, measured.** On October 26 the optical-flow meter was run over every orbit and arc on disk before the next session. For arcs, orbits and bullet time the sign of the sideways flow is the camera's direction (plus means it went right); for trucks and pans it is the picture's. The validated orbits read one sign throughout (the pier orbit 90 at -9.8 px/s, orbit 180 at -12.8), while the three arc-left takes read +12.4 (the wrong way), 0 (it stood still) and +2.8 then -5.6 (it turned back). From October 26 both arcs are keyframed: a second still edited from the hero with the camera moved 45 degrees round the subject and the subject's facing anchored to the scene, not the lens. They stay unflagged until a render holds.
- **Orbit 360.** Its renders turned the subject in front of a still camera, flew up or rolled.
- **Through object (held on October 26).** The four earlier takes pulled back out of the opening, the reverse of the move. So the move is now made as its reverse: a dolly out is rendered from a still framed just inside the open door and played backwards in code, with the sound kept as rendered. The first take so made, Oskar in the fisherman's hut, pushes through the door at 39 to 75 percent a second with no sideways drift and ends inside; a second, through a bookshop door, read the same but its sign came out as garbled letters, so it was set aside.
- **Rack focus.** The image model will not paint the soft subject a rack starts from.
- **Pedestal down.** Three renders dropped and tilted or rose. Made as its reverse on October 26 (a pedestal up played backwards), two more takes came down but pulled back and slid as they did, so it stays off.
- **The dolly zoom (held on October 26).** A dolly-out shrinks the subject faster than a fixed zoom can hold, so the zoom now follows the face: the render is sampled four times a second, the face is found, and a window zooms in code to keep it at its first size; the receipt records the path. Ines in a library corridor held within 5 percent for the whole take while the shelves stretched behind her (the zoom ran from 1.0 to 1.72). Mara at the end of a pier did not: that render pulled back eight times in three seconds, past the 2.2x the window may zoom, and its last frame was a ghost, so it was set aside.

Orbit 180 holds only on a setting with depth. On bare dunes the same move turned the subject instead.

## Camera positions

There are 96 camera positions: 8 azimuths, 4 heights and 3 distances. The approved hero is re-shot from the chosen position with one Qwen-Image 2.1 edit, you approve it as the shot's first still, and the move runs from there.

**65 of the 96 are tested.** Twelve were rendered with a take each on October 22 (`angle-oskar-*`). On October 25 every other position was re-shot as a still from the same hero and checked by eye and by two vision models, and 53 read as their label.

What does not hold: the front quarters keep him facing the lens, so their stills read as front views and are not claimed. Close-ups from the back quarters read as a profile. The back and the back quarters show a side of the scene no still ever recorded.

The angle takes drift. All six angle takes rendered on October 25 tilted, levelled or pulled back, and two lost the subject. A position is claimed for its still, not for the shot that follows it.

## Effects and transitions

There are 21 effects and all 21 are tested: 6 prompt presets and 15 keyframed transformations.

**Prompt presets.** One sentence is added to the LTX shot prompt: rain, lightning, time freeze, dust, fog or slow motion. Rain, lightning and dust were tested on October 21, time freeze and slow motion on October 23. Fog's old words whited out the frame, so they were rewritten on October 24 in positive words and held.

**Transformations.** The last still is edited into the end state with Qwen-Image 2.1, you approve it beside the hero, and LTX 2.5 renders the change between the two with sound. Ignite, freeze, gold statue, bloom and day to night were rendered on October 22 and hold. The other ten were rendered on October 23 and nine held. Ruin had a light stand drift across the frame on October 23 and again on October 24. On October 25 the hall decayed round a grand piano with nothing drifting through, so ruin holds too.

Six transformations skip the identity check: gold statue, age, vanish, clones, comic book and oil painting. Each gives its reason in the receipt. Behind the scenes skips it on its end still only.

**Transitions: push through only, 1 of 4 styles.** A transition is one LTX 2.5 render from the first take's last frame to the second take's first frame. Four styles (morph, whip pan, push through, match cut), a length of 2, 3 or 4 seconds, and up to 240 characters on how it gets there. The new take plays the first take, the bridge and the second, with a 0.12 s cross-fade at each join. A take of another shape is letterboxed, never stretched. The bridge is not face-checked.

The tested bridge is `v1c-tr-rooftop-dragon-push`, where the camera dives off a rooftop, flies down between the towers in one move and comes out in the avenue under the dragon. The first four bridges had no idea and washed out, dissolved or cut. With an idea the morphs and whips moved the setting itself, but the second take still arrived by a cut.

## Apps

**Cast.** Keep reference images for a character or product, or generate an invented character from a description and keep the candidate you like. Consent is required before a cast is saved.

**Direct.** Describe a subject, set the camera rig and pick a move from the 49. Approve the stills, then render the shot with synced sound. A shot can start from your own image, with nothing rendered for the hero.

**Shots.** One still becomes nine setups: wide, close-up, the two three-quarter views, both profiles, low angle, high angle and from behind. Nine Qwen-Image 2.1 edits re-shoot the still. Each is checked for the same person and re-rolled once if it drifts, and a setup that shows no face reads n/a. The take plays the nine stills in order, 0.6 s each. Both boards rendered on October 23 kept one person through all nine setups.

**Re-shoot.** Take a clip and one reference image, and Wan Animate 2 keeps the motion and puts a new character in it. The showcase's source is a dance clip rendered with LTX 2.5, so no real person was filmed. The motion transfer has no flag, so it is called recorded rather than tested: three re-shoots from October 21 are bundled.

*Swap only the face* keeps the clip's look. The first frame gets a Cast character's face in one Qwen-Image 2.1 edit, and Wan Animate 2 re-performs the clip from it. The face comes from a Cast only. It is tested from `v1b-reshoot-face-noor-pier`, which keeps the jacket, the lantern and the spoken turn of the pier take. Identity was 0.84 on the swapped frame and 0.77 on the result. The first try, on a dance clip where the face was about 40 px tall, could not be judged and was kept out.

**Edit with words.** One Qwen-Image 2.1 edit of one still, with six presets: Swap the face, Swap the person, Remove something, Change the outfit, Relight (eight lights, or your own words) and Your words. The two swaps take the face or the person from a Cast only, and without a Cast they are refused before a take exists. The take plays the still before and after, 1.2 s each. All six are tested, one render each: `v1-edit-face-swap`, `v1-edit-person-swap`, `v1-edit-remove`, `v1-edit-outfit`, `v1-edit-relight`, `v1-edit-custom`.

**Dub and spoken lines.** A line goes into the prompt as quoted speech with a delivery (natural, calm, tender, whisper, urgent, shout, radio, announcer) and a language. LTX 2.5 writes the voice with the picture in the same pass, lips and all. Three lines were rendered on October 22, one per character: the lips move with the words, the identity holds, and faster-whisper transcribed every line word for word from the take's own audio.

Dub asks for the language and the line, then shoots the take again from the take's own still, with the same subject, rig, seed and sound. No video, voice or lip movement of the first take is reused, and you write the translation. `v1-dub-mara-es` and `v1-dub-mara-fr` dub `dlg-mara-calm` into Spanish and French, and faster-whisper hears the Spanish line word for word and the French one with one article different.

**Extend.** Continues a finished take from its last frame. One LTX 2.5 image-to-video render adds 3 or 5 seconds, and the new take plays the original and the extension, joined with the same 0.12 s cross-fade. It is tested from two 3-second extensions that join without a jump: `v5-extend-lava` and `v5-extend-ines-canal`.

**Upscale (2K and 4K).** Real-ESRGAN x4plus on ComfyUI's official video-upscale graph, plus one core resize node. The target is 2560 or 3840 pixels on the long side, shape kept. The 4x model holds the whole clip in memory as float32 before the resize, so a take whose estimate passes 24 GB is refused before anything renders. A 5-second Draft take fits, a 5-second Standard take does not. `v6-upscale-draft-2k` took a Draft take from 896×512 to 2560×1462 in about 2 minutes on an RTX 5090, with clean edges where the source was blocky and nothing invented. On October 25 `r11-up-4k` took the helicopter take to 3840×2194 in about 2 minutes.

**Loop.** The move plans two stills and makes the second the hero again, so LTX 2.5 renders from the hero to the hero and the clip is pinned to end on the frame it began with. Quick mode drops the pinned last frame, so a loop rendered in Quick mode is not a loop. It is tested from three takes that close on their first frame by eye: `v3-loop-storm-waves`, `v3-loop-campfire` and `v3-loop-neon-rain`.

**Bullet time.** Rebuilt on October 25 from parts that hold: one still of the moment at its peak, the 90-degree orbit's words and the time-freeze sentence. The take circles Tomas, frozen mid-strike in the rain, from the front to behind his shoulder. It holds a grounded pose, and a dancer in mid-air kept moving in every version tried.

**Chat.** The seventh room puts `openfield mcp` behind a conversation. Three lanes work: OpenCode with an open-weights model, Claude Code, and Codex. Every lane gets the studio's MCP server and nothing else. Each chat has a cap on renders (`OPENFIELD_CHAT_RENDERS`, default 6), kept in a budget file so it holds across turns and restarts. The room answers this computer only. On October 25, OpenCode with DeepSeek V4.1 Flash planned a push-in, shot a draft on the rented RTX 5090, approved the still and finished the take (`tk_20261025_135037_c07b`) through the room.

**The film made through the MCP.** On October 24 a headless Claude Code session on Opus 5.5 made a short movie through the server alone, on a rented RTX 5090 (the studio ran on the box; the MCP server on this PC reached it over an SSH tunnel). Given an idea (Noor finds a glowing doorway on Mars and steps through into a rainy neon Tokyo, where Tomas turns and draws his katana), it read the guide, planned three shots with `plan_shot`, rendered them, looked at every still before approving it and re-rolled three whose hair or face drifted from the Cast (face-check scores 0.83-0.88 after), judged each finished strip, re-rendered two shots that failed its own check, bridged the first two shots with a rendered push transition and joined everything with `make_movie`: a 17.5-second, three-shot film with sound. Its closing report listed what still did not hold (a track that read as the wrong direction, soft bokeh orbs from the anamorphic look it chose). 75 turns, 10 of its 14-render budget, $1.97 of Claude usage, 52 minutes, most of it waiting on a slow link to the box.

## The takes in this repo

137 takes are bundled. Each one is a folder with the video, the stills, the events, the workflows and the receipt.

- October 20 and 21: 22 Direct takes, a dance source, 3 full-body references, 3 re-shoots and 3 effect takes (32).
- October 22: the from-image proof, 3 quality tiers, 12 camera positions, 5 transformations, 2 one-pass orbits, 8 signature moves and a ten-second take (32).
- Evening of October 22: 3 spoken lines, 3 coverage re-shoots, 5 takes on new subjects and 4 one-pass orbit renders (15).
- Round 7, sessions 5 and 6, October 23: 43.
- Session 7, October 24: 19, including the five takes of the film a headless Claude Code session made through the MCP (`tk_20261024_192756_a60e` is the film).
- Session 8, October 25: the Dutch angle take `v9b-dutch-angle-noir`. GPU session 9, October 25: 21.

That is 163 recorded and kept at the time. 28 of them left the bundle on October 25, which left the 135 that shipped that day. On October 26 four more landed and two left, so 137 ship.

**What was kept out, and why.**

- **Five left before session 9**: the October 20 keyframed arc right, track left and crane down, an early dolly zoom and the first bullet time.
- **Twenty-three left after the motion meter ran over every bundled take.** Most bundled orbit takes were the subject turning in front of a still camera. Every through-object take pulled back out of the opening. Two hyperlapses lost their subject. A few more takes did not show the move their label names. Their rows stay in `showcase/report.json` with the reason.
- **Twenty-three of the 66 takes rendered on October 23 did not hold.** The first four bridges washed out, cut or dissolved. The Dutch angle kept rolling past its tilt twice. The super dolly in failed twice. Ruin had a light stand drift through the frame.
- **Five of the October 22 takes on new subjects** stayed out: the rooftop orbit rolled the camera upside down, the crash zoom pulled back instead of in, the snorricam read as a pull-back, and the two kitchen takes carry a blown-white frame.
- **The planned Draft render of the 26 older untested moves did not run.** The box stopped when the account's credit ran out.

The Lobby's loops and posters are cut from the takes by `scripts/make_previews.py`: every take gets 2.5-second muted loops 384, 768 and up to 1280 pixels wide (never wider than the take), and the page takes the narrowest that fills its frame on the screen in use; each of its stills gets a copy up to 768 pixels wide.

With all 137 bundled takes the static export holds about 746 MB of media (778 MB in all, as the release check measures it), under GitHub Pages' 1 GB limit.

## The first visit and the pixels

Measured on October 27 on the local export, served without gzip (GitHub Pages gzips the text, so the Pages figure counts every text file at gzip -9), twelve seconds after opening the Lobby with motion allowed (`scripts/ui/transfer.mjs`):

| Visit | Before the round (Oct 27 morning) | After the round | After the hero (Oct 27 night) | Of which video, after the hero |
|---|---|---|---|---|
| Desktop 1440x900 at 1x | 7.67 MB | 6.61 MB (Pages 5.33 MB) | 8.18 MB (Pages 6.89 MB) | the 1280px trailer 6.29 MB, no loops yet |
| Desktop 1440x900 at 2x | about 9.95 MB (computed) | 9.44 MB (Pages 8.16 MB) | 8.18 MB (Pages 6.89 MB) | the 1280px trailer 6.29 MB, no loops yet |
| Phone 390x844 at 3x | 4.02 MB | 3.74 MB (Pages 2.45 MB) | 3.71 MB (Pages 2.42 MB) | the 640px trailer 1.82 MB, no loops |
| Desktop at 1x with Save-Data | no video | 1.85 MB (Pages 0.62 MB) | 1.81 MB (Pages 0.59 MB) | none |

The hero (the night of October 27): the trailer runs across the whole Lobby, so every window 1100px and wider plays the 1280px copy whatever its density (a 1024px copy stretched over 1366px read soft), and the poster wall now sits under the first screen, so no poster loop plays in the first twelve seconds. A 1x desktop's first visit grew by 1.6 MB for a sharp hero; a 2x desktop's shrank by 1.3 MB.

What changed: the hosted manifest lists its recorded takes by id and carries only the four identity fields the page reads (1.10 MB to 0.62 MB raw, 95 KB to 55 KB gzipped); every take has a 768px loop beside the 384px and 1280px ones, so a 1x desktop's gallery frames fetch about a quarter of the bytes they did and a 2x desktop's Takes wall draws sharp (`lib/pictures.js` picks the narrowest copy that fills a frame's pixels, up to 2x; a phone and a data saver keep the 384px loop); the Takes list, the Moves cards and the Shots board no longer load full posters and stills (579 KB to 1.5 MB each) into thumbnails. The 896x512 draft takes among the 44 camera moves stay at their native size on the move page: only a GPU session can sharpen them.

Frame times (`scripts/ui/frames.mjs`, headless Chrome at 1440x900, 600 frames while the pointer sweeps the stage at 60 Hz for ten seconds): on the Takes wall with twelve loops playing, the sweep crossing tiles (each one pinning its loop, drawing its path chip and scrubbing), median 13.3 ms, p95 13.5 ms, longest 26.7 ms, no frame over 32 ms, the main thread busy 75% of the time; on the Lobby median 13.3 ms, p95 13.4 ms, one frame of 40 ms in the 600, the main thread busy 21%. A room change between Takes and Direct still costs one long frame (about 250 ms, the wall of 137 tiles laid out), as it did before this round.

## Render times and cost

The machine: a rented RTX 5090 (32 GB) on Vast.ai at about $0.71 per hour, Ubuntu 24.04, ComfyUI 0.41.0, PyTorch 2.11.0 (cu128), reached through comfy-api-proxy over an SSH tunnel.

Per step, typical:

| Step | Model and size | Typical time |
|---|---|---|
| Still (hero or anchor) | Qwen-Image 2.1, 1344×768 or 1024×1024, 25 steps | 21 to 30 s |
| Keyframed shot, 5 s | LTX 2.5 first-to-last frame, 1280×704, two-stage with the x2 latent upscaler, with audio | about 85 s |
| Prompt-only shot, 5 s | LTX 2.5 image-to-video, 1280×704, with audio | about 68 s |

A keyframed take (two stills and one shot) finishes in about 135 s. A prompt-only take in about 98 s. **A 5-second shot costs 2 to 3 cents of rented GPU time.**

Other measured points, from the tables in `docs/benchmarks.md`: on October 22 the Draft tier took 81 s, Standard 137 s and Fine (1920×1088) 304 s, and a ten-second keyframed shot took 208 s. On October 23 a Shots board took 206 to 212 s, an edit 24 to 43 s, the push bridge 61 s, the face-only re-shoot 251 s, a dub 63 to 86 s, an extension 46 to 48 s and the 2K upscale of a Draft take 121 s. On the second box a transformation take ran 204 to 298 s against 134 to 141 s on October 22.

What each session cost:

- Round 7, session 5, night of October 22 to 23: RTX 5090 on Vast.ai at $0.71 an hour, about $2.19.
- Round 7, session 6, morning of October 23: RTX 5090 in Estonia at $0.79 an hour, about $3.20 projected for its lease.
- Session 7, October 24: RTX 5090 in Seoul. The runner ran on the box, because the relay carried 25 to 200 KB/s. Cost not recorded.
- Session 8, October 25: the same box as session 7 (Vast.ai instance 57539009), destroyed on the owner's word when the work was done. The credit went from $4.71 to $4.01 over its last hour and a half, about $0.70.
- Session 9, October 25: a new RTX 5090 (instance 57668144) at about $0.71 an hour, destroyed at the end. About $2.16.

The takes that shipped, the 136 whose receipts record a GPU time, took 5.6 GPU hours between them: about $3.97 at $0.71 an hour (the corridor dolly zoom of October 26 rendered on a box shared with other work, and its receipt counts all 770 seconds of its three runs, including the time the first one spent in the queue; a receipt is never rewritten). The Takes room shows the same sum. The sessions above cost more, because they also paid for the failed tries, the model downloads and the time a box sat idle.

## Known limits

- **The hosted copy shipped three of the five Cast members until October 26.** Noor and Tomas were added to the Cast on October 22 and never copied into the bundle's cast folder, so on the hosted copy their takes, the hero among them, read "Needs a backend" instead of Recreate. All five ship now, and the release gate (`scripts/release_check.py`) runs the hosted copy's smoke test on a full export, not only the small fixture set that hid it.
- The receipt is a checksum over canonical JSON, not a signature. Anyone can re-seal an edited copy. The face check is a consistency aid, not proof of identity, and it says n/a for stylised, product or faceless shots.
- Five of the 49 moves are untested, with the reason each one fails given above. 31 of the 96 camera positions are untested too. An angle is a prompt directive, not a measurement.
- Comfy Cloud is not measured. A key passed the connection check on October 22; no take has been rendered there. Every render and every number here comes from a rented RTX 5090 behind comfy-api-proxy. Replay and the hosted demo play recorded runs, and an edited recipe is refused.
- The Re-shoot source is a clip rendered with LTX 2.5, and no real person was filmed. Wan Animate 2 works at 482×854 or 854×482 and centre-crops. Coverage does not work with it either. The re-angled reference stills hold, and the pass still keeps the source clip's viewpoint.
- Out of scope, and said so: cloning a voice, lip-syncing recorded audio to a face, training an identity from photos, and re-angling a finished video. Not built: skin retouching, which needs a model we have not added, plus video background removal, outpainting and ad templates made from a link.
- Nine setups are nine separate edits of one still, so a face can drift between them. Each is checked once and re-rolled once. An edit is a prompt directive, not a mask, so it can change more than was asked.
- The face-only re-shoot is a new performance of the clip from its first frame, and the face must be visible there. Its tested mark rests on one take. A dub rests on two dubs of one take.
- A loop pins only the picture. An extension starts from one frame, so the pace and the sound do not carry across the join. An upscale redraws fine detail from each frame with a GAN and adds nothing to the shot.
- *What happens* is words in the prompt. Of the nine takes rendered with an action (eight are still in the bundle), five held.
- The models are open weights, each under its own licence. Qwen-Image 2.1 is non-commercial and requires "Built with Qwen".

## Left out on purpose, October 27

Ideas read in the field this week that would fit the studio, with the hours each would take on this stack. None is built, so none is claimed; they are listed so the next session does not rediscover them.

- A draggable 3D camera sphere to pick a position: 10 to 14 hours. The planned camera and the named positions cover the same ground with words and a drag on the preview.
- An output self-check with CLIP or OWLv2 that says whether the shot did what the prompt asked: 8 to 10 hours, two model downloads, and a calibration run over the bundle before it could be trusted to speak.
- A plain-words effect builder, a logline-to-trailer agent over the Chat room's tools, a Windows one-click installer, and a per-take optical-flow verdict in the receipt from the meter used for the arcs above: 6 to 14 hours each. Every effect shown must have a recorded take behind it, so a builder is a render and a check per effect, not an evening of code.
- Two to three days each, after the contest: expanding a still on a padded canvas, more grade presets with a recorded take behind each, a breakdown page that lays a take's stills, prompts and receipt out as one story, the moves other tools list and we do not (head tracking, object point of view, wiggle, incline, double dolly, a flying-camera transition, timelapse looks), four candidate stills at once, an emotion chip for the person, extending a take backwards, and a receipt signed with a published key.
