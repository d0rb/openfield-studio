---
version: 1
slug: "openfield-web-index-html"
primary_target: "openfield/web/index.html"
related_targets: []
---

# Surface brief: the OpenField Studio app (openfield/web)

## Scope and mode

Two rooms, one static ES-module app that serves both the live server and the hosted Replay (every screen works with recorded takes only and with a real backend). The Lobby (new, the first screen) is Persuade: a stranger or a judge decides within seconds to try an app. The stations behind it (Cast, Direct, Shots, Re-shoot, Takes) are Operate: the screening room, where the footage leads and the interface stays quiet.

## Audience, job, action, proof, constraints

A creator alone at a laptop in a dim room making shareable clips; contest judges who open it cold and decide in minutes. Job in the Lobby: see what is showing, see proof, pick an app or start directing. Job in the stations: describe a shot, pick a camera move, approve cheap stills, shoot, then judge, share, remix and export. Proof the Lobby must carry: every poster's proof is a recorded take with a sealed receipt, played on hover; untested apps say so; the marquee carries only counts read from the data; the art itself was rendered on our own GPU with open weights and has receipts. Constraints: no build step, no CDN, self-hosted fonts and icons, the size budgets in tests/test_web_assets.py (raised with a dated reason), AA contrast, keyboard operable, reduced motion respected, desktop first at 1024 and up with a working phone layout (390 wide), original copy only (no other product's names or phrases, and no comparison with another product), every selector the tests and the demo recorder use survives verbatim, every shipping raster carries its provenance.

## Chosen direction and memorable moment

The cinema lobby at night. The apps hang as one-sheets in lit poster cases, the takes are numbered lobby cards, a receipt is a ticket stub, the marquee carries the true counts, and the stations are the screening room behind the doors. Memorable moment: a poster comes alive under the pointer, its key art giving way to the app's real recorded take with the take's ticket stub sliding up.

## Direction contract

THESIS: A cinema lobby for an open-weights studio, not a feed. Each app is a one-sheet whose key art our own GPU rendered and whose proof is a recorded take; each take is a lobby card, each receipt a ticket stub, and the marquee says only what the data says. It refuses the category's wall of autoplay thumbnails under a neon Generate key, the upsell banners, and any poster without a real take behind it.

OWN-WORLD: Lacquer-black lobby ground, warm, never blue; poster cases framed by a hairline of brass with the case light coming from the art itself (no CSS glow, no glass); marquee white only on the rendered letter board; ticket orange, the roll ticket's colour, is the one action colour (primary action, selection, focus). Barlow Condensed for marquee letters, poster titles and the billing block (tall caps, small connecting words between large names); Barlow for interface text; Overpass Mono for every figure. Atoms: the one-sheet (key art, title, tagline, billing block, a status snipe), the lobby card (printed border, title band, card number), the ticket stub (perforated edge, TAKE, seat = seed, row = steps, checksum stamp), the screen with velvet masking for its aspect. Overlays are rendered light (projector beam, light leak, dust), screen-blended. Raises: the stills step is the trailer before the feature, the one cheap preview before the irreversible spend (darkroom safelight); one ruled billing grid in one order on every poster, card and stub: title, models, seed, steps, seconds, hash (sneaker box stacks); the wall records its run: each poster shows since when it has been showing, read from its take (sticker accretion); the marquee letters are matter: hung one by one on load, a count changes by swapping its letters (alphabet storm); total palette commitment: lacquer black, marquee white, ticket orange, brass, and colour only from the art (risograph); progress is a physical behaviour: a render lights a row of bulbs one by one (leather studio).

STORY: The visitor arrives at the lobby: the marquee says what is showing; the feature one-sheet plays our stage; the poster wall lists every app with its key art and its status. Hovering a poster plays its real take with its ticket; choosing one, or Start directing, leads into the screening room, where the footage leads and the ticket sits beside every take. They believe it because the proof is a recorded take with a sealed receipt, the untested say so, and even the art has receipts.

FIRST VIEWPORT: At 1440 by 900: a 56px bar (floor-tape T, wordmark, the rooms as text links, backend pill at the right). Below it, a hero about 560px tall: at the left a 380px one-sheet in its brass case, the stage loop playing as key art, OPENFIELD STUDIO in condensed caps, a tagline and the billing block in its lower third; at the right the rendered marquee board (about 860 by 250) with three rows of hung letters (NOW SHOWING / the moves count and the tested count / OPEN WEIGHTS ONLY), then the headline, one sentence, the orange ticket-shaped Start directing with a quieter Watch the takes beside it, and a mono proof line. From about 640px down: NOW SHOWING and the first row of one-sheets, about 176 by 260 each, the wall continuing below the fold. Signature interaction: hover or focus on a one-sheet raises its case light, sweeps one rendered light leak across it and crossfades the key art to the app's recorded take with a REAL TAKE stamp, the ticket stub rising from the bottom. Reduced motion shows the take's poster frame, no sweep, no loop.

FORM: Cinema lobby (one-sheets, lobby cards, ticket stubs, marquee), candidate 3 on my ordered grounded list, assigned by seed key 42050d21 (index 3); the roll output that printed this key was not saved (the only roll file, .impeccable/roll-07857be4.txt, belongs to the earlier stage world). Challengers: darkroom safelight bay competitive on product clarity; sticker accretion, leather skeuomorph, risograph, alphabet storm and sneaker box stacks declined; each discipline donated as a named raise above.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Unresolved decisions

Which station screens adopt lobby atoms beyond the shell, buttons, receipts and empty states is decided by what keeps the Operate rooms quiet. The old stage-world signature (the stage view with the travelling camera) stays as product function inside Direct.
