"""Settings, read from the environment each time they are asked for (never at import).

    COMFY_BASE_URL / COMFY_API_KEY   which Comfy target to use (unset base URL = Comfy Cloud)
    OPENFIELD_BACKEND                auto | sdk | replay    (auto = sdk when a target is configured)
    OPENFIELD_HOST / _PORT           where the app listens   (127.0.0.1:8877)
    OPENFIELD_DATA_DIR               takes, cast, uploads    (./data)
    OPENFIELD_WORKFLOW_DIR           override the bundled workflow templates (tests, forks)
    OPENFIELD_MODEL_DIR              face models cache       (~/.cache/openfield/models)

Keys are never stored on the settings object: `has_api_key` only says whether one is present.
"""
from __future__ import annotations

import codecs
import os
import re
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    data_dir: Path
    backend: str
    comfy_base_url: str | None
    has_api_key: bool
    workflow_dir: Path
    showcase_dir: Path
    web_dir: Path

    @property
    def takes_dir(self) -> Path:
        return self.data_dir / "takes"

    @property
    def cast_dir(self) -> Path:
        return self.data_dir / "cast"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def sdk_configured(self) -> bool:
        return bool(self.comfy_base_url) or self.has_api_key

    @property
    def effective_backend(self) -> str:
        if self.backend == "auto":
            return "sdk" if self.sdk_configured else "replay"
        return self.backend


_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _read_env_text(path: Path) -> str:
    """Decode a .env the way Windows tools write it: UTF-8 (with or without a BOM) or UTF-16."""
    raw = path.read_bytes()
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):  # PowerShell 5.1's `>` and `echo`
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


def parse_env_line(raw: str) -> tuple[str, str] | None:
    """(name, value) for a KEY=VALUE line, or None for blanks, comments and anything else."""
    line = raw.strip()
    if line.startswith("export "):
        line = line[len("export "):].lstrip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    key, _, value = line.partition("=")
    key, value = key.strip(), value.strip()
    if not _ENV_NAME.match(key):
        return None
    if value[:1] in {"'", '"'}:  # quoted: everything up to the closing quote, comments and all
        end = value.find(value[0], 1)
        value = value[1:end] if end != -1 else value[1:]
    else:  # unquoted: a ` # ...` tail is a comment, not part of the value
        value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
    return key, value


def load_env_file(path: Path) -> int:
    """Load KEY=VALUE lines from a .env file without overriding variables already set."""
    if not path.is_file():
        return 0
    loaded = 0
    for raw in _read_env_text(path).splitlines():
        parsed = parse_env_line(raw)
        if parsed and parsed[0] not in os.environ:
            os.environ[parsed[0]] = parsed[1]
            loaded += 1
    return loaded


def get_settings() -> Settings:
    env = os.environ
    backend = env.get("OPENFIELD_BACKEND", "auto").strip().lower()
    if backend not in {"auto", "sdk", "replay"}:
        raise ValueError("OPENFIELD_BACKEND must be auto, sdk or replay")
    return Settings(
        host=env.get("OPENFIELD_HOST", "127.0.0.1"),
        port=int(env.get("OPENFIELD_PORT", "8877")),
        data_dir=Path(env.get("OPENFIELD_DATA_DIR", "data")).resolve(),
        backend=backend,
        comfy_base_url=(env.get("COMFY_BASE_URL") or "").strip() or None,
        has_api_key=bool((env.get("COMFY_API_KEY") or "").strip()),
        workflow_dir=Path(env.get("OPENFIELD_WORKFLOW_DIR") or PACKAGE_DIR / "workflows").resolve(),
        showcase_dir=PACKAGE_DIR / "web" / "showcase",
        web_dir=PACKAGE_DIR / "web",
    )
