# Render times

Every number here was measured on a real run, by `openfield showcase --benchmarks` unless a row says otherwise; nothing is estimated.

## Machine

A rented **RTX 5090 (32 GB)** on Vast.ai at about $0.71 per hour, Ubuntu 24.04, ComfyUI 0.41.0, PyTorch 2.11.0 (cu128),
all models in the official templates' int8 and bf16 files, reached through `comfy-api-proxy` over an SSH tunnel. The
50 GB of Wan and Qwen files downloaded in a few minutes on that host's link; LTX 2.5 added about 40 GB.

## Per step, typical

| Step | Model and size | Typical time |
|---|---|---|
| Still (hero or anchor) | Qwen-Image 2.1, 1344x768 or 1024x1024, 25 steps | 21 to 30 s |
| Keyframed shot, 5 s | LTX 2.5 first-to-last frame, 1280x704, two-stage with the x2 latent upscaler, with audio | about 85 s |
| Prompt-only shot, 5 s | LTX 2.5 image-to-video, 1280x704, with audio | about 68 s |
| Character portrait | Qwen-Image 2.1, 1024x1024 | about 20 s |

A keyframed take (two stills and one shot) finishes in about 135 s; a prompt-only take in about 98 s. The first job after
ComfyUI starts adds model loading time (the first still took 30 s rather than 22 s).

## The keyframing experiment, 2026-10-20

| Take | Kind | Steps | Seconds per step | Total |
|---|---|---|---|---|
| mara-dolly-in-keyframed | direct | 3 | qwen21_edit 22s, qwen21_edit 21s, ltx25_flf2v 85s | 130s |
| mara-dolly-in-prompt | direct | 2 | qwen21_edit 28s, ltx25_i2v 68s | 97s |
| oskar-dolly-in-keyframed | direct | 3 | qwen21_edit 22s, qwen21_edit 22s, ltx25_flf2v 86s | 131s |
| oskar-dolly-in-prompt | direct | 2 | qwen21_edit 29s, ltx25_i2v 68s | 98s |
| mara-orbit-90-keyframed | direct | 3 | qwen21_edit 28s, qwen21_edit 22s, ltx25_flf2v 86s | 136s |
| mara-orbit-90-prompt | direct | 2 | qwen21_edit 28s, ltx25_i2v 68s | 97s |
| oskar-orbit-90-keyframed | direct | 3 | qwen21_edit 29s, qwen21_edit 21s, ltx25_flf2v 86s | 137s |
| oskar-orbit-90-prompt | direct | 2 | qwen21_edit 29s, ltx25_i2v 69s | 98s |
| mara-crane-up-keyframed | direct | 3 | qwen21_edit 28s, qwen21_edit 22s, ltx25_flf2v 85s | 136s |
| mara-crane-up-prompt | direct | 2 | qwen21_edit 29s, ltx25_i2v 69s | 98s |
| oskar-crane-up-keyframed | direct | 3 | qwen21_edit 29s, qwen21_edit 22s, ltx25_flf2v 86s | 137s |
| oskar-crane-up-prompt | direct | 2 | qwen21_edit 29s, ltx25_i2v 68s | 98s |
| mara-arc-left-keyframed | direct | 3 | qwen21_edit 28s, qwen21_edit 22s, ltx25_flf2v 85s | 136s |
| mara-arc-left-prompt | direct | 2 | qwen21_edit 30s, ltx25_i2v 70s | 100s |
| oskar-arc-left-keyframed | direct | 3 | qwen21_edit 29s, qwen21_edit 22s, ltx25_flf2v 89s | 141s |
| oskar-arc-left-prompt | direct | 2 | qwen21_edit 29s, ltx25_i2v 69s | 98s |
| mara-track-right-keyframed | direct | 3 | qwen21_edit 29s, qwen21_edit 22s, ltx25_flf2v 85s | 137s |
| mara-track-right-prompt | direct | 2 | qwen21_edit 29s, ltx25_i2v 68s | 98s |
| oskar-track-right-keyframed | direct | 3 | qwen21_edit 29s, qwen21_edit 22s, ltx25_flf2v 87s | 138s |
| oskar-track-right-prompt | direct | 2 | qwen21_edit 28s, ltx25_i2v 69s | 98s |

