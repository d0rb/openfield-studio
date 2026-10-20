# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Static HTML, CSS and ES modules served by the FastAPI app: no build step, no CDN, self-hosted fonts. Confirmed with the plan the owner approved on 2026-10-16.

## Users

Primary: a creator making short, shareable video clips alone on a laptop, usually late in the day in a dim room, reviewing footage and wanting a take they can post. Confirmed 2026-10-16.

Secondary: contest judges from Comfy, NVIDIA and LTX who open the app cold, with a "can't get it running" fallback, and decide within minutes. They succeed by acting like the creator.

## Product Purpose

OpenField Studio is an open-weights film studio built on the Comfy Developer Platform. A creator casts a character or product, directs a shot with a virtual camera rig, re-shoots a phone clip with a new character, and keeps every take with a verifiable receipt.

Success: a stranger sees real footage and a clear next action within seconds, gets a good take within a minute of connecting a backend (or sees recorded takes with no setup), and can trust the take was made with open weights only.

## Positioning

What a neighbouring product could not truthfully copy:

- Every take carries a tamper-evident receipt (prompts, seeds, workflow hash, exact model files and licences, open-weights audit, identity result) and can be remixed from the file.
- Cheap stills are approved before video compute is spent.
- Only open-weights models run, through the Comfy Developer Platform, on Comfy Cloud, the owner's own GPU box, or from recorded takes.

## Operating Context

Long sessions on a dim screen, reviewing footage: the interface must stay colour-neutral so the footage is the only saturated thing. Renders take minutes, so waiting, progress, queue and failure states are core, not edge cases. Three backends: Comfy Cloud, a GPU box behind comfy-api-proxy (reached over an SSH tunnel), and Replay (recorded takes, no key and no GPU). Contest: Open Source Higgsfield by Comfy, deadline 2026-10-30 09:00 PT.

## Capabilities and Constraints

- Stations: Cast (reference sets with consent), Direct (camera rig, 35 moves in 7 groups, approve stills, then shoot), Re-shoot (motion transfer onto a new character), Takes (ledger, receipts, remix, export).
- Models: LTX 2.5 (video and audio), Qwen-Image 2.1 (stills), Wan Animate 2 (motion transfer). No partner or API nodes.
- Only validated moves are promoted in the UI; the rest sit under "More (experimental)".
- The face check is local, report-only, with at most one automatic re-roll; faceless shots read "n/a".
- Replay never fakes a render: a recipe that was not recorded is refused with an explanation.
- Undecided: which moves get promoted after the showcase renders.

## Brand Commitments

Name: OpenField Studio. Station names Cast, Direct, Re-shoot, Takes are confirmed; "OpenJutsu" may name the Re-shoot mode. Original copy only: no Higgsfield product names or marketing phrases in the UI.

Visual direction (chosen 2026-10-17): the category standard, played straight. A dark, colour-neutral AI-video workbench (prompt bar, monitor, history strip, settings panel) with one accent, held to the finish of Frame.io, Linear, Runway and DaVinci Resolve. Convention is the commitment: no ornament, no gimmick, no irony.

## Evidence on Hand

No real renders yet (2026-10-16). Showcase renders are planned for 2026-10-24 to 26: fictional characters, a product, and a clip the owner shot. Until then any imagery in the UI must be labelled synthetic. Future work must not fabricate: render times, prices, user counts, benchmarks, testimonials.

## Product Principles

1. Footage is the hero; the interface stays quiet around it.
2. Never fake a render: show recorded takes honestly, or say a backend is needed.
3. Proof over claims: every take shows its receipt and open-weights audit.
4. Cheap before expensive: approve stills before video is rendered.
5. Works first try for a stranger: no key, no GPU, one command.

## Accessibility & Inclusion

Keyboard-operable, AA contrast, state never carried by colour alone, `prefers-reduced-motion` respected, readable at 1024 px wide and up (desktop first; a phone only needs to view takes).
