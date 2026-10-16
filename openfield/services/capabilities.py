from typing import Any

import requests


def fetch_nodes(base_url: str, timeout: int = 20) -> set[str]:
    response = requests.get(f"{base_url.rstrip('/')}/object_info", timeout=timeout)
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    return set(payload)


def validate_against_live(base_url: str, workflow: dict[str, Any], timeout: int = 20) -> list[str]:
    from .preflight import validate_workflow

    return validate_workflow(workflow, fetch_nodes(base_url, timeout))
