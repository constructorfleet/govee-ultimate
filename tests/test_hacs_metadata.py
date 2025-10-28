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
            version = line.partition("==")[2]
            return version.partition(";")[0].strip()
    msg = "homeassistant requirement is not pinned"
    raise AssertionError(msg)


def test_required_homeassistant_version_strips_markers(monkeypatch) -> None:
    """Ensure the helper ignores environment markers when parsing."""

    def fake_read_text(self: Path, *args, **kwargs):
        assert self == Path("requirements.txt")
        return 'homeassistant==2024.12.5 ; python_version >= "3.13"\n'

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    assert _required_homeassistant_version() == "2024.12.5"


def test_hacs_metadata_matches_integration_identity():
    """Ensure the published metadata references the Govee Ultimate domain."""
    hacs_path = Path("hacs.json")
    with hacs_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    assert data["name"] == "Govee Ultimate"
    assert "filename" not in data
    assert data["zip_release"] is False
    assert data["homeassistant"] == _required_homeassistant_version()
