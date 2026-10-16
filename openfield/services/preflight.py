from typing import Any


def validate_workflow(workflow: dict[str, Any], available_nodes: set[str]) -> list[str]:
    """Return missing node classes; never submits an invalid graph."""
    required = {
        node.get("class_type")
        for node in workflow.values()
        if isinstance(node, dict) and node.get("class_type")
    }
    return sorted(required - available_nodes)


def validate_or_raise(workflow: dict[str, Any], available_nodes: set[str]) -> None:
    missing = validate_workflow(workflow, available_nodes)
    if missing:
        raise ValueError("workflow requires unavailable nodes: " + ", ".join(missing))