Comfy Cloud was not used for these takes; its times are not known. On October 22 a key passed the health check and a draft-tier submission was refused with "This key is not allowed to do that", so the path is wired but unmeasured.

## The showcase, 2026-10-20

The 22 Direct takes bundled with the app (10 shots and the 12-move sheet), as recorded by `openfield showcase --benchmarks`. Steps are the per-step model runs; a retried still counts as a step.

| Take | Kind | Steps | Seconds per step | Total |
|---|---|---|---|---|
| mara-market-dolly-in | direct | 3 | qwen21_edit 30s, qwen21_edit 22s, ltx25_flf2v 88s | 141s |
| mara-rooftop-crane-up | direct | 3 | qwen21_edit 29s, qwen21_edit 22s, ltx25_flf2v 86s | 138s |
| oskar-pier-orbit | direct | 2 | qwen21_edit 29s, ltx25_i2v 71s | 101s |
| oskar-closeup-static | direct | 2 | qwen21_edit 29s, ltx25_i2v 59s | 90s |
| ines-canal-track | direct | 2 | qwen21_edit 29s, ltx25_i2v 69s | 99s |
| ines-cafe-arc | direct | 3 | qwen21_edit 29s, qwen21_edit 20s, ltx25_i2v 71s | 121s |
| thermos-orbit | direct | 5 | qwen21_t2i 26s, qwen21_edit 23s, qwen21_edit 22s, ltx25_flf2v 66s, ltx25_flf2v 45s | 184s |
| thermos-dolly-out | direct | 3 | qwen21_t2i 26s, qwen21_edit 23s, ltx25_flf2v 87s | 136s |
| lighthouse-zoom | direct | 3 | qwen21_t2i 27s, qwen21_edit 23s, ltx25_flf2v 89s | 140s |
| harbour-dolly-out | direct | 3 | qwen21_t2i 26s, qwen21_edit 22s, ltx25_flf2v 87s | 136s |
| sheet-static | direct | 2 | qwen21_edit 30s, ltx25_i2v 70s | 102s |
| sheet-dolly-in | direct | 3 | qwen21_edit 30s, qwen21_edit 22s, ltx25_flf2v 85s | 138s |
| sheet-dolly-out | direct | 3 | qwen21_edit 29s, qwen21_edit 21s, ltx25_flf2v 88s | 140s |
| sheet-optical-zoom-in | direct | 3 | qwen21_edit 30s, qwen21_edit 22s, ltx25_flf2v 88s | 141s |
| sheet-orbit-90 | direct | 2 | qwen21_edit 29s, ltx25_i2v 70s | 101s |
| sheet-orbit-180 | direct | 5 | qwen21_edit 29s, qwen21_edit 22s, qwen21_edit 22s, ltx25_flf2v 52s, ltx25_flf2v 32s | 160s |
| sheet-arc-left | direct | 2 | qwen21_edit 29s, ltx25_i2v 70s | 100s |
| sheet-arc-right | direct | 3 | qwen21_edit 29s, qwen21_edit 22s, ltx25_flf2v 88s | 140s |
| sheet-track-left | direct | 3 | qwen21_edit 29s, qwen21_edit 22s, ltx25_flf2v 88s | 140s |
| sheet-track-right | direct | 2 | qwen21_edit 29s, ltx25_i2v 71s | 101s |
| sheet-crane-up | direct | 3 | qwen21_edit 29s, qwen21_edit 21s, ltx25_flf2v 86s | 138s |
| sheet-crane-down | direct | 3 | qwen21_edit 30s, qwen21_edit 22s, ltx25_flf2v 88s | 141s |

## Re-shoots, references and effects (Oct 21, RTX 5090)

