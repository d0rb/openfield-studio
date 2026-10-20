---
name: OpenField Studio
description: A dark, colour-neutral AI-video workbench with one indigo accent, where the footage is the only saturated thing and how a take was made is one click away.
colors:
  ground: "#0f1115"
  panel: "#14171c"
  raised: "#1a1d23"
  hover: "#21252d"
  pressed: "#272c35"
  screen: "#08090b"
  line: "#262b34"
  line-strong: "#323844"
  control-line: "#667080"
  control-line-hover: "#7a8494"
  text: "#e6e8eb"
  text-2: "#a6adb9"
  text-3: "#8d95a3"
  accent: "#6d7cff"
  accent-fill: "#5667f0"
  accent-fill-hover: "#4f5fe8"
  accent-fill-press: "#4a5ae0"
  accent-text: "#8e9bff"
  accent-soft: "rgb(109 124 255 / 0.14)"
  green: "#4cc38a"
  green-soft: "rgb(76 195 138 / 0.14)"
  amber: "#e0a63c"
  amber-soft: "rgb(224 166 60 / 0.14)"
  red: "#f2727b"
  red-soft: "rgb(242 114 123 / 0.14)"
  danger-fill: "#c73e49"
  danger-fill-hover: "#b5353f"
  on-fill: "#ffffff"
typography:
  headline:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  subtitle:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.5
  body:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.4286
  label:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 500
    lineHeight: 1
  caption:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.4
  mono:
    fontFamily: "ui-monospace, Cascadia Mono, SF Mono, Menlo, Consolas, Liberation Mono, monospace"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1
rounded:
  xs: "4px"
  s: "6px"
  m: "10px"
  pill: "999px"
spacing:
  s1: "4px"
  s2: "8px"
  s3: "12px"
  s4: "16px"
  s5: "24px"
  s6: "32px"
  s7: "48px"
components:
  button-primary:
    backgroundColor: "{colors.accent-fill}"
    textColor: "#ffffff"
    typography: "{typography.label}"
    rounded: "{rounded.s}"
    height: "32px"
    padding: "0 12px"
  button-primary-hover:
    backgroundColor: "{colors.accent-fill-hover}"
  button-primary-active:
    backgroundColor: "{colors.accent-fill-press}"
  button-primary-large:
    backgroundColor: "{colors.accent-fill}"
    textColor: "#ffffff"
    typography: "{typography.body}"
    rounded: "{rounded.s}"
    height: "40px"
    padding: "0 16px"
  button-secondary:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text}"
    typography: "{typography.label}"
    rounded: "{rounded.s}"
    height: "32px"
    padding: "0 12px"
  button-secondary-hover:
    backgroundColor: "{colors.hover}"
  button-secondary-active:
    backgroundColor: "{colors.pressed}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.text-2}"
    typography: "{typography.label}"
    rounded: "{rounded.s}"
    height: "32px"
    padding: "0 12px"
  button-ghost-hover:
    backgroundColor: "{colors.hover}"
    textColor: "{colors.text}"
  button-danger:
    backgroundColor: "{colors.danger-fill}"
    textColor: "#ffffff"
    typography: "{typography.label}"
    rounded: "{rounded.s}"
    height: "32px"
    padding: "0 12px"
  button-small:
    typography: "{typography.caption}"
    rounded: "{rounded.s}"
    height: "26px"
    padding: "0 8px"
  button-icon-only:
    rounded: "{rounded.s}"
    size: "32px"
  input:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.text}"
    typography: "{typography.label}"
    rounded: "{rounded.s}"
    height: "32px"
    padding: "0 10px"
  segmented:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.text-2}"
    typography: "{typography.caption}"
    rounded: "{rounded.s}"
    padding: "2px"
  segmented-selected:
    backgroundColor: "{colors.pressed}"
    textColor: "{colors.text}"
    height: "26px"
  switch-off:
    backgroundColor: "{colors.line-strong}"
    rounded: "{rounded.pill}"
    width: "42px"
    height: "24px"
  switch-on:
    backgroundColor: "{colors.accent-fill}"
    rounded: "{rounded.pill}"
    width: "42px"
    height: "24px"
  pill:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text-2}"
    typography: "{typography.caption}"
    rounded: "{rounded.pill}"
    height: "20px"
    padding: "0 8px"
  pill-amber:
    backgroundColor: "{colors.amber-soft}"
    textColor: "{colors.amber}"
  pill-green:
    backgroundColor: "{colors.green-soft}"
    textColor: "{colors.green}"
  pill-red:
    backgroundColor: "{colors.red-soft}"
    textColor: "{colors.red}"
  pill-accent:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.accent-text}"
  prompt-bar:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text}"
    rounded: "{rounded.m}"
    padding: "12px 12px 12px 16px"
  dock:
    backgroundColor: "{colors.panel}"
    width: "360px"
  move-tile:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text-2}"
    typography: "{typography.caption}"
    rounded: "{rounded.s}"
    height: "64px"
  move-tile-selected:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.text}"
  monitor-screen:
    backgroundColor: "{colors.screen}"
    rounded: "{rounded.m}"
  filmstrip-tile:
    backgroundColor: "{colors.screen}"
    rounded: "{rounded.s}"
    width: "132px"
  cast-card:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text}"
    rounded: "{rounded.m}"
  take-list:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.m}"
  drop-zone:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.text-2}"
    rounded: "{rounded.m}"
    padding: "16px"
  notice:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text}"
    rounded: "{rounded.m}"
    padding: "12px"
