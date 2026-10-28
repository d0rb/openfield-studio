# The SDK path

OpenField renders only through `comfy-sdk`. Two environment variables pick the target: `COMFY_BASE_URL` for a GPU
box behind comfy-api-proxy or a Comfy API deployment, `COMFY_API_KEY` for Comfy Cloud. The Connect sheet in the
header can also build the same `SdkBackend` from the address and key you paste (`docs/CONNECT.md`).

The app reads ComfyUI itself in two places. The optional model check (`openfield/engine/preflight.py`) reads
`/object_info` and `/system_stats` to say which workflows a box can run before any render is paid for. The health
probe's `/system_stats` call tells a bare ComfyUI from the proxy.

```python
from comfy_sdk import AsyncComfy

async with AsyncComfy() as client:                       # target chosen by COMFY_BASE_URL / COMFY_API_KEY
    wf = client.workflows.from_json(graph)               # an API-format graph, patched from an official template
    frame = client.assets.from_file("first_frame.png")
    wf.set_input(slots["first_frame"]["node"], "image", frame)   # node ids come from the template's slot map
    job = await client.submit(wf)                        # inputs are uploaded here
    async for event in job.events():                     # progress, previews, queue position
        ...
    await job.wait()
    output = job.get_outputs(slots["output"]["node"])[0]
    await output.to_file("take.mp4")
```

The real code is [openfield/backends/sdk.py](../openfield/backends/sdk.py). It adds timeouts, cancellation, error
mapping and event recording. The graphs come from the official templates and are patched by
[openfield/engine/workflows.py](../openfield/engine/workflows.py), as described in
[openfield/workflows/README.md](../openfield/workflows/README.md).

Render times on a rented RTX 5090 are in [benchmarks.md](benchmarks.md). Comfy Cloud times are not measured yet.