| Take | Kind | Steps | Seconds per step | Total |
|---|---|---|---|---|
| dance-source | direct | 2 | qwen21_t2i 34s, ltx25_i2v 120s | 154s |
| ref-mara | direct | 2 | qwen21_edit 48s, ltx25_i2v 114s | 161s |
| ref-oskar | direct | 2 | qwen21_edit 52s, ltx25_i2v 126s | 177s |
| ref-ines | direct | 2 | qwen21_edit 55s, ltx25_i2v 120s | 176s |
| reshoot-mara | reshoot | 1 | wan_animate2 206s | 206s |
| reshoot-oskar | reshoot | 1 | wan_animate2 187s | 187s |
| reshoot-ines | reshoot | 1 | wan_animate2 186s | 186s |
| fx-rain | direct | 2 | qwen21_edit 46s, ltx25_i2v 126s | 172s |
| fx-lightning | direct | 2 | qwen21_edit 57s, ltx25_i2v 121s | 178s |
| fx-dust | direct | 2 | qwen21_edit 49s, ltx25_i2v 115s | 164s |

## Round 5: angles, transformations, one pass, signature moves (Oct 22, RTX 5090)

| Take | Kind | Steps | Seconds per step | Total |
|---|---|---|---|---|
| from-image-mara | direct | 2 | qwen21_edit 26s, ltx25_flf2v 88s | 115s |
| quality-draft-dolly-in | direct | 3 | qwen21_edit 18s, qwen21_edit 9s, ltx25_flf2v 54s | 81s |
| quality-standard-dolly-in | direct | 3 | qwen21_edit 27s, qwen21_edit 23s, ltx25_flf2v 86s | 137s |
| quality-fine-dolly-in | direct | 3 | qwen21_edit 52s, qwen21_edit 53s, ltx25_flf2v 197s | 304s |
| angle-oskar-front-eye-wide | direct | 3 | qwen21_edit 23s, qwen21_edit 23s, ltx25_i2v 70s | 118s |
| fx-ignite | direct | 3 | qwen21_edit 23s, qwen21_edit 23s, ltx25_flf2v 88s | 134s |
| fx-freeze | direct | 3 | qwen21_edit 27s, qwen21_edit 23s, ltx25_flf2v 87s | 139s |
| fx-gold | direct | 3 | qwen21_edit 28s, qwen21_edit 23s, ltx25_flf2v 87s | 138s |
| fx-bloom | direct | 3 | qwen21_edit 28s, qwen21_edit 23s, ltx25_flf2v 89s | 141s |
| fx-night | direct | 3 | qwen21_edit 28s, qwen21_edit 23s, ltx25_flf2v 87s | 139s |
| angle-oskar-front-right-eye-medium | direct | 3 | qwen21_edit 28s, qwen21_edit 22s, ltx25_i2v 70s | 121s |
| angle-oskar-right-eye-medium | direct | 3 | qwen21_edit 28s, qwen21_edit 22s, ltx25_i2v 70s | 121s |
| angle-oskar-back-right-eye-medium | direct | 4 | qwen21_edit 28s, qwen21_edit 22s, qwen21_edit 20s, ltx25_i2v 70s | 140s |
| angle-oskar-back-eye-medium | direct | 3 | qwen21_edit 28s, qwen21_edit 22s, ltx25_i2v 70s | 121s |
| angle-oskar-back-left-eye-medium | direct | 4 | qwen21_edit 27s, qwen21_edit 22s, qwen21_edit 20s, ltx25_i2v 70s | 141s |
| angle-oskar-left-eye-medium | direct | 3 | qwen21_edit 30s, qwen21_edit 23s, ltx25_i2v 70s | 124s |
| angle-oskar-front-left-eye-medium | direct | 3 | qwen21_edit 28s, qwen21_edit 22s, ltx25_i2v 70s | 121s |
| angle-oskar-front-low-medium | direct | 3 | qwen21_edit 28s, qwen21_edit 21s, ltx25_i2v 70s | 121s |
| angle-oskar-front-elevated-medium | direct | 3 | qwen21_edit 28s, qwen21_edit 22s, ltx25_i2v 70s | 121s |
| angle-oskar-front-high-medium | direct | 3 | qwen21_edit 28s, qwen21_edit 22s, ltx25_i2v 70s | 121s |
| angle-oskar-front-eye-close | direct | 3 | qwen21_edit 28s, qwen21_edit 22s, ltx25_i2v 70s | 121s |
| sp-orbit-180 | direct | 5 | qwen21_edit 28s, qwen21_edit 23s, qwen21_edit 22s, qwen21_edit 20s, ltx25_flf2v 92s | 186s |
| sp-orbit-360 | direct | 5 | qwen21_edit 30s, qwen21_edit 22s, qwen21_edit 22s, qwen21_edit 22s, ltx25_flf2v 99s | 197s |
| sig-crash-zoom-in | direct | 2 | qwen21_edit 28s, ltx25_i2v 70s | 99s |
| sig-dolly-zoom | direct | 2 | qwen21_edit 28s, ltx25_i2v 70s | 100s |
| sig-snorricam | direct | 2 | qwen21_edit 28s, ltx25_i2v 71s | 101s |
| sig-through-object | direct | 2 | qwen21_edit 28s, ltx25_i2v 70s | 100s |
| sig-hyperlapse | direct | 2 | qwen21_edit 28s, ltx25_i2v 71s | 100s |
| sig-lazy-susan | direct | 2 | qwen21_t2i 25s, ltx25_i2v 70s | 95s |
| sig-crash-zoom-out | direct | 2 | qwen21_edit 28s, ltx25_i2v 70s | 100s |
| sig-eyes-in | direct | 2 | qwen21_edit 28s, ltx25_i2v 70s | 100s |
| ten-second-dolly-in | direct | 3 | qwen21_edit 28s, qwen21_edit 22s, ltx25_flf2v 156s | 208s |

