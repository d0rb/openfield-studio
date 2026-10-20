# Workflows

The five ComfyUI graphs OpenField drives, in API format, plus a slot map for each:

| Workflow | Official template | Used for |
|---|---|---|
| `qwen21_t2i` | `image_qwen_image_2_1_t2i` | hero stills, generated characters |
| `qwen21_edit` | `image_qwen_image_2_1_image_edit` | anchor stills, identity-preserving edits |
| `ltx25_i2v` | `video_ltx2_5_i2v` | one-still shots (two-stage, with a x2 latent upscale) |
| `ltx25_flf2v` | `video_ltx2_5_flf2v` | first-and-last-frame shots |
| `wan_animate2` | `video_wan_animate2` | Re-shoot (motion transfer) |

## Provenance

The graphs come from the official [Comfy-Org/workflow_templates](https://github.com/Comfy-Org/workflow_templates)
(MIT, see `LICENSE.workflow_templates`) at the commit pinned in `openfield/engine/manifest.json`. Those templates are
UI-format; they were converted with ComfyUI 0.41.0's own frontend (`app.graphToPrompt()`, frontend 1.55.17) by
`scripts/export_templates.py`, so the compound node ids (`251:198`) are what ComfyUI itself produces. No custom nodes.

## Slot maps (`*.slots.json`)

A slot map names the literal inputs OpenField may change, and nothing else. The patcher checks every node and input
before touching the graph (the Comfy SDK would silently create a missing one), then removes whatever no longer feeds an
output. Three kinds of edit go beyond setting a value, each stated in the slot map:

- **Prompt enhancers are removed.** Every template can rewrite your prompt with a language model behind an If/Else
  switch. OpenField records the exact prompt it sent, so the enhancer is cut out (`fixed` + `unlink` on the switch's
  `on_true`). ComfyUI validates a switch's unused branch too, so leaving it in would require its model files on every box.
- **Sizes are literals.** Where a template derives width and height from a resolution selector, that wiring is replaced
  (`unlink`) by the exact size requested; sizes snap to what the model accepts and the snapped value is recorded.
- **Reference images grow.** `qwen21_edit` accepts up to nine references beyond the base image; extra loader nodes are
  cloned from the template's own and the unused placeholder wiring is removed.

## Checking them

```
python scripts/validate_workflows.py                                  # contract, wiring and open-weights audit
python scripts/validate_workflows.py --object-info <ComfyUI URL>      # slot ranges against the node's own limits
python scripts/validate_on_comfy.py --comfy <ComfyUI URL>             # ComfyUI's validator, on each patched graph
```

All five were accepted by a ComfyUI 0.41.0 server with no node errors, and `python -m pytest tests/test_real_templates.py`
holds the patched shape of each in place. Re-export (`scripts/export_templates.py`) after bumping the pinned templates,
review the diff, then regenerate the manifest (`scripts/gen_manifest.py`) and the licence list (`scripts/gen_third_party.py`).
