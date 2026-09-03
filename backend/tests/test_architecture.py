"""Architectural guardrails.

The plan's claim that `backend/core` is a pure domain layer is only true if something
enforces it. A code-review note would not; this test does.
"""

from __future__ import annotations

import ast
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "core"

#: Importing any of these into core would break testability and make the AWS layer
#: non-swappable, which is what backs the "I'd choose differently at scale" argument.
FORBIDDEN = {
    "boto3", "botocore", "aws_lambda_powertools", "aws_cdk",
    "garminconnect", "garth",
    "fastapi", "mangum", "starlette",
    "requests", "httpx", "urllib3",
}


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_core_modules_exist() -> None:
    expected = {
        "models", "units", "reasons", "energy", "nutrition", "weight",
        "baselines", "recovery", "trends", "body_composition", "calibration",
    }
    actual = {p.stem for p in CORE.glob("*.py")} - {"__init__"}
    assert expected <= actual, f"missing core modules: {expected - actual}"


def test_core_has_no_infrastructure_imports() -> None:
    offenders: dict[str, set[str]] = {}
    for path in CORE.glob("*.py"):
        bad = _imported_modules(path) & FORBIDDEN
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"core must stay pure, found: {offenders}"


def test_core_does_no_io() -> None:
    """No file, network or clock access. `datetime.now()` in particular makes a pure
    function untestable -- every calculation takes the date it should reason about."""
    banned_calls = {"open", "print", "input"}
    offenders: list[str] = []
    for path in CORE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in banned_calls:
                    offenders.append(f"{path.name}: {func.id}()")
                if isinstance(func, ast.Attribute) and func.attr in {"now", "today", "utcnow"}:
                    offenders.append(f"{path.name}: .{func.attr}()")
    assert not offenders, f"core must be pure and clock-free, found: {offenders}"