---

# Design System: OpenField Studio

## Overview

**Creative North Star: "The Edit Bay"**

OpenField Studio is the category standard played straight: a dark, colour-neutral AI-video workbench in the lineage of Frame.io (how footage is shown and judged), Linear (controls, density, states), Runway (the category itself) and DaVinci Resolve (panels around a viewer). Convention is the commitment. A 52px top bar, a 64px icon rail, a centre column with a prompt bar over a 16:9 monitor over a filmstrip, and a 360px settings dock: someone who has used any of those tools can operate it cold.

The interface stays quiet so the footage is the only saturated thing on screen. Surfaces step through six near-neutral blue-greys; text is cool grey; a single indigo accent marks the primary action, selection, focus and progress and nothing else. What the system owns is provenance without friction: the receipt, the open-weights audit and the identity score sit one click from every take, and Replay never dresses up as a render. Recognisable with content removed: rail, bar, prompt, monitor, strip, dock.

The recorded visual rejections are ornament, gimmick and irony: no gradients, glass, glow or kickers, and no quirk smuggled in to be memorable. The memorable moment is functional: choosing a camera move draws its path with numbered anchors while the plan line recounts the real renders.

**Key Characteristics:**
- Dark neutral ground, tonal layering instead of shadows; one floating-layer shadow.
- One accent (indigo), spent on action, selection, focus and progress only.
- One family (Inter), one control vocabulary (segmented, slider, select, switch), one icon stroke (Lucide, 1.5px).
- 4/8-point spacing, 6px control radius, 10px container radius, 1px hairlines.
- Motion shows state only, 120 to 400 ms, none on load, reduced motion honoured.
- Honest provenance: Replay is amber and says "a recording played back".

## Colors

A cool, near-black blue-grey ladder with one indigo accent and three muted state hues; the footage supplies all the colour.

