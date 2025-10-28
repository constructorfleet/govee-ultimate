"""Validate hacs.json metadata."""

import json
from pathlib import Path


def test_hacs_metadata_matches_integration_identity():
    """Ensure the published metadata references the Govee Ultimate domain."""
    hacs_path = Path("hacs.json")
    with hacs_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    assert data["name"] == "Govee Ultimate"
    assert data["filename"] == "govee_ultimate.zip"
