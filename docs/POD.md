# Running the real models

OpenField talks to ComfyUI only through the official `comfy-sdk`, so one app runs against three targets. Two
environment variables pick one.

| Target | `COMFY_BASE_URL` | `COMFY_API_KEY` | Notes |
|---|---|---|---|
| **Comfy Cloud** | unset | your `comfyui-...` key | Paid plan for API use. We have not checked whether its library has these workflows' files. |
| **Your own GPU box** (below) | `http://127.0.0.1:9189` through an SSH tunnel | none on loopback | You pay the provider by the hour. This one needs the most setup. |
| **Comfy API deployment** | `https://<deployment>.run.comfy.app` | your key | Needs a Comfy Build. |

No GPU and no key: `openfield demo` replays recorded takes. You can also connect from inside the app (header →
*Connect a backend…*, which tests them). See [CONNECT.md](CONNECT.md).

## GPU box

1. **Rent** a box with a CUDA PyTorch image (Ubuntu 22.04), SSH access, **at least 32 GB VRAM**
   (RTX 5090, RTX 6000 Ada, L40S, A6000) and **at least 150 GB disk**. The models are tens of GB, and 150 GB leaves room.
2. **Get access to LTX 2.5 once** on Hugging Face. Open https://huggingface.co/Lightricks/LTX-2.5 and click
   *Agree and Access* (approval is instant). Create a **read-only** token at
   https://huggingface.co/settings/tokens (fine-grained, *Read access to contents of all public gated repos you can
   access* and nothing else).
3. **Copy the scripts and the model list** from your computer:
   ```
   scp -P <SSH_PORT> scripts/pod_setup.sh scripts/fetch_template_models.py openfield/engine/manifest.json root@<BOX_IP>:/workspace/
   ```
   The repo keeps these files with Unix line endings. If a Windows editor turned them into CRLF, bash on the box stops
   with `set: pipefail: invalid option name`. Fix it with `sed -i 's/\r$//' /workspace/pod_setup.sh`.
4. **On the box**:
   ```
   export HF_TOKEN=hf_...        # read-only token; typed on the box, never committed
   bash /workspace/pod_setup.sh
   ```
   It checks the GPU and disk, installs ComfyUI v0.41.0, and downloads the official templates' model files
   (resumable, safe to re-run). Then it starts ComfyUI and `comfy-api-proxy` on `127.0.0.1`. Without the token,
   `FETCH_ONLY=wan,qwen bash /workspace/pod_setup.sh up` brings everything up with the ungated models.
   `HF_TOKEN=hf_... FETCH_ONLY=ltx bash /workspace/pod_setup.sh fetch` adds LTX 2.5 later. A refused file never
   stops the services.
5. **On your computer**, open the tunnel (the script prints it) and point the app at it:
   ```
   ssh -N -L 9188:127.0.0.1:8188 -L 9189:127.0.0.1:8189 -p <SSH_PORT> root@<BOX_IP>
   ```
   ```
   $env:COMFY_BASE_URL = "http://127.0.0.1:9189"      # PowerShell
   openfield doctor
   ```
6. **Stop the box** when you are done. `bash pod_setup.sh down` stops the services. Stop or destroy the instance in
   your provider's console to stop billing.

The proxy has no TLS and no public-safe defaults, so it stays on loopback. ComfyUI's own `/object_info` (used for
node checks) is on the second forwarded port.

The local ports are 9188 and 9189 on purpose. You may already run ComfyUI on 8188. Windows reserves some ranges
(here 8189 to 8288), and then `ssh` fails with "cannot listen to port" or "bind: permission denied". Any free local
ports work, with `COMFY_BASE_URL` set to match. `netsh interface ipv4 show excludedportrange protocol=tcp` lists what
Windows reserves.

## First checks (Day 1)

With the tunnel up, ask the box's ComfyUI whether it accepts every workflow. Nothing renders. Run it before the
first real render:

```
python scripts/validate_on_comfy.py --comfy http://127.0.0.1:9188
```
It prints one line per workflow and names the node and file when ComfyUI refuses one (a model that did not download,
for example). `python scripts/validate_workflows.py --object-info http://127.0.0.1:9188` also compares each numeric
slot's range with the limits the box reports.

Then a real submission through the SDK:

```
python scripts/smoke_sdk.py --graph openfield/workflows/<graph>.api.json --list-nodes
python scripts/smoke_sdk.py --graph <graph>.api.json --asset <node>/<input>=<file> --set <node>/<input>=<value> --out out
```
The smoke script prints the real output types and sizes. It saves `events.jsonl` and the first live preview. It
refuses node ids or inputs that are not in the graph.

These are confirmed on a CPU-only ComfyUI 0.41.0 behind `comfy-api-proxy` 0.1.6 and `comfy-sdk` 0.5.0, with no
weights. An `.mp4` upload is accepted. A `SaveVideo` result downloads as `video/mp4` with audio and counts as video.
Failures name the node (`The job failed at node ... (VAELoader)`). Every patched workflow passes ComfyUI's validation.

Still to confirm on the box: previews arrive (ComfyUI needs `--preview-method auto`), the render times, and whether
each camera move looks right.
