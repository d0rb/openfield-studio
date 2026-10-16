from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    execution_mode: str = os.getenv("OPENFIELD_EXECUTION_MODE", "dryrun").lower()
    open_weights_only: bool = os.getenv("OPENFIELD_OPEN_WEIGHTS_ONLY", "1") not in {"0", "false", "no"}
    comfy_base_url: str = os.getenv("OPENFIELD_COMFY_BASE_URL", "http://127.0.0.1:8188")
    api_key: str = os.getenv("COMFY_API_KEY", "")
    output_dir: Path = Path(os.getenv("OPENFIELD_OUTPUT_DIR", "output"))
    host: str = os.getenv("OPENFIELD_HOST", "127.0.0.1")
    port: int = int(os.getenv("OPENFIELD_PORT", "8877"))


settings = Settings()
