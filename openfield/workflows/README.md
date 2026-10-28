# Workflows

The six ComfyUI graphs OpenField drives, in API format, plus a slot map for each:

| Workflow | Official template | Used for |
|---|---|---|
| `qwen21_t2i` | `image_qwen_image_2_1_t2i` | hero stills, generated characters |
| `qwen21_edit` | `image_qwen_image_2_1_image_edit` | anchor stills, identity-preserving edits, the angled still, Shots setups, Edit with words, the face-only re-shoot's first frame |
| `ltx25_i2v` | `video_ltx2_5_i2v` | one-still shots (two-stage, with a x2 latent upscale), Extend |
| `ltx25_flf2v` | `video_ltx2_5_flf2v` | first-and-last-frame shots, transitions, the loop move |
| `wan_animate2` | `video_wan_animate2` | Re-shoot (motion transfer), including the face-only re-shoot |
| `esrgan_upscale` | `utility-gan_upscaler` | Upscale (a finished take, enlarged to 2K or 4K) |

Of round 7's features only Upscale added a graph. Shots, Edit with words and the face-only re-shoot's first frame are `qwen21_edit` runs. The image to change is `base_image`. For the two swaps and the face-only step, the Cast's images go in as references (up to nine). A Shots board is nine such runs, one per camera position, with no reference. A transition is one `ltx25_flf2v` run, with the first take's last frame as `first_frame` and the second take's first frame as `last_frame`. The loop move is the same graph with the hero as both frames. Extend is one `ltx25_i2v` run from a take's last frame. A dub renders on whichever LTX graph its take's move needs. None of these adds a node class.

## Provenance

The graphs come from the official [Comfy-Org/workflow_templates](https://github.com/Comfy-Org/workflow_templates)
(MIT, see `LICENSE.workflow_templates`) at the commit pinned in `openfield/engine/manifest.json`. Those templates are
UI-format. They were converted with ComfyUI 0.41.0's own frontend (`app.graphToPrompt()`, frontend 1.55.17) by
`scripts/export_templates.py`, so the compound node ids (`251:198`) are what ComfyUI itself produces. No custom nodes.

`esrgan_upscale` is derived as well as exported. It starts from the official "Video Upscale: Real-ESRGAN" template
(`utility-gan_upscaler`) with the same nodes and the same model, `RealESRGAN_x4plus.safetensors`. One core
`ImageScale` node was added after the model, to land on 2K or 4K (the model always enlarges 4x. The note inside the template says to
resize its result). The added node is `13`, and `scripts/export_templates.py` (`add_image_scale`) repeats the edit on a
re-export. The graph was written by hand from the template, in the form the frontend exports the other graphs. On
October 23 a ComfyUI 0.41.0 server ran it on a rented RTX 5090. A 5-second Draft take (896x512, 121 frames) became
2560x1462 in about 2 minutes and was checked by eye against its source (`v6-upscale-draft-2k`), so `UPSCALE_TESTED` in
`openfield/engine/rig.py` is on. 4K has not been rendered. The clip is held in memory at 4x as float32 before the resize
(173 MB a frame at 1280x704, about 21 GB for 121 frames, up to twice that for a moment by the ComfyUI 0.41.0 source).
Those numbers are arithmetic, and they were not measured. So the pipeline refuses an upscale whose estimate passes 24 GB before any take exists.
`OPENFIELD_UPSCALE_MAX_GB` sets another limit for a box with more memory.

## Slot maps (`*.slots.json`)

A slot map names the literal inputs OpenField may change, and nothing else. The patcher checks every node and input
before touching the graph, because the Comfy SDK would silently create a missing one. Then it removes whatever no longer
feeds an output. Three kinds of edit go beyond setting a value, each stated in the slot map:

- **Prompt enhancers are removed.** Every template can rewrite your prompt with a language model behind an If/Else
  switch. OpenField records the exact prompt it sent, so the enhancer is cut out (`fixed` + `unlink` on the switch's
  `on_true`). ComfyUI validates a switch's unused branch too, so leaving it in would require its model files on every box.
- **Sizes are literals.** Where a template derives width and height from a resolution selector, that wiring is replaced
  (`unlink`) by the exact size requested. Sizes snap to what the model accepts, and the snapped value is recorded.
- **Reference images grow.** `qwen21_edit` accepts up to nine references beyond the base image. Extra loader nodes are
  cloned from the template's own, and the unused placeholder wiring is removed.
- **Middle stills are guided.** `ltx25_flf2v` can take up to three stills between the first and the last frame (`mids`, a
  `guide_list` slot). The template's own last-frame chain (LoadImage → ResizeImageMaskNode → LTXVPreprocess →
  LTXVAddGuide) is cloned once per still and chained in before the last guide, and each clone is pinned to its frame index.
  Each middle still may also carry its own guide strength, and the receipt records it.
  `LTXVCropGuides` removes every guide at once, as it does for two. The node classes stay the same, so the audit sees nothing new.
  The app renders every move of three or more stills this way since October 22 (`SINGLE_PASS` in `engine/rig.py`), with
  the middle stills held at strength 0.4 (`MID_GUIDE_STRENGTH`). At the template's 0.7 the subject ghosted near them.

There is no negative prompt. The LTX 2.5 templates run their guider at CFG 1 (`LTXVDualCFGGuider`, video and audio), so
one would never be applied. OpenField sends none and records none.

## Checking them

```
python scripts/validate_workflows.py                                  # contract, wiring and open-weights audit
python scripts/validate_workflows.py --object-info <ComfyUI URL>      # slot ranges against the node's own limits
python scripts/validate_on_comfy.py --comfy <ComfyUI URL>             # ComfyUI's validator, on each patched graph (the
                                                                       # first-last-frame graph twice: as exported, and with
                                                                       # two middle stills guided inside one pass)
```

All six were accepted by a ComfyUI 0.41.0 server with no node errors, `esrgan_upscale` by running it on October 23.
`python -m pytest tests/test_real_templates.py` holds the patched shape of each in place. Re-export
(`scripts/export_templates.py`) after bumping the pinned templates, review the diff, then regenerate the manifest
(`scripts/gen_manifest.py`) and the licence list (`scripts/gen_third_party.py`).
