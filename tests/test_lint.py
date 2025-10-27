"""Lint integration using Ruff."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_ruff_check_passes() -> None:
    """Ruff should report no lint errors for the project."""

    result = subprocess.run(
        ["ruff", "check", ".", "--output-format", "json"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(result.stdout or result.stderr)


def test_ruff_check_targets_project_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lint gate should lint the repository root explicitly."""

    recorded: dict[str, list[str]] = {}

    def _fake_run(cmd: list[str], **kwargs: Any) -> Any:
        recorded["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    test_ruff_check_passes()

    target = recorded["cmd"][2]
    assert target in {".", str(PROJECT_ROOT)}
