# Connect a render backend

OpenField renders through the official `comfy-sdk`, which speaks Comfy API v2. It works with **Comfy Cloud**,
**comfy-api-proxy in front of any ComfyUI**, and a Comfy API deployment. Replay needs none of them.
`openfield demo` plays the recorded takes.

The **Connect** sheet (the header's backend button) takes an address or a key. It tests it and reports what it
found. New takes switch only when you confirm. The address can be remembered between runs (`data/connection.json`).
A key or token stays in memory until the app closes. It is never written to disk, logged or shown.

| Target | What to paste | Test reports |
|---|---|---|
| **GPU box** (Vast.ai, RunPod, your PC) | the proxy address, usually `http://127.0.0.1:9189` through an SSH tunnel. A token if the proxy started with `--token`. Optionally ComfyUI's address (`http://127.0.0.1:9188`). | Reachable or not. "This is ComfyUI itself" when the proxy is missing. Token accepted or rejected. With the ComfyUI address, one row per workflow: ready, the missing model file and where to get it, or a node class it lacks. |
| **Comfy Cloud** | an API key from [platform.comfy.org](https://platform.comfy.org) (API Keys). A paid plan is needed. | Key accepted or rejected. Cloud lists no model files, so the first render names the missing one. We have not checked whether its library has these workflows' files. |

The same check runs from the command line: `openfield doctor --comfy http://127.0.0.1:9188`.

## A GPU box on Vast.ai or RunPod, in ten minutes

1. **Rent** one RTX 5090 (32 GB) or a 48 GB card (RTX 6000 Ada, L40S, A6000), **150 GB of disk**, SSH access, a CUDA
   PyTorch image (Ubuntu 22.04). On Vast.ai, `vastai/pytorch` works. If its venv lacks torch, run the setup with
   `TORCH_INDEX=https://download.pytorch.org/whl/cu128` and it installs CUDA 12.8 torch.
2. **Get access to LTX 2.5 once** on Hugging Face (https://huggingface.co/Lightricks/LTX-2.5, *Agree and Access*).
   Make a **read-only**, fine-grained token (*Read access to contents of all public gated repos you can access*).
3. **Copy the setup** to the box and run it. Type the token on the box, never commit it:
   ```
   scp -P <PORT> scripts/pod_setup.sh scripts/fetch_template_models.py openfield/engine/manifest.json root@<BOX>:/workspace/
   ssh -p <PORT> root@<BOX>
   export HF_TOKEN=hf_...; bash /workspace/pod_setup.sh
   ```
   It checks the GPU and disk, installs ComfyUI v0.41.0, downloads the 14 model files the official templates need
   (about 90 GB: 50 GB of Wan and Qwen, 40 GB of LTX 2.5, resumable), then starts ComfyUI on `127.0.0.1:8188` and
   the proxy on `127.0.0.1:8189`.
   `FETCH_ONLY=wan,qwen bash /workspace/pod_setup.sh up` starts without the gated LTX files.
   `HF_TOKEN=hf_... FETCH_ONLY=ltx bash /workspace/pod_setup.sh fetch` adds them later.
4. **Tunnel** both ports. The proxy has no TLS, so it stays on the box's loopback:
   ```
   ssh -N -L 9189:127.0.0.1:8189 -L 9188:127.0.0.1:8188 -p <PORT> root@<BOX>
   ```
5. **Connect**: header → *Connect a backend…* → GPU box → proxy `http://127.0.0.1:9189`, ComfyUI `http://127.0.0.1:9188`
   → **Test** (six Ready rows, one per workflow, and the GPU's name) → **Use this backend**.
6. **Stop paying** when done. Destroy the instance in the provider's console. `bash pod_setup.sh down` stops the
   services only.

**Without a tunnel** (RunPod's HTTP proxy, an exposed port): start the proxy with a token, bound beyond loopback on
purpose. Paste the public address and the token:
```
comfy-api-proxy run --comfyui http://127.0.0.1:8188 --host 0.0.0.0 --port 8189 --token <long random string> --comfyui-base-dir /workspace/ComfyUI
```
The Connect sheet warns when an address is not loopback and no token was given.

Local ports 9188/9189 are only a suggestion. Windows reserves some ranges
(`netsh interface ipv4 show excludedportrange protocol=tcp` lists them), and you may already run ComfyUI on 8188.
Any free ports work.

## Your own ComfyUI (no proxy yet)

`comfy-sdk` cannot talk to ComfyUI's own `/prompt` API, so a plain ComfyUI answers "this is ComfyUI itself" in the
Connect sheet. One command fixes it next to a running ComfyUI:
```
pip install comfy-api-proxy
comfy-api-proxy run --comfyui http://127.0.0.1:8188 --port 8189 --comfyui-base-dir <your ComfyUI folder>
```
Then connect to `http://127.0.0.1:8189`, with ComfyUI at `http://127.0.0.1:8188` for the model check. The six
workflows need ComfyUI 0.41 or newer and the 14 files in `openfield/engine/manifest.json`. The file lists 17, and
three belong to the prompt enhancers the app prunes. The check names a missing file and the Hugging Face repository
for it. `python scripts/fetch_template_models.py` downloads them.

## Comfy Cloud

Make an API key at https://platform.comfy.org (API Keys). Copy it once, it is shown only at creation. The API needs a
paid plan (Standard: one job at a time, 30 minutes per job). Paste it in the Connect sheet, or set `COMFY_API_KEY` in
`.env` before starting.

We have not measured a render on Comfy Cloud. On October 22 a key passed the health check (authenticated, ready).
The first submission, a Qwen-Image 2.1 portrait graph, was refused with "This key is not allowed to do that". The
graph is probably not the cause. That points at the key's scope or the account's plan. We have also not checked
whether Cloud's library has these workflows' files. The six workflows are the official ComfyUI templates.

## The environment still works

`COMFY_BASE_URL` and `COMFY_API_KEY` in the environment or `.env` set the same targets before the app starts.
`OPENFIELD_REQUEST_TIMEOUT` (seconds, default 600) caps one HTTP call, such as an upload or a long poll of a running
job. A whole render gets thirty minutes. `openfield doctor` checks both. The sheet shows such a target as "from the
environment". The showcase CLI (`openfield showcase`) reads the environment only.
