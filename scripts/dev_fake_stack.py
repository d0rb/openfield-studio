#!/usr/bin/env python3
"""Offline dev stack for UI work: the app on the real templates, rendering through a fake Comfy API.

    python scripts/dev_fake_stack.py [--delay 1.0] [--port 8877] [--data-dir data-dev]

Every "render" is a synthetic test pattern labelled FAKE. This exists so the whole interface
(queue, progress, approvals, receipts, exports) can be built and screenshotted without a GPU. It
is never a substitute for real renders and nothing it makes belongs in the showcase.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--delay", type=float, default=1.0, help="seconds per simulated step (default 1.0)")
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--data-dir", default=str(ROOT / "data-dev"))
    parser.add_argument("--no-previews", action="store_true")
    args = parser.parse_args(argv)

    import uvicorn

    from openfield.app import create_app
    from openfield.config import get_settings
    from tests.fake_comfy_api import FakeComfyApi

    scratch = tempfile.TemporaryDirectory(prefix="openfield-fake-")  # the fake's one test clip; removed on exit
    fake = FakeComfyApi(delay=args.delay, previews=not args.no_previews, tmp=Path(scratch.name))
    base_url = fake.start()
    os.environ.update({
        "COMFY_BASE_URL": base_url,
        "OPENFIELD_BACKEND": "sdk",
        "OPENFIELD_BACKEND_LABEL": "FAKE dev stack (synthetic outputs, not a render)",
        "OPENFIELD_DATA_DIR": args.data_dir,
        "OPENFIELD_PORT": str(args.port),
    })
    print(f"FAKE Comfy API on {base_url} (synthetic outputs only)")
    print(f"OpenField dev stack on http://127.0.0.1:{args.port}/  data: {args.data_dir}")
    try:
        uvicorn.run(create_app(get_settings()), host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        fake.stop()
        scratch.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
