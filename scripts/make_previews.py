#!/usr/bin/env python3
"""CLI wrapper around openfield.previews.

    py.cmd scripts/make_previews.py [--takes DIR] [--out DIR] [--index FILE] [--check]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openfield.previews import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
