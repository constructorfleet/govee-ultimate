"""Formatting lint checks for the codebase."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BLACK_TARGETS = ("custom_components", "tests")


def test_codebase_is_black_formatted() -> None:
    """Ensure the repository is formatted with Black."""

    project_root = Path(__file__).resolve().parent.parent
    command = [sys.executable, "-m", "black", "--check", *BLACK_TARGETS]
    result = subprocess.run(
        command,
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
