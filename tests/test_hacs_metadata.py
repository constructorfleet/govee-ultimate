"""Validate hacs.json metadata."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _required_homeassistant_version() -> str:
    """Extract the pinned Home Assistant version from requirements.txt."""
    requirements_path = Path("requirements.txt")
    for line in requirements_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("homeassistant=="):
            return line.partition("==")[2]
    msg = "homeassistant requirement is not pinned"
    raise AssertionError(msg)


def test_hacs_metadata_matches_integration_identity():
    """Ensure the published metadata references the Govee Ultimate domain."""
    hacs_path = Path("hacs.json")
    with hacs_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    assert data["name"] == "Govee Ultimate"
    assert "filename" not in data
    assert data["zip_release"] is False
    assert data["homeassistant"] == _required_homeassistant_version()
