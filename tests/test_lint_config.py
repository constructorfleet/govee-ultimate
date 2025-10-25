"""Regression tests for lint configuration stability."""

from __future__ import annotations

from pathlib import Path

import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_ruff_config_uses_lint_section() -> None:
    """Ensure Ruff configuration opts into the new lint.* namespace."""

    config_path = PROJECT_ROOT / ".ruff.toml"
    config = tomllib.loads(config_path.read_text())

    assert "lint" in config
    assert "select" not in config
    assert "ignore" not in config
