# OpenField Studio

[![Awesome](https://awesome.re/badge.svg)](https://github.com/sindresorhus/awesome)

OpenField Studio is an open-source creative app for deterministic cinematic
direction, video re-shoots, reference-locked characters and products, and
multi-shot audio/video finishing on ComfyUI.

## Why .cursorrules?

The repository is designed to be easy for humans and coding agents to extend:
small services, explicit contracts, capability checks, structured logs, and
offline tests keep workflow changes reviewable.

## Table of contents

- [Features](#features)
- [Quick start](#quick-start)
- [Execution modes](#execution-modes)
- [API](#api)
- [Development](#development)
- [Contributing](#contributing)
- [License](#license)

## Features

- Cinema rig compiler: sensor, lens, aperture, lighting, movement, and start/end frames.
- OpenJutsu-compatible motion-transfer workflow contracts for LTX and MiniMax H3.
- Reference and identity gates with optional OpenCV YuNet/SFace support.
- Comfy SDK v2 adapter with an explicit open-weights-only policy.
- Local ComfyUI HTTP fallback for private fleets.
- FastAPI control surface with a six-stage production rail.
- Offline workflow validation and deterministic JSON output.

## Quick start

```powershell
cd C:\code\openfield_studio
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[platform]"
python -m openfield
```

Open `http://127.0.0.1:8877/docs`.

For a local ComfyUI instance:

```powershell
$env:OPENFIELD_COMFY_BASE_URL = "http://127.0.0.1:8188"
$env:OPENFIELD_EXECUTION_MODE = "local"
```

For Comfy API v2 / Cloud, set `COMFY_API_KEY` and
`OPENFIELD_EXECUTION_MODE=platform`. Router partner models are disabled when
`OPENFIELD_OPEN_WEIGHTS_ONLY=1`.

## Execution modes

| Mode | Purpose |
| --- | --- |
| `dryrun` | Compile and validate workflow contracts without submitting |
| `local` | Submit API-format workflows to a private ComfyUI endpoint |
| `platform` | Use `comfy-sdk` for Comfy API v2 workflows |
| `router` | Use the SDK Router surface for an explicitly allowed partner model |

The default is `dryrun`; no generation or billing occurs until a mode is chosen.

## API

- `GET /api/health`
- `GET /api/catalog`
- `POST /api/cinema/compile`
- `POST /api/openjutsu/compile`
- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `GET /api/media/{path}` for files under the configured output directory

## Development

```powershell
python -m pytest -q
python -m openfield.cli dryrun
python -m openfield.cli live-preflight
```

`live-preflight` reads `OPENFIELD_LIVE_COMFY_URL/object_info` and reports missing
node classes. It requires a reachable ComfyUI instance; it does not submit a
generation.

Workflow builders must return API-format graphs and declare their required
node classes. The executor rejects a graph when a supplied capability
inventory does not contain those nodes.

## Contributing

Open a focused pull request with tests, an updated `change.txt` entry, and a
small example when adding a workflow or UI control. Do not commit API keys,
private server addresses, copyrighted reference media, or offensive tooling.

## License

MIT. See `LICENSE`.