### Primary
- **Signal Indigo** (`accent` #6d7cff): focus ring, selection borders, slider and progress fill, the active tab underline, stage-rail marks, path lines on the Move Pad. Never a large surface.
- **Indigo Fill** (`accent-fill` #5667f0, hover #4f5fe8, pressed #4a5ae0): the one filled-button colour, switch-on, checked boxes, numbered path anchors. Carries white text; the lighter `accent` does not.
- **Indigo Text** (`accent-text` #8e9bff): links, the active rail item, selected-state text on the dark ground.
- **Indigo Wash** (`accent-soft`, 14% of the accent): selected rail item, selected move tile, current take row, drop-zone hover.

### Neutral
- **Ground** (`ground` #0f1115): the page, the workspace, and the inside of inputs, so fields read as wells.
- **Panel** (`panel` #14171c): top bar, rail, dock, take list.
- **Raised** (`raised` #1a1d23): prompt bar, secondary buttons, cast cards, menus, notices.
- **Hover** (`hover` #21252d) and **Pressed** (`pressed` #272c35): interaction steps; pressed is also the selected segment.
- **Screen** (`screen` #08090b): the monitor and every thumbnail well; darker than anything else so footage sits in a black frame.
- **Hairline** (`line` #262b34) divides regions; **Hairline Strong** (`line-strong` #323844) edges containers and tracks; **Control Edge** (`control-line` #667080, hover `control-line-hover` #7a8494) is a control's own border and must hold 3:1 against the ground.
- **Text** (`text` #e6e8eb), **Text 2** (`text-2` #a6adb9) for supporting copy, **Text 3** (`text-3` #8d95a3) for hints and placeholders. Text 3 is the floor; nothing dimmer carries words.

### State
- **Pass Green** (`green` #4cc38a, wash `green-soft`): backend connected, identity pass, open-weights verified.
- **Replay Amber** (`amber` #e0a63c, wash `amber-soft`): Replay, drift, cautions, plan notes.
- **Fault Red** (`red` #f2727b, wash `red-soft`): errors, failed steps, quiet destructive text. **Danger Fill** (`danger-fill` #c73e49, hover `danger-fill-hover` #b5353f) is the solid destructive button. **On Fill** (`on-fill` #ffffff) is the only pure white: text and marks on an accent or danger fill, a switch thumb that is on, a checked box's mark.

### Named Rules
**The Footage-Only Saturation Rule.** Nothing in the chrome is saturated except the footage and the single accent. State hues appear as small pills, dots and arcs, never as panels.
**The One Accent Rule.** Indigo means act, selected, focused or in progress. A decorative use is a defect.
**The Replay Is Amber Rule.** A replayed run always carries the amber Replay pill and the words "a recording played back"; a real recorded render carries the accent "Recorded take" pill. They are never the same colour.

## Typography

**Display Font:** none. There is no display voice.
**Body Font:** Inter, variable 100 to 900, self-hosted (SIL OFL), with system-ui fallbacks.
**Label/Mono Font:** the system monospace stack (ui-monospace, Cascadia Mono, SF Mono, Menlo, Consolas), only for seeds, hashes and timecodes.

**Character:** Inter is the workhorse face of this category, chosen because it is that category's standard and offers tabular numerals for timecodes, scores and counts. The design detector's overused-font rule is waived for it on that basis (recorded in `.impeccable/config.json`). It is a UI face only, never a display voice, and swapping it is one file.

### Hierarchy
- **Headline** (600, 1.375rem/22px, -0.01em): the running-render name only.
- **Title** (600, 1.125rem/18px, -0.01em): station heading, monitor title, empty-state heading, approval heading.
- **Subtitle** (600, 1rem/16px): take header in the details dock; the prompt field text is 16px at 400.
- **Body** (400, 0.875rem/14px, 1.4286): default text, crumb, large-button label.
- **Label** (500, 0.8125rem/13px): buttons, inputs, tabs, dock-section heads (600), plan line.
- **Caption** (500, 0.75rem/12px): field labels, segmented options, pills, hints, tile names. 12px is the floor.
- **Mono** (500, 0.75rem/12px, tabular): timecodes, seeds, hashes.

### Named Rules
**The Twelve Floor Rule.** No text under 12px (`--fs-xs`). Smaller is a defect.
**The Numerals Stay Still Rule.** Numbers that change (timecodes, scores, counts, slider values) use tabular numerals.
**The Sentence Case Rule.** Labels are sentence case at rest. No uppercase, no tracked small caps, no kickers above headings.

## Layout

A three-column app grid: 64px rail, flexible workspace, 360px dock, under a 52px top bar. The workspace is a single column with 16px padding and 12 to 16px gaps: prompt bar, monitor (fills remaining height, minimum 300px), filmstrip (132px tiles). Dock sections are 40px heads over bodies padded 16px with 12px gaps. Spacing is a 4/8 grid (4, 8, 12, 16, 24, 32, 48); 12px is the working gap inside controls and panels.

The Monitor's aspect follows the footage: the screen is sized by container queries to the largest box of the take's own aspect ratio that fits, 16:9 by default and portrait when the take is 9:16. Approval stills and candidate thumbnails follow the same rule.

Responsive behaviour:
- **1180px and up:** the dock is docked in the grid and can be closed.
- **Below 1180px:** the rail stays; the dock becomes a floating panel (360px, or full width if narrower), fixed under the top bar and sliding in over the workspace with the floating shadow, so the monitor is never squeezed.
- **Below 720px:** the top bar drops to 48px, the rail becomes a 56px bottom station bar, the dock is a full-width sheet above it, the monitor is full-width at footage aspect, wordmark, crumb and button labels are hidden in favour of icons.
- **Below 760px height (720px and up):** the filmstrip heading hides and tiles shrink to 104px to keep the monitor large.

Takes rows collapse by container width: at 920px the length and identity columns drop, at 520px only thumbnail, title and state remain.

## Elevation & Depth

Tonal layering, not shadow. Depth comes from the surface ladder (ground, panel, raised, hover, pressed) and 1px hairlines. The screen sits in a darker well than anything around it.

### Shadow Vocabulary
- **Float** (`box-shadow: 0 6px 16px rgb(0 0 0 / 0.5), 0 1px 3px rgb(0 0 0 / 0.4)`): the only shadow. Used on layers that physically float: the backend menu, notices, the floating dock below 1180px, the sticky reel bar.

### Named Rules
**The Flat-Until-Floating Rule.** A surface that sits in the layout has no shadow. A surface that overlaps other content has the Float shadow and a `line-strong` border. No hard offset shadows, no glow.

## Shapes

Small, quiet radii and hairline edges. Controls (buttons, inputs, segmented, tiles, thumbnails) use 6px; containers (prompt bar, monitor, cast cards, menus, notices, take list, drop zones) use 10px; inner pieces such as segmented options, key hints and tile badges use 4px; pills, switches, the backend button and scrollbar thumbs are fully round. Checkboxes are 16px with a 4px radius; radios are circles. Dashed borders (1px, `control-line`) mean a drop target and nothing else. Footage and stills are always cropped by the container, never rounded independently. Icons are Lucide at a 1.5px stroke, 16px by default (14 small, 20 large).

## Components

### Buttons
Quiet, compact, 32px tall, 13px 500-weight label, 6px radius, 12px side padding, 8px icon gap.
- **Primary:** Indigo Fill with white text. Hover and pressed step the fill. One per view region (Shoot, Recreate, Approve).
- **Secondary:** Raised with a `line-strong` border; hover goes to Hover and the `control-line` border.
- **Ghost:** transparent, Text 2; hover fills Hover and lifts text to Text. Toggled-on ghost (`aria-pressed`) takes the Indigo Wash and Indigo Text.
- **Danger:** Danger Fill with white text, for confirmed destructive actions. **Quiet danger** is red text that washes on hover.
- **Sizes:** large 40px with 14px text (Shoot); small 26px with 12px text; icon-only is a 32px (26px small) square. Optional trailing key hint in a 18px outlined box.
- **Disabled:** 45% opacity, not-allowed cursor. Busy: progress cursor.
- **Focus:** 2px accent outline, 2px offset, on every interactive element.

### Fields, selects, sliders, switches, checks
- **Input / textarea / select:** Ground well, 1px Control Edge border, 6px radius, 32px high (textarea min 64px). Hover lightens the edge; focus is a 2px accent outline with an accent border; invalid turns the border red with an inline red message and icon. Select hides the native arrow and adds a chevron. Labels are 12px Text 2 above the field; hints 12px Text 3.
- **Segmented control:** Ground track with Control Edge, 2px inset, 26px options. Selected option fills Pressed with a `line-strong` inset ring. The vocabulary for any pick-one among a few.
- **Slider with number box:** 4px track, accent fill to the value over `line-strong`, 16px light thumb ringed in the ground colour, paired with a 64px right-aligned tabular number input.
- **Switch:** 42 by 24px pill; off is `line-strong` with a Control Edge ring, on is Indigo Fill with a white 18px knob that slides in 180 ms. Sits in a row with a 13px title and a hint.
- **Checkbox and radio:** 16px, Ground well and Control Edge border; checked fills Indigo Fill with a white mark.

### Pills
20px high, 12px 500 text, optional 6px dot. Neutral is Raised with a hairline. Tones (`data-tone`) use a soft wash and the matching hue text with no border: green (verified, connected), amber (Replay, drift), red (failed), accent (Recorded take, selected). Large pill is 24px.

### Tabs and dock sections
Tabs are 44px high, 13px 500 text, Text 2; selected is Text with a 2px accent underline on the hairline. Dock sections have a 40px head (13px, 600, chevron that rotates 90 degrees in 180 ms), a Raised hover, and a collapsible body.

### Prompt bar with plan line
A Raised, 10px-radius bar holding a 16px borderless subject field (two lines tall) and a foot row: the plan line at left and the large primary Shoot button at right. Focus-within draws the accent border and a 1px accent outline. The plan line is 13px Text 2 with bold Text key values and `text-3` separators, for example move, mode, "2 stills + 1 shot, 5 s"; it recounts real renders as options change. Cautions use an amber icon note; locked states use a quiet Text 3 note with a lock icon.

### Monitor with transport
The hero. A title (18px, 600) and pills above a Screen-black well at the footage's aspect. A 64px translucent circular Play button centres on it and fades out (180 ms) while playing. The transport row (36px) holds play, a scrub slider, and mono timecodes (`tc`, 84px). Modes: ready, empty (empty state with Play and Recreate on the featured recorded take), running (name, detail, 4px progress bar, elapsed or "Replaying", 0.45-opacity preview behind), approval, failed, canceled.
- **Stage rail** (`steps`): a bottom-docked strip of equal segments, each a 3px mark and a 12px name. Done is the accent mark; active is the lighter accent mark pulsing at 1.6 s and is the one moving thing during a render; failed is red; canceled is Text 3. Names hide on phones.
- **Approval stills:** the cheap-before-expensive gate. A 16:9 (or 9:16) still row with `line-strong` bordered images, a caption with re-roll toggle per still, and Approve (primary) and cancel actions, in a screen padded 24px.
- **Before/after comparator:** two players clipped by a CSS split variable; a 2px white divider and a 40 by 28px Raised handle with a Control Edge border; two corner tags on a black 78% scrim; `ew-resize`, touch-safe.

### Filmstrip tile
132px wide (104px short viewports, 124px phone), 16:9 Screen-black frame with a hairline border, 12px name beneath. Hover lifts the border to Control Edge; current take gets a 1px-plus-1px accent ring. Corner badges (duration at bottom right, flag at top left) sit on a 82% black scrim; flag tones: amber, accent, red. A 3px accent bar shows progress. Dead takes drop to 60% opacity until hovered or current.

### Move Pad tile and path preview
A 4-column grid of 64px-tall Raised tiles, each a 36px path glyph over a 12px name. Selected: accent border, Indigo Wash, glyph strokes in Indigo Text. Beneath: two figures (top view and side view) on Ground wells drawing the chosen path in Indigo Text with numbered white-on-indigo anchors; the path draws in over 180 ms. A "More" toggle opens the remaining moves as grouped rows.

### Identity ring and take details
A 64px ring: 5px track in `line-strong`, arc in green (pass) or amber (drift), a tick for the threshold, a tabular score at the centre. Unavailable states dash the track and dim the number to Text 3. Below it: stage list, open-weights audit with per-model pills, and key/value receipt rows in 13px with Text 3 keys.

### Take row (Takes table)
Rows inside a Panel container with 10px radius: a 36px check column, 96px thumbnail, title (500) over subtitle, kind, length, identity, state pill and time. Hover goes Raised; the current row takes the Indigo Wash; remixes indent 32px on a faint white wash. A sticky reel bar (Raised, Float shadow) appears with the selection.

### Cast card
Raised, 10px radius, 1px `line-strong` border, a 3:4 portrait well on Screen black, pills for state, a hint line, then a full-width primary-or-secondary action with an icon button. Candidate sets sit in a Panel container with 1:1 candidates. Consent is a plain radio list with plain copy; the safety and consent text is never softened or hidden.

### Drop zone
Ground well, 1px dashed Control Edge, 10px radius, 16px padding, Text 2 label in 13px 500 Text. Hover or drag-over: accent border, Indigo Wash. A chosen file becomes a 72px thumbnail row with name and remove.

### Notice and empty state
Notices stack top-right under the bar (max 380px): Raised, `line-strong` border, Float shadow, an amber (or red for errors) icon, a 500 "what" line and a Text 2 "how to fix it" line. Empty states centre an 18px 600 heading over a Text 2 paragraph (max 44ch) with one or two actions; they say plainly what is missing and what to do. Skeletons are a flat Raised block that breathes (opacity down to 55%) over 1.6 s; nothing sweeps across them and nothing is a gradient.

## Do's and Don'ts

### Do:
- **Do** keep the footage as the only saturated thing: chrome is the six-step neutral ladder plus one indigo.
- **Do** use the accent for the primary action, selection, focus and progress only, and the lighter `accent-text` for text on dark.
- **Do** show Replay as an amber pill with "a recording played back"; use "Recorded take" in the accent for real recorded renders; say "Nothing was rendered just now" where it applies.
- **Do** keep text at 12px or larger and interactive targets at 24px or larger (controls are 26 to 40px).
- **Do** give every control a visible 2px accent focus ring and keep control edges at 3:1 (`control-line`).
- **Do** animate only to show state, 120 to 400 ms with the `cubic-bezier(0.16, 1, 0.3, 1)` ease: 120 ms for hover and color, 180 ms for toggles, panels and path draws, 400 ms for progress. Nothing animates on load. Honour `prefers-reduced-motion`.
- **Do** spend cheap before expensive: stills for approval before video, and let the plan line count real renders.
- **Do** keep content-safety and consent copy plain, complete and in the interface, in Text colour.
- **Do** say what is missing and how to fix it in notices and empty states; never fake a render, a price or a count.
- **Do** size the Monitor to the footage's aspect ratio, and use tabular numerals for anything that changes.

### Don't:
- **Don't** add gradients, glass, blur, glow, or decorative colour to the chrome.
- **Don't** add kickers, eyebrows, uppercase tracked labels or glyph-as-icon decoration; icons are Lucide SVGs at one stroke weight.
- **Don't** use a second accent, or colour a panel with a state hue; state is a pill, dot or arc.
- **Don't** put a shadow on anything that does not overlap other content, and never a hard offset shadow.
- **Don't** introduce a display face or a second sans family; mono is for seeds, hashes and timecodes only.
- **Don't** let Replay read as a render: no spinner, no "Rendering", no accent colour on a replayed run.
- **Don't** use native controls where the vocabulary exists; pick-one is segmented, a value is a slider with a number box, an option is a switch.
- **Don't** use pure white except through `on-fill` (marks on accent or danger fills, a switch thumb that is on) and the translucent white of the comparator divider and the play control over footage.
