"""Formatting guard tests for DreamView state modules."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    REPO_ROOT / "custom_components" / "govee" / "state" / "states.py",
    REPO_ROOT / "tests" / "test_dreamview_states.py",
]


@pytest.mark.parametrize(
    "command",
    (
        ("ruff", "format", "--check"),
        ("black", "--check"),
    ),
)
def test_dreamview_code_is_tool_formatted(command: tuple[str, ...]) -> None:
    """Ensure DreamView modules align with Ruff/Black formatting expectations."""
    result = subprocess.run(
        [*command, *[str(path) for path in TARGETS]],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
