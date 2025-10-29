"""Metadata validation tests for the Govee Ultimate integration."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any


def _load_json_pairs(path: Path) -> tuple[list[str], dict[str, Any]]:
    pairs = json.loads(path.read_text(), object_pairs_hook=lambda items: items)
    keys = [key for key, _ in pairs]
    return keys, dict(pairs)


def test_manifest_keys_sorted_and_issue_tracker_present() -> None:
    """The manifest should follow Home Assistant key ordering requirements."""

    manifest_path = Path("custom_components/govee_ultimate/manifest.json")
    keys, manifest = _load_json_pairs(manifest_path)

    assert keys[0] == "domain"
    assert keys[1] == "name"
    assert keys[2:] == sorted(keys[2:])
    assert "issue_tracker" in manifest


def test_services_yaml_exists_for_registered_services() -> None:
    """Service registrations require a services.yaml descriptor."""

    services_yaml = Path("custom_components/govee_ultimate/services.yaml")
    assert services_yaml.exists()


def test_config_schema_defined_for_async_setup() -> None:
    """Integrations with async_setup must expose a config schema."""

    module = importlib.import_module("custom_components.govee_ultimate")
    assert hasattr(module, "CONFIG_SCHEMA")
