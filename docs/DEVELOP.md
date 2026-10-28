# Develop and test

```bash
pip install -e ".[dev]"
ruff check .
pytest                                  # a faithful fake of the Comfy API stands in for the GPU. It also drives the
                                        # real interface in Chrome or Edge (skipped when Node or a browser is missing)
node --test "tests/js/*.test.mjs"       # front-end logic
python scripts/dev_fake_stack.py        # the app on that fake, for UI work (its output is labelled FAKE, never a render)
python scripts/record_demo.py --url URL # the demo video, scripted. See docs/DEMO.md
python scripts/release_check.py         # the pre-publish gate
python scripts/fill_links.py --repo URL --site URL --video URL   # at publish time: the three links the gate waits for
```

## Repository layout

```text
openfield/engine/     rig, workflow patcher, audit, receipts, identity, video
openfield/backends/   comfy-sdk backend, replay backend
openfield/            pipeline, ledger, cast, exports, showcase, app (FastAPI), cli
openfield/workflows/  the six exported ComfyUI graphs and their slot maps
openfield/web/        the interface: static ES modules and plain CSS, self-hosted Barlow, Barlow Condensed and Overpass Mono and Lucide icons, no build step (about 175 KB of script over the wire)
openfield/web/art/    every picture in the interface, rendered with open weights, and manifest.json with each one's prompt, seed, models and hashes
scripts/              GPU box setup, template export and validation, release gate
showcase/             the specs the recorded takes were rendered from
tests/                Python tests, JS tests, a faithful fake of the Comfy API
```

CI runs `ruff check .` and the Python and JavaScript tests on Windows and Linux. The release gate (`scripts/release_check.py`) also checks for secrets, unfinished markers, workflow contracts, the recorded takes and their receipt seals. It also exports the whole site to a temporary folder and runs the hosted copy's browser smoke test on it (`--no-browser` skips that), because the test suite's small fixture export cannot show what only the full bundle shows.

## The fake stack

`tests/fake_comfy_api.py` answers like the real API, so the engine and the interface can be tested without a GPU. The development stack labels its output `FAKE`. `scripts/record_demo.py` refuses to pass test-pattern footage off as a render, and it names the result `demo.FAKE.mp4`. Only record the submission video against takes rendered by the real models.
