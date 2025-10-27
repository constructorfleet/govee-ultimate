"""Lint integration using Ruff."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_ruff_check_passes() -> None:
    """Ruff should report no lint errors for the project."""

    result = subprocess.run(
        ["ruff", "check", "--output-format", "json"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(result.stdout or result.stderr)
