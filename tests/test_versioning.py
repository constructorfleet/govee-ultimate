"""Tests for repository version management utilities."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def manifest_file(tmp_path: Path) -> Path:
    """Provide a minimal manifest file for testing."""

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "domain": "govee",
                "name": "Govee Ultimate",
                "config_flow": True,
            }
        )
    )
    return manifest


def test_update_manifest_version_sets_version_field(manifest_file: Path) -> None:
    """Version update should add or replace the manifest version field."""

    from scripts.versioning import update_manifest_version

    update_manifest_version(manifest_file, "1.2.3")

    manifest = json.loads(manifest_file.read_text())
    assert manifest["version"] == "1.2.3"


@pytest.mark.parametrize(
    ("current", "expected"),
    (
        ("0.0.0", "0.0.1"),
        ("1.2.3", "1.2.4"),
    ),
)
def test_bump_patch_version_increments_last_segment(
    current: str, expected: str
) -> None:
    """Patch bumps should increment the final semantic version segment."""

    from scripts.versioning import bump_patch_version

    assert bump_patch_version(current) == expected


def test_prepare_release_adds_version_when_missing(manifest_file: Path) -> None:
    """Release preparation should seed an initial semantic version."""

    from scripts.versioning import prepare_release

    new_version = prepare_release(manifest_file)

    manifest = json.loads(manifest_file.read_text())
    assert new_version == "0.0.1"
    assert manifest["version"] == "0.0.1"


def test_prepare_release_cli_prints_version(
    manifest_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Command line release helper should emit the calculated version."""

    from scripts import prepare_release as cli

    exit_code = cli.main(["--manifest", str(manifest_file)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == "0.0.1"
