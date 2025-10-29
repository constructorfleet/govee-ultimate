"""Tests for the integration manifest metadata."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MANIFEST_PATH = Path("custom_components/govee_ultimate/manifest.json")


def _load_manifest() -> dict[str, Any]:
    assert MANIFEST_PATH.exists(), "manifest.json must exist for the integration"
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_manifest_declares_requirements_and_dependencies() -> None:
    """Ensure the manifest exposes domain, requirements, and MQTT dependency."""

    manifest = _load_manifest()
    assert manifest["domain"] == "govee_ultimate"
    assert sorted(manifest["requirements"]) == ["httpx", "pydantic"]
    assert "mqtt" in manifest.get("dependencies", [])


def test_manifest_keys_sorted_by_specification() -> None:
    """The manifest keys must appear as domain, name, then alphabetical."""

    manifest = _load_manifest()

    assert list(manifest.keys()) == [
        "domain",
        "name",
        "codeowners",
        "config_flow",
        "dependencies",
        "documentation",
        "integration_type",
        "iot_class",
        "issue_tracker",
        "requirements",
        "version",
    ]
