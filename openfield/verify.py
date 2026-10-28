"""`openfield verify`: one command that prints every proof a judge would check.

All checks are pure functions returning a `CheckResult`. The CLI only formats and prints.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .backends.replay import ReplayBackend
from .engine import quality
from .engine import receipt as receipts
from .engine.audit import audit_graph
from .engine.contract import CONTRACTS
from .engine.models import registry
from .engine.rig import (
    ANGLES_TESTED,
    AZIMUTHS,
    DISTANCES,
    EFFECT_IDS,
    ELEVATIONS,
    FROM_IMAGE_TESTED,
    MOVES,
    SINGLE_PASS,
    VALIDATED,
    VALIDATED_EFFECTS,
)
from .engine.workflows import load_template
from .ledger import Ledger
from .pipeline import DirectRequest, Pipeline


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str  # "ok" | "fail" | "skip"
    detail: str
    items: list[dict[str, Any]] = field(default_factory=list)


def _root_paths(root: Path) -> tuple[Path, Path]:
    """Workflow templates and bundled takes relative to the repository root."""
    return (
        root / "openfield" / "workflows",
        root / "openfield" / "web" / "showcase" / "takes",
    )


def check_workflows(workflow_dir: Path) -> CheckResult:
    """Audit every workflow template (one per contract)."""
    items: list[dict[str, Any]] = []
    failures: list[str] = []
    for name in CONTRACTS:
        try:
            template = load_template(name, workflow_dir)
            audit = audit_graph(template.graph)
            items.append({"template": name, "passed": audit.passed,
                          "nodes_checked": audit.nodes_checked})
            if not audit.passed:
                failures.append(name)
        except Exception as exc:  # noqa: BLE001
            items.append({"template": name, "passed": False,
                          "nodes_checked": 0, "error": str(exc)})
            failures.append(name)
    ok = not failures
    detail = f"{sum(i['passed'] for i in items)}/{len(items)} templates pass"
    return CheckResult("Workflows", "ok" if ok else "fail", detail, items)


def check_receipts(takes_dir: Path) -> CheckResult:
    """Count bundled takes and verify their seals."""
    if not takes_dir.is_dir():
        return CheckResult(
            "Receipts", "skip",
            "no bundled takes in this checkout",
            [{"path": str(takes_dir), "exists": False}],
        )
    takes: list[Path] = []
    for folder in sorted(takes_dir.iterdir()):
        if folder.is_dir() and (folder / "receipt.json").is_file():
            takes.append(folder)
    if not takes:
        return CheckResult(
            "Receipts", "skip",
            "no bundled takes in this checkout",
            [{"path": str(takes_dir), "count": 0}],
        )

    items: list[dict[str, Any]] = []
    verified = 0
    first_failure: str | None = None
    for folder in takes:
        try:
            receipt = json.loads((folder / "receipt.json").read_text(encoding="utf-8"))
            ok = receipts.verify(receipt)
            take_id = receipt.get("take", {}).get("id") or folder.name
        except Exception:  # noqa: BLE001
            ok = False
            take_id = folder.name
        items.append({"id": take_id, "verified": ok})
        if ok:
            verified += 1
        elif first_failure is None:
            first_failure = take_id

    total = len(takes)
    ok = verified == total
    detail = f"{total} take(s), {verified} seal(s) verified"
    if first_failure:
        detail += f", first failure: {first_failure}"
    return CheckResult("Receipts", "ok" if ok else "fail", detail, items)


def check_models() -> CheckResult:
    """Every known model file must be marked open-weights."""
    items: list[dict[str, Any]] = []
    failures: list[str] = []
    for info in registry().values():
        items.append({"file": info.file, "license": info.license_name,
                      "open_weights": info.open_weights})
        if not info.open_weights:
            failures.append(info.file)
    detail = f"{len(items)} model file(s), all open-weights"
    if failures:
        detail = f"{len(failures)} not open-weights: {', '.join(failures)}"
    return CheckResult("Models", "ok" if not failures else "fail", detail, items)


def check_proof_counts() -> CheckResult:
    """Compute tested counts from the rig and quality modules, never hard-written."""
    moves_total = len(MOVES)
    moves_tested = len(VALIDATED)
    angles_total = len(AZIMUTHS) * len(ELEVATIONS) * len(DISTANCES)
    angles_tested = len(ANGLES_TESTED)
    effects_total = len([e for e in EFFECT_IDS if e != "none"])
    effects_tested = len(VALIDATED_EFFECTS)
    tiers_total = len(quality.TIERS)
    tiers_tested = len(quality.VALIDATED_QUALITY)

    items = [{
        "moves_tested": moves_tested, "moves_total": moves_total,
        "angles_tested": angles_tested, "angles_total": angles_total,
        "effects_tested": effects_tested, "effects_total": effects_total,
        "quality_tiers_tested": tiers_tested, "quality_tiers_total": tiers_total,
        "from_image_tested": FROM_IMAGE_TESTED,
        "single_pass": SINGLE_PASS,
    }]
    detail = (
        f"moves {moves_tested}/{moves_total}, "
        f"angles {angles_tested}/{angles_total}, "
        f"effects {effects_tested}/{effects_total}, "
        f"quality {tiers_tested}/{tiers_total}, "
        f"from-image {'yes' if FROM_IMAGE_TESTED else 'no'}, "
        f"single-pass {'on' if SINGLE_PASS else 'off'}"
    )
    return CheckResult("Proof counts", "ok", detail, items)


async def _check_replay_once(workflow_dir: Path) -> CheckResult:
    """Replay on an empty ledger must refuse an unrecorded recipe."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        ledger = Ledger(tmp_path / "takes")
        backend = ReplayBackend([tmp_path / "empty"])
        pipeline = Pipeline(
            ledger, lambda: backend, workflow_dir, gate=None, timeout=10.0,
        )
        take = await pipeline.start_direct(
            DirectRequest(
                subject="A lighthouse at dusk",
                rig={"movement": "static"},
                auto_approve=True,
            )
        )
        await pipeline.wait(take["id"])
        done = ledger.read(take["id"])
        refused = (
            done.get("status") == "failed"
            and done.get("error", {}).get("code") == "replay_unavailable"
        )
        detail = "refused an unrecorded recipe"
        items = [{"status": done.get("status"),
                  "code": done.get("error", {}).get("code")}]
        if not refused:
            detail = f"expected replay_unavailable, got {done.get('error')}"
            items[0]["message"] = done.get("error", {}).get("message")
        return CheckResult("Replay", "ok" if refused else "fail", detail, items)


