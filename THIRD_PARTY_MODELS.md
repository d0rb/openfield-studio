# Third-party models and licences

OpenField Studio's own code is MIT. It does not bundle any model weights: they are downloaded
from Hugging Face by the official ComfyUI templates (see `docs/POD.md`) and run on Comfy Cloud or
your own GPU box. Every weight file below is **open-weights** (downloadable and runnable locally).
"Open weights" is not the same as "open source": each model has its own licence, summarised here.
Check the model card before any commercial use.

The app enforces this list at runtime: before a workflow is submitted, the open-weights audit
refuses any node that is not in the allowlist taken from the official templates, and any weight
file that is not listed here. The audit result is stored in every take's receipt.


## Apache License 2.0

- Commercial use: free for commercial use.
- Licence text: https://www.apache.org/licenses/LICENSE-2.0

| File | Role | Source repo | Loaded by OpenField |
|---|---|---|---|
| `clip_vision_h.safetensors` | clip_vision | [Comfy-Org/Wan-Animate-2](https://huggingface.co/Comfy-Org/Wan-Animate-2) | yes |
| `lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors` | lora | [Comfy-Org/Wan-Animate-2](https://huggingface.co/Comfy-Org/Wan-Animate-2) | yes |
| `gemma4_e2b_it_int8_convrot.safetensors` | text_encoder | [Comfy-Org/gemma-4](https://huggingface.co/Comfy-Org/gemma-4) | no (listed by the official templates only) |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | text_encoder | [Comfy-Org/Wan-Animate-2](https://huggingface.co/Comfy-Org/Wan-Animate-2) | yes |
| `Wan2_1_VAE_bf16.safetensors` | vae | [Comfy-Org/Wan-Animate-2](https://huggingface.co/Comfy-Org/Wan-Animate-2) | yes |
| `wan_animate_2_int8_convrot.safetensors` | video:wan-animate-2 | [Comfy-Org/Wan-Animate-2](https://huggingface.co/Comfy-Org/Wan-Animate-2) | yes |

## BSD 3-Clause License

- Commercial use: free for commercial use; keep the copyright notice with any copy.
- Licence text: https://github.com/xinntao/Real-ESRGAN/blob/a4abfb2/LICENSE

| File | Role | Source repo | Loaded by OpenField |
|---|---|---|---|
| `RealESRGAN_x4plus.safetensors` | upscaler:real-esrgan | [Comfy-Org/Real-ESRGAN_repackaged](https://huggingface.co/Comfy-Org/Real-ESRGAN_repackaged) | yes |

## LTX-2.x Community License Agreement

- Commercial use: free for commercial and production use under $10M annual revenue; paid agreement above.
- Licence text: https://huggingface.co/Lightricks/LTX-2.5

| File | Role | Source repo | Loaded by OpenField |
|---|---|---|---|
| `ltx-2.5-audio-vae-bf16.safetensors` | audio_vae | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) | yes |
| `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` | text_encoder | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) | yes |
| `ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors` | upscaler | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) | yes |
| `ltx-2.5-video-vae-bf16.safetensors` | vae | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) | yes |
| `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` | video:ltx-2.5 | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) | yes |

## Qwen Research License Agreement

- Commercial use: non-commercial use only.
- Required attribution: "Built with Qwen".
- Licence text: https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE

| File | Role | Source repo | Loaded by OpenField |
|---|---|---|---|
| `qwen_image_2.1_int8_convrot.safetensors` | image:qwen-image-2.1 | [Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1) | yes |
| `qwen3.5_9b_qwen_image_2.1_pe_i2i.int8_convrot.safetensors` | text_encoder | [Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1) | no (listed by the official templates only) |
| `qwen3.5_9b_qwen_image_2.1_pe_t2i.int8_convrot.safetensors` | text_encoder | [Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1) | no (listed by the official templates only) |
| `qwen3vl_8b_int8_convrot.safetensors` | text_encoder | [Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1) | yes |
| `qwen_image_2.1_vae_bf16.safetensors` | vae | [Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1) | yes |


## Notes

- **Qwen-Image 2.1** is under the Qwen Research License: non-commercial use only, and products
  built with it must show "Built with Qwen". The still-image step is a swappable slot.
- **LTX 2.5** is gated on Hugging Face (one click on "Agree and Access" shares your contact
  details with Lightricks). Free commercial use applies below $10M annual revenue.
- **Real-ESRGAN** (the video upscaler, 67 MB, not gated) is BSD-3-Clause as the Comfy-Org repack's model card
  declares. The upstream repository states BSD-3-Clause for its code and names no separate licence for the
  weights, so the weights' own terms are not confirmed from the authors.
- **Face check** (optional, local): YuNet (MIT) and SFace (Apache-2.0) from the OpenCV Zoo, downloaded
  on demand and checked against pinned SHA-256 hashes.
- This list covers weights. Python dependencies carry their own licences (see `pyproject.toml`).


_Generated from the official templates at `Comfy-Org/workflow_templates@04a508b31bec`; repo to licence map: Lightricks/LTX-2.5 -> ltx-2.x-community, Comfy-Org/Qwen-Image-2.1 -> qwen-research, Comfy-Org/Wan-Animate-2 -> apache-2.0, Comfy-Org/gemma-4 -> apache-2.0, Comfy-Org/Real-ESRGAN_repackaged -> bsd-3-clause, Comfy-Org/Real-ESRGAN -> bsd-3-clause._
