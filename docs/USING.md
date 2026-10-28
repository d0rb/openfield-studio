# Using the app

The app has seven rooms, in the rail on the left: Lobby, Cast, Direct, Shots, Re-shoot, Takes and Chat. It opens in the Lobby.

## The Lobby

**The screen.** A trailer cut from recorded takes plays at the top, each cut with its own sound. The chip on the screen names the take on screen, and a click opens it. The sound stays off until you turn it on. The thin reel under the screen has one mark per cut: the cuts played are lit, and a click plays from that cut.

**The marquee** carries counts read from the data: the camera moves, the effects and the recorded takes, one at a time.

**Now showing.** Every app hangs as a poster with its key art, the models it uses and the date of the take that proves it. A poster only hangs when that feature has held on a real render. Point at one, or tab to it, and it plays that take with a ticket that shows the take's seed, length and audit. A few posters wake up on their own, three at a time on a wide screen and one on a phone.

**Camera moves.** Every move that held on a real render plays the take that shows it. The filters pick a group: Featured, All, or one of the seven groups. Run the mouse across a frame and the take follows your hand, so you can drive the camera back and forth. The corner shows the move's path from above.

Click a move to open its page. It plays the whole take beside the set seen from above, where a camera travels the move's path in step with the video. Below are the words the video model reads for that move, how it is shot, and the take's seed, length, GPU time and cost. *Direct this move* loads the take's settings into Direct. *Save with the camera's path* records the take with that camera drawn in a corner, travelling in step, plus the move's name, as a video file to post. It records in your browser while the take plays, so it takes about as long as the take. The arrow keys walk to the next move, and *Copy link* copies an address that opens this page. On the hosted copy each move has its own page that unfurls in a feed with its video.

**Effects** run on a rail: weather, light and changes on camera. Click one to start a shot with it.

**Name the move** is a quiz in the room: five clips a day, the same five for everyone (the day turns at midnight UTC), four names each. At the end you can post the day's score, a line with one square per clip, or save a score card picture. Your result and your streak stay in this browser until the next five. *Play ten at random* is there any time.

**Make your own** shows three ways to run it, with commands to copy: on your own GPU, on a rented one, or driven by your own agent.

The app prints no "tested" labels. The code's flags still decide what plays, so only a move or effect that held on a real render plays a recorded loop. `openfield verify` prints the counts.

## Direct

Describe the shot in the prompt bar, pick a move on the Move Pad and press **Shoot** (Ctrl or Cmd + Enter). The stills come first and stop for your approval. Approve them, or redo any one, and only then does the video render.

**The stage view** at the top of the Move Pad, and small on the Monitor, shows the move as planned: the subject's mark, the camera's path, a numbered mark at each still you approve, and the camera with its field of view. While a take plays, the camera travels the path in step with the footage. It is the plan the stills and the prompt came from, not a measurement of the video. A move with only one still draws its camera dashed.

**Where the camera starts.** Drag the stage sideways to move the camera around the subject (eight stops, 45 degrees apart), or up and down to change its height (low, eye level, elevated, high). The dials under it set the same things and the distance (close-up, medium, wide), and they take the keyboard. When you shoot, the hero still is re-shot from that position with one Qwen-Image 2.1 edit. You approve it as *Angled still* and the move runs from there. *As shot* puts the camera back. In Takes, the **Angles** tab shows one subject from every recorded position.

**What happens** (beside the subject) is the action, up to 300 characters. Only the video model reads it. A move with two or more stills pins them to one moment, so the action may barely move. Quick mode and one-still moves leave it room.

**The Shot section.** Lens, length, speed and format set the shot. **Effect** has two kinds. *Weather and light* (rain, lightning, time freeze, dust, fog, slow motion) adds one sentence to the video prompt. *Transformations* (ignite, freeze, gold statue, bloom, day to night, age, snowfall, ruin, behind the scenes, vanish, clones, comic book, oil painting, melt, flood) edit the last still into the end state, you approve it beside the hero, and LTX 2.5 renders the change with sound. Six of them skip the face check because they change the face, and the receipt says why.

**Look** sets the camera, lens, lighting and aperture, and **Grade** adds a colour palette. **Sound and options** has the score and soundscape, **a line** for the character to say (pick a delivery and, if it is not English, the language), **Quick mode** (one still and a camera instruction instead of anchor stills) and **Skip approval**. Keep a line short: a 5-second shot carries about a dozen words.

**Quality** is Draft, Standard or Fine. A tier changes the size of the stills and the video (896×512, 1344×768 with 1280×720 video, or 1920×1088) and the steps of the stills (12, 25 or 30). LTX 2.5 always runs the same number of steps. The plan line shows a time measured on this backend from its own past renders of the same shape, or says it has none yet.

**Start from your own image.** In the Character section, set *Start from* to *My image* and drop a photo. It becomes the hero still and nothing is rendered for it. The image is centre-cropped to the tier's size. The face check compares the stills to your photo, or to the Cast character you picked. Use a photo of yourself or of someone who agreed. This needs a connected backend.

## Shots

Shots turns one still into nine setups: wide, close-up, three-quarter left and right, profile left and right, low angle, high angle and from behind. Pick a take as the source, or *My image…* for a photo. Each setup is one Qwen-Image 2.1 edit with its own face check, and the take plays the nine stills in order. No video model runs. Press a tile to *Animate this setup in Direct* or *Edit this setup…*.

