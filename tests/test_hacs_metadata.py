"""Validate hacs.json metadata."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from packaging.version import Version


@lru_cache(maxsize=1)
def _required_homeassistant_version() -> str:
    """Extract the pinned Home Assistant version from requirements.txt."""
    requirements_path = Path("requirements.txt")
    for line in requirements_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("homeassistant=="):
            return line.partition("==")[2]
    msg = "homeassistant requirement is not pinned"
    raise AssertionError(msg)


def _load_hacs_metadata() -> dict[str, object]:
    """Return the parsed hacs.json payload for assertions."""

    hacs_path = Path("hacs.json")
    with hacs_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def test_hacs_metadata_matches_integration_identity():
    """Ensure the published metadata references the Govee Ultimate domain."""
    data = _load_hacs_metadata()
    assert data["name"] == "Govee Ultimate"
    assert "filename" not in data
    assert data["zip_release"] is False
    assert data["homeassistant"] == _required_homeassistant_version()


def test_hacs_metadata_requires_python312_ready_version() -> None:
    """Metadata must declare compatibility with Python 3.12 era releases."""

    data = _load_hacs_metadata()
    assert Version(data["homeassistant"]) >= Version("2025.1.4")
