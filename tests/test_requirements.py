"""Dependency pin regression tests."""

from __future__ import annotations

from pathlib import Path

from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = REPO_ROOT / "requirements.txt"
PINNED_VERSIONS = {
    line.split("==", maxsplit=1)[0]: Version(line.split("==", maxsplit=1)[1])
    for line in REQUIREMENTS.read_text().splitlines()
    if "==" in line
}


def _extract_pin(package: str) -> Version:
    """Return the pinned Version for the provided package name."""

    try:
        return PINNED_VERSIONS[package]
    except KeyError as exc:
        msg = f"{package} is not pinned in requirements.txt"
        raise AssertionError(msg) from exc


def test_aiohttp_pin_supports_python312() -> None:
    """Aiohttp must be pinned to a Python 3.12 compatible version."""

    assert _extract_pin("aiohttp") >= Version("3.11.11")