def check_replay(workflow_dir: Path) -> CheckResult:
    """Synchronous wrapper for the async Replay check."""
    return asyncio.run(_check_replay_once(workflow_dir))


def run_checks(root: Path) -> list[CheckResult]:
    """Run every check and return the ordered results."""
    workflow_dir, takes_dir = _root_paths(root)
    return [
        check_workflows(workflow_dir),
        check_receipts(takes_dir),
        check_models(),
        check_proof_counts(),
        check_replay(workflow_dir),
    ]


def _format_marker(status: str) -> str:
    return {"ok": "[ ok ]", "fail": "[FAIL]", "skip": "[ -- ]"}[status]


def _print_text(results: list[CheckResult]) -> None:
    for result in results:
        print(f"{_format_marker(result.status)} {result.name}: {result.detail}")


def _to_json(results: list[CheckResult]) -> dict[str, Any]:
    ok = sum(1 for r in results if r.status == "ok")
    failed = sum(1 for r in results if r.status == "fail")
    return {
        "results": [asdict(r) for r in results],
        "summary": {"ok": ok, "failed": failed},
    }


def verify(root: Path | None = None, *, json_output: bool = False) -> int:
    """Run all checks, print them, and return 1 if anything failed."""
    root = root or Path.cwd()
    results = run_checks(root)
    ok = sum(1 for r in results if r.status == "ok")
    failed = sum(1 for r in results if r.status == "fail")
    if json_output:
        print(json.dumps(_to_json(results), indent=2))
    else:
        _print_text(results)
        print(f"\nVERIFIED: {ok} ok, {failed} failed")
    return 1 if failed else 0