## Round 6: dialogue, coverage gate, one-pass sweep, new subjects (the evening of Oct 22, RTX 5090)

| Take | Kind | Steps | Seconds per step | Total |
|---|---|---|---|---|
| sp-orbit-180 | direct | 5 | qwen21_edit 3s, qwen21_edit 3s, qwen21_edit 4s, qwen21_edit 4s, ltx25_flf2v 80s | 94s |
| sp-orbit-360 | direct | 5 | qwen21_edit 4s, qwen21_edit 3s, qwen21_edit 3s, qwen21_edit 3s, ltx25_flf2v 85s | 98s |
| dlg-mara-calm | direct | 2 | qwen21_edit 32s, ltx25_i2v 96s | 130s |
| dlg-oskar-gruff | direct | 2 | qwen21_edit 33s, ltx25_i2v 65s | 100s |
| dlg-ines-whisper | direct | 3 | qwen21_edit 29s, qwen21_edit 20s, ltx25_i2v 66s | 118s |
| cov-oskar-left | reshoot | 1 | wan_animate2 179s | 181s |
| cov-oskar-back | reshoot | 1 | wan_animate2 172s | 174s |
| cov-oskar-front-right | reshoot | 1 | wan_animate2 365s | 367s |
| noor-observatory-dolly-in | direct | 3 | qwen21_edit 108s, qwen21_edit 96s, ltx25_flf2v 167s | 372s |
| noor-observatory-crash-zoom | direct | 2 | qwen21_edit 21s, ltx25_i2v 133s | 155s |
| noor-rooftop-orbit-90 | direct | 2 | qwen21_edit 43s, ltx25_i2v 155s | 199s |
| noor-ignite | direct | 3 | qwen21_edit 27s, qwen21_edit 122s, ltx25_flf2v 222s | 374s |
| tomas-kitchen-snorricam | direct | 2 | qwen21_edit 84s, ltx25_i2v 142s | 229s |
| tomas-kitchen-dolly-out | direct | 3 | qwen21_edit 30s, qwen21_edit 120s, ltx25_flf2v 184s | 336s |
| tomas-alley-hyperlapse | direct | 2 | qwen21_edit 24s, ltx25_i2v 122s | 147s |
| tomas-gold | direct | 3 | qwen21_edit 28s, qwen21_edit 70s, ltx25_flf2v 149s | 247s |
| desert-highway-hyperlapse | direct | 2 | qwen21_t2i 20s, ltx25_i2v 156s | 177s |
| lighthouse-storm-crane-up | direct | 3 | qwen21_t2i 32s, qwen21_edit 89s, ltx25_flf2v 172s | 294s |
| thermos-orbit (one pass, guide strength 0.4) | direct | 4 | qwen21_t2i 19s, qwen21_edit 39s, qwen21_edit 23s, ltx25_flf2v 184s | 265s |
| sheet-orbit-180 (one pass, guide strength 0.4) | direct | 4 | qwen21_edit 25s, qwen21_edit 69s, qwen21_edit 22s, ltx25_flf2v 144s | 262s |

