"""Ensure dependency list only includes directly imported packages."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable

from packaging.requirements import Requirement

REQUIREMENTS_PATH = Path("requirements.txt")

EXPECTED_RUNTIME_PACKAGES = (
    "httpx",
    "packaging",
    "pydantic",
    "PyYAML",
    "pytest",
    "voluptuous",
)

EXPECTED_TOOLING_PACKAGES = (
    "black",
    "ruff",
)

EXPECTED_IMPORTED_PACKAGES = (
    *EXPECTED_RUNTIME_PACKAGES,
    *EXPECTED_TOOLING_PACKAGES,
)


def _iter_requirements() -> Iterable[Requirement]:
    """Yield parsed requirement entries, ignoring comments and blank lines."""

    for raw_line in REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        yield Requirement(line)


def _requirement_names() -> list[str]:
    """Collect requirement package names while guarding against duplicates."""

    names = [requirement.name for requirement in _iter_requirements()]
    assert len(names) == len(
        set(names)
    ), "requirements.txt should not contain duplicates"
    return sorted(names)


def test_requirements_match_imported_packages() -> None:
    """The requirements file should only list directly imported libraries."""

    assert _requirement_names() == sorted(EXPECTED_IMPORTED_PACKAGES)