## Working from a take

A finished take's **Take** tab shows its receipt as a ticket: the seed, the length, the GPU time and what it cost at $0.71 an hour, the open-weights check, the face check and the checksum. *Check it in this browser* fetches `receipt.json` and hashes it in your browser to show it has not been edited. Under the receipt are the stills, then the actions:

- **Use these settings** puts the take's settings back in Direct.
- **Transition…** flies this take into another one with one LTX 2.5 render from its last frame to the other's first. Pick the landing take, a style, a length (2, 3 or 4 s) and, if you like, how one becomes the other. Push is the style that holds.
- **Edit with words…** changes the take's still with one Qwen-Image 2.1 edit: swap the face, swap the person, remove something, change the outfit, relight, or your own words. A face or a person only comes from a Cast, where consent is recorded.
- **Dub…** shoots the take again from its own still with a new line in another language. You write the translation. It is a new render, so the picture moves a little differently.
- **Extend…** continues the shot from its last frame by 3 or 5 seconds.
- **Upscale…** takes it to 2K or 4K with Real-ESRGAN. A take too long for the memory limit is refused before anything renders.
- **Compare…** sets the take beside another one. Both play in step, and a table shows what their receipts say differently: the move, the words with the changes marked, the seed, the model files, the GPU time. It offers takes of the same subject first. *Only what differs* hides the rows that match.
- **Share…** opens the caption (with `#OpenSourceHiggsfield`), Copy link, Copy caption, links to post on X, Reddit, LinkedIn, WhatsApp or Telegram, the phone's own share sheet, Download video, and, for a Direct take, *Save with the camera's path* and *Save the shot sheet*: one picture of the take with three of its frames, the camera's path from above, the words the video model read and the receipt's facts (seed, models, GPU time and cost, the checksum), to share or print. On the hosted copy a take's link opens its own page, which unfurls with the video.
- The receipt and the exact workflows can be downloaded, and the workflows load in ComfyUI.

## Re-shoot

Add a clip and a reference image of the new character, describe them, and press Re-shoot. Wan Animate 2 keeps the movement and changes the character. It works on one person, at 482×854 or 854×482, centre-cropped. Use footage you filmed or have the right to use.

*Swap only the face* keeps the clip's look. Pick a Cast character, and a clip whose first frame shows the face clearly. The first frame gets the face, then Wan Animate 2 re-performs the clip from it.

## Loop

**Loop** is a move in Lock and aim. Its last frame is the hero again, so the clip ends on the frame it began with. Leave Quick mode off, because Quick mode drops that last frame. Only the picture is pinned, not the sound.

## The Takes wall

Takes opens on a wall where every finished take plays a short muted loop, with its move or kind, its timecode and its face check. Run the mouse across a tile to scrub it, and click to open it. At most twelve loops play at once (four on a phone), and only while they are on screen. The other filters are All, Direct, Re-shoot, Exports, Moves and Angles.

## Connecting a backend

The button in the header shows what new takes render on: Replay (recorded takes), a GPU box, or Comfy Cloud. **Connect a backend…** asks for a GPU box (the comfy-api-proxy address, and a token if it needs one) or Comfy Cloud (an API key). **Test** reports what it found and never switches: whether it is reachable, whether the token works, and, with ComfyUI's own address, which model files and nodes each workflow is missing. **Use this backend** switches new takes only. Keys and tokens stay in memory until the app closes. The hosted copy cannot connect anything. The full guide is [docs/CONNECT.md](CONNECT.md).

In Replay, anything you change that was not recorded turns Shoot into "Needs a backend". It never invents a take.

## Chat

The Chat room puts an agent in charge of the studio. It can be **OpenCode** with an open-weights model (the default when it is installed), **Claude Code** or **Codex**, each signed in on your own computer. The agent gets the studio's tools and nothing else: no shell, files or web.

Write what you want. The agent says what it will render, asks before it approves stills, and its takes appear in the rooms with their receipts. Each tool it uses shows as a line, and the stills it looks at show as pictures. **Stop** interrupts it, and renders it already started keep going. **New chat** starts over. Each chat has a cap on renders (`OPENFIELD_CHAT_RENDERS`, default 6) that holds across restarts. The room only works on a studio running on your own computer.

The same tools work from any MCP client with `openfield mcp`. See [docs/MCP.md](MCP.md).

## Keys

| Key | Does |
|---|---|
| Ctrl or Cmd + Enter | Shoot (Recreate, in Replay) |
| Space or K | Play or pause the Monitor |
| J, L | Back or forward a second |
| Left, Right | On the Move Pad: the next move. On the Monitor: one frame when paused, one second when playing. On a move's page: the next move |
| Up, Down | On the Move Pad: the next move. Elsewhere: the previous or next take in the filmstrip |
| M, F | Sound on or off, full screen |
| C | Cinema: the take alone in the window (C or Escape to come back) |
| `[` | Hide or show the settings panel |
| `?` | The list of keys |

The app works with the keyboard alone, keeps AA contrast, and folds down to a phone layout. With reduced motion turned on, or data saver, nothing plays on its own and the posters and frames show still pictures.

The interface is in `openfield/web/`: plain ES modules and CSS, self-hosted fonts and icons, no build step. Every picture in it was rendered with open-weights models, and `openfield/web/art/manifest.json` lists each one with its prompt, seed, workflow and model files.