## Round 7, session 5: Shots, edits, dubs, new moves (the night of Oct 22 to 23, RTX 5090)

A rented RTX 5090 on Vast.ai at $0.71 per hour, set up as above; about $2.19 for the session. One row per take that was kept; the takes that did not hold are left out. The two rows marked "total from the log" were put together from the records this table is written from (each step's `run.json`, and the total the run printed) because that run stopped before it wrote its report. Times on this box varied: v1-lava-surfer's still took 685 s, v1-mara-skydive's 32 s.

| Take | Kind | Steps | Seconds per step | Total |
|---|---|---|---|---|
| v1-mara-skydive | direct | 2 | qwen21_edit 32s, ltx25_i2v 86s | 119s |
| v1-lava-surfer | direct | 2 | qwen21_t2i 685s, ltx25_i2v 494s | 1180s |
| v1-shots-noor-mars | shots | 9 | qwen21_edit 32s, qwen21_edit 22s, qwen21_edit 22s, qwen21_edit 22s, qwen21_edit 22s, qwen21_edit 22s, qwen21_edit 22s, qwen21_edit 22s, qwen21_edit 23s | 212s |
| v1-shots-tomas-samurai | shots | 9 | qwen21_edit 22s, qwen21_edit 21s, qwen21_edit 27s, qwen21_edit 21s, qwen21_edit 22s, qwen21_edit 22s, qwen21_edit 22s, qwen21_edit 22s, qwen21_edit 22s | 206s |
| v1-edit-face-swap | edit | 1 | qwen21_edit 35s | 36s |
| v1-edit-person-swap | edit | 1 | qwen21_edit 27s | 29s |
| v1-edit-remove | edit | 1 | qwen21_edit 22s | 24s |
| v1-edit-outfit | edit | 1 | qwen21_edit 22s | 24s |
| v1-edit-relight | edit | 1 | qwen21_edit 22s | 24s |
| v1-edit-custom | edit | 2 | qwen21_edit 22s, qwen21_edit 20s | 43s |
| v1-dub-mara-es | direct | 1 | ltx25_i2v 85s | 86s |
| v1-dub-mara-fr | direct | 1 | ltx25_i2v 61s | 63s |
| v2-bullet-time (total from the log) | direct | 2 | qwen21_t2i 28s, ltx25_i2v 92s | 120s |
| v2-aerial-pullback (total from the log) | direct | 2 | qwen21_edit 31s, ltx25_i2v 85s | 118s |

## Round 7, session 6: re-rolls, effects, loops, extensions, an upscale, a bridge (the morning of Oct 23, RTX 5090)

Another rented RTX 5090 on Vast.ai, in Estonia, at $0.79 per hour (about $3.20 projected for its lease), with the same ComfyUI 0.41.0 and PyTorch 2.11.0. Steps took longer on this box than on the first: a transformation take took 204 to 298 s here against 134 to 141 s on October 22. One row per take that was kept; the three rows marked "total from the log" were put together as above, because the box stopped before the run wrote its report.

| Take | Kind | Steps | Seconds per step | Total |
|---|---|---|---|---|
| v1b-tomas-samurai-draw | direct | 2 | qwen21_edit 41s, ltx25_i2v 178s | 221s |
| v1b-noor-mars-orbit | direct | 5 | qwen21_edit 67s, qwen21_edit 51s, qwen21_edit 20s, qwen21_edit 22s, ltx25_flf2v 161s | 324s |
| v1b-ines-ride | direct | 2 | qwen21_edit 48s, ltx25_i2v 125s | 174s |
| v1b-cat-dj-zoom | direct | 2 | qwen21_t2i 42s, ltx25_i2v 126s | 168s |
| v1b-reshoot-face-noor-pier | reshoot | 2 | qwen21_edit 53s, wan_animate2 196s | 251s |
| v2-fisheye | direct | 2 | qwen21_edit 48s, ltx25_i2v 127s | 176s |
| v2-yoyo-zoom | direct | 2 | qwen21_t2i 40s, ltx25_i2v 144s | 185s |
| v2-fx-bts | direct | 3 | qwen21_edit 49s, qwen21_edit 60s, ltx25_flf2v 188s | 298s |
| v2-fx-vanish | direct | 3 | qwen21_edit 47s, qwen21_edit 33s, ltx25_flf2v 143s | 224s |
| v2-fx-clones | direct | 3 | qwen21_edit 46s, qwen21_edit 28s, ltx25_flf2v 142s | 216s |
| v2-fx-comic | direct | 3 | qwen21_edit 45s, qwen21_edit 24s, ltx25_flf2v 162s | 232s |
| v2-fx-painting | direct | 3 | qwen21_edit 50s, qwen21_edit 24s, ltx25_flf2v 138s | 214s |
| v2-fx-melt | direct | 3 | qwen21_t2i 39s, qwen21_edit 25s, ltx25_flf2v 140s | 204s |
| v2-fx-flood | direct | 3 | qwen21_edit 43s, qwen21_edit 24s, ltx25_flf2v 142s | 211s |
| v2-fx-age | direct | 3 | qwen21_edit 41s, qwen21_edit 23s, ltx25_flf2v 140s | 205s |
| v2-fx-snowfall | direct | 3 | qwen21_t2i 36s, qwen21_edit 30s, ltx25_flf2v 139s | 205s |
| v2-fx-time-freeze | direct | 3 | qwen21_edit 45s, qwen21_edit 20s, ltx25_i2v 149s | 215s |
| v2-fx-slow-motion | direct | 2 | qwen21_t2i 39s, ltx25_i2v 144s | 184s |
| v3-loop-storm-waves | direct | 2 | qwen21_t2i 45s, ltx25_flf2v 155s | 200s |
| v3-loop-campfire | direct | 2 | qwen21_t2i 40s, ltx25_flf2v 140s | 180s |
| v3-loop-neon-rain | direct | 2 | qwen21_t2i 39s, ltx25_flf2v 140s | 179s |
| v3-loop-camera-dolly | direct | 5 | qwen21_t2i 41s, qwen21_edit 30s, qwen21_edit 26s, qwen21_edit 22s, ltx25_flf2v 159s | 279s |
| v3-spin-sneaker | direct | 2 | qwen21_t2i 41s, ltx25_i2v 131s | 172s |
| v5-extend-lava | extend | 1 | ltx25_i2v 44s | 46s |
| v5-extend-ines-canal | extend | 1 | ltx25_i2v 45s | 48s |
| v6-upscale-draft-2k | upscale | 1 | esrgan_upscale 120s | 121s |
| v1c-oskar-skate-dolly (total from the log) | direct | 2 | qwen21_edit 50s, ltx25_i2v 144s | 197s |
| v1c-dragon-glide-wide (total from the log) | direct | 2 | qwen21_t2i 41s, ltx25_i2v 220s | 262s |
| v1c-tr-rooftop-dragon-push (total from the log) | transition | 1 | ltx25_flf2v 57s | 61s |
