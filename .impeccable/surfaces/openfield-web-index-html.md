---
version: 1
slug: "openfield-web-index-html"
primary_target: "openfield/web/index.html"
related_targets: []
---

# Surface brief: the OpenField Studio app (openfield/web)

## Scope and mode

Operate. The whole studio: shell plus four stations (Direct, Re-shoot, Cast, Takes). One static ES-module app that serves both the live server and the hosted Replay, so every screen must work with recorded takes only and with a real backend.

## Audience, job, action, proof, constraints

A creator alone at a laptop in a dim room, iterating on short clips; and contest judges who open it cold and decide in minutes. Job: describe a shot, pick a camera move, approve cheap stills, shoot, then judge, remix and export the take. Action on first sight: play a recorded take and press Recreate, or describe a shot and press Shoot. Proof the screen must carry: footage first; the open-weights audit, the identity result and the receipt one click from every take; nothing faked (Replay says it is a replay, a missing backend is said plainly). Constraints: no build step, no CDN, self-hosted fonts and icons, JS under about 120 KB, AA contrast, keyboard operable, reduced motion respected, desktop first at 1024 and up with a working phone layout, original copy only (no Higgsfield names or phrases), any imagery before the showcase exists labelled synthetic.

## Chosen direction and memorable moment

The user took the standing exit: the category standard, played straight, held to the finish of Frame.io (how footage is shown and judged), Linear (controls, density, states), Runway (the category itself) and DaVinci Resolve (panels around a viewer). Convention is the commitment: no irony, no smuggled quirk. The memorable moment is not decoration: choosing a move draws its camera path with numbered anchor stills and the plan line counts the real renders, so cost and result are visible before anything is spent.

## Direction contract

THESIS: A familiar AI-video workbench at full craft: prompt bar, monitor, history strip and settings panel on a dark neutral ground with one accent. What it owns is provenance without friction: the footage is the only saturated thing, and how it was made (receipt, audit, identity) is one click from every take. It refuses the category habit of spending video compute before the stills are approved, and of hiding what a result was made from.

OWN-WORLD: Ground #0f1115, panels #14171c and #1a1d23, text #e6e8eb with cool grey secondary tones, one indigo accent #6d7cff used only for the primary action, selection and focus, muted green, amber and red for state. Inter (self-hosted) is the one family, the system monospace only for seeds, hashes and timecodes. Eight-point spacing, 8 to 10px radii, 1px hairlines, a soft offset shadow only on floating layers. Lucide icons at one stroke weight. One control vocabulary: segmented controls, sliders, selects, switches. No gradients, glass, glow or kickers. Recognizable with content removed: a 64px icon rail, a 52px top bar with a backend pill, a prompt bar over a 16:9 monitor, a filmstrip below, a 360px settings panel on the right.

STORY: In Replay the visitor sees a real recorded take, understands it was rendered with open weights, and presses Recreate; with a backend they describe a shot, pick a move, approve the stills and shoot. They believe the take is honest because its receipt, audit and identity score are right there, and they leave with a clip they can remix, open in ComfyUI or export as 9:16.

FIRST VIEWPORT: At 1440 by 900, left to right: the rail (Direct selected), then the centre column, then the 360px settings panel. The centre column stacks the prompt bar (subject field two lines tall, the primary Shoot button at its right, the plan line beneath: move, mode, "2 stills + 1 shot, 5 s"), the 16:9 monitor holding the latest take or, with none, the featured recorded take with Play and Recreate, then a filmstrip of recent takes. The panel holds the Move Pad (twelve promoted moves as path glyphs, the rest under More), look, shot, character and advanced groups. Signature interaction: the Move Pad draws the selected camera path in top and side views with numbered anchors while the plan line recounts the renders. Motion: 150 to 200 ms state changes only; the active step of the stage rail is the one moving thing during a render; nothing on load.

FORM: The category standard (the standing exit), declined from the dealt roll whose seed key was 07857be4. Operate mode, restrained colour, convention embraced.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Unresolved decisions

The accent shade may move a few steps for contrast on the dark ground. Which moves are promoted beyond the twelve candidates waits for the keyframing experiment. The wordmark is text until the user asks for a mark. Showcase imagery arrives with the first real renders; until then the dev stack's synthetic frames are labelled FAKE and never shipped.
