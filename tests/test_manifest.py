"""Tests for the integration manifest metadata."""

from __future__ import annotations

import json
from pathlib import Path


def test_manifest_declares_requirements_and_dependencies() -> None:
    """Ensure the manifest exposes domain, requirements, and MQTT dependency."""

    manifest_path = Path("custom_components/govee_ultimate/manifest.json")
    assert manifest_path.exists(), "manifest.json must exist for the integration"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["domain"] == "govee_ultimate"
    assert sorted(manifest["requirements"]) == ["httpx", "pydantic"]
    assert "mqtt" in manifest.get("dependencies", [])


def test_manifest_keys_sorted_and_issue_tracker_present() -> None:
    """The manifest should follow Home Assistant key ordering requirements."""

    manifest_path = Path("custom_components/govee_ultimate/manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    keys = list(manifest)

    assert keys[:2] == ["domain", "name"], "domain then name should lead the manifest"
    assert keys[2:] == sorted(
        keys[2:]
    ), "remaining keys should be alphabetically ordered"

    issue_tracker = manifest.get("issue_tracker")
    assert issue_tracker, "issue_tracker URL must be present in the manifest"
