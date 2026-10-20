# Running the real models: GPU box or Comfy Cloud

OpenField talks to ComfyUI only through the official `comfy-sdk`, so the same app runs against
three targets by changing two environment variables. Pick one.

| Target | `COMFY_BASE_URL` | `COMFY_API_KEY` | Notes |
|---|---|---|---|
| **Comfy Cloud** | unset | your `comfyui-...` key | Paid plan needed for API use. Models are preinstalled. |
| **Your own GPU box** (below) | `http://127.0.0.1:9189` through an SSH tunnel | none on loopback | You pay the provider by the hour; the most setup. |
| **Comfy API deployment** | `https://<deployment>.run.comfy.app` | your key | Needs a Comfy Build. |

No GPU and no key: `openfield demo` replays recorded takes.

## GPU box

1. **Rent** a box with a CUDA PyTorch image (Ubuntu 22.04), SSH access, **at least 32 GB VRAM**
   (RTX 5090, RTX 6000 Ada, L40S, A6000) and **at least 150 GB disk** (the models are tens of GB; 150 GB leaves room).
2. **Unlock LTX 2.5 once** on your Hugging Face account: open
   https://huggingface.co/Lightricks/LTX-2.5 and click *Agree and Access* (approval is instant).
   Create a **read-only** token at https://huggingface.co/settings/tokens (fine-grained, with
   *Read access to contents of all public gated repos you can access* and nothing else).
3. **Copy the scripts and the model list** from your computer:
   ```
   scp -P <SSH_PORT> scripts/pod_setup.sh scripts/fetch_template_models.py openfield/engine/manifest.json root@<BOX_IP>:/workspace/
   ```
   The repository keeps these files with Unix line endings. If an editor on Windows turned them into CRLF, bash on the
   box stops with `set: pipefail: invalid option name`; fix it on the box with `sed -i 's/\r$//' /workspace/pod_setup.sh`.
4. **On the box**:
   ```
   export HF_TOKEN=hf_...        # read-only token; typed on the box, never committed
   bash /workspace/pod_setup.sh
   ```
   It checks the GPU and disk, installs ComfyUI v0.41.0, downloads the model files listed by the
   official templates (resumable, safe to re-run), then starts ComfyUI and `comfy-api-proxy`,
   both bound to `127.0.0.1`.
5. **On your computer**, open the tunnel (the script prints it) and point the app at it:
   ```
   ssh -N -L 9188:127.0.0.1:8188 -L 9189:127.0.0.1:8189 -p <SSH_PORT> root@<BOX_IP>
   ```
   ```
   $env:COMFY_BASE_URL = "http://127.0.0.1:9189"      # PowerShell
   openfield doctor
   ```
6. **Stop the box** when you are done rendering. `bash pod_setup.sh down` stops the services;
   stop or destroy the instance in your provider's console to stop billing.

Why a tunnel: `comfy-api-proxy` has no TLS and no public-safe defaults, so it stays on loopback.
ComfyUI's own `/object_info` (used for node checks) is on the second forwarded port.

The left-hand (local) ports are 9188 and 9189 on purpose: you may already run ComfyUI on 8188 on your own
computer, and Windows reserves some port ranges (here 8189 to 8288), in which case `ssh` fails with "cannot
listen to port" or "bind: permission denied". Any free local ports work; set `COMFY_BASE_URL` to match.
`netsh interface ipv4 show excludedportrange protocol=tcp` lists what Windows reserves.

## First checks (Day 1)

With the tunnel up, ask the box's own ComfyUI whether it accepts every workflow (this is a validity check,
nothing renders; run it before the first real render):

```
python scripts/validate_on_comfy.py --comfy http://127.0.0.1:9188
```
It prints one line per workflow and names the node and the file when ComfyUI refuses one (a model that did
not download, for example). `python scripts/validate_workflows.py --object-info http://127.0.0.1:9188` also
compares each numeric slot's range with the limits the box reports.

Then a real submission through the SDK:


```
python scripts/smoke_sdk.py --graph openfield/workflows/<graph>.api.json --list-nodes
python scripts/smoke_sdk.py --graph <graph>.api.json --asset <node>/<input>=<file> --set <node>/<input>=<value> --out out
```
The smoke script prints the real output types and sizes, saves `events.jsonl` and the first
live preview, and refuses to bind to node ids or inputs that do not exist in the graph.

Already confirmed on a CPU-only ComfyUI 0.41.0 behind the real `comfy-api-proxy` 0.1.6 and `comfy-sdk` 0.5.0
(no weights needed): an `.mp4` upload is accepted; a `SaveVideo` result downloads as `video/mp4` with its audio and
is classified as video; failures name the node (`The job failed at node ... (VAELoader)`); every patched workflow
passes ComfyUI's own validation. Still to confirm with real weights on the box: that previews arrive (they only do
because ComfyUI is started with `--preview-method auto`), render times, and whether each camera move looks right.
