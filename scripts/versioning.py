"""Utility helpers for managing project release metadata."""

from __future__ import annotations

import json
from typing import Any, Final
from pathlib import Path

SemVer = tuple[int, int, int]
_SEMVER_PARTS: Final[int] = 3


def update_manifest_version(manifest_path: Path, version: str) -> None:
    """Update the Home Assistant manifest with the provided version string."""

    manifest_data = _load_json(manifest_path)
    manifest_data["version"] = version
    _write_json(manifest_path, manifest_data)


def prepare_release(manifest_path: Path) -> str:
    """Bump the manifest version and return the next semantic version."""

    manifest_data = _load_json(manifest_path)
    current = str(manifest_data.get("version", "0.0.0"))
    next_version = bump_patch_version(current)
    update_manifest_version(manifest_path, next_version)
    return next_version


def bump_patch_version(version: str) -> str:
    """Increment the patch component of a semantic version string."""

    major, minor, patch = _split_version(version)
    patch += 1
    return f"{major}.{minor}.{patch}"


def _split_version(version: str) -> SemVer:
    """Split a dotted semantic version into integers."""

    parts = version.split(".")
    if len(parts) != _SEMVER_PARTS:
        msg = f"Version '{version}' must follow MAJOR.MINOR.PATCH format"
        raise ValueError(msg)
    try:
        return tuple(int(part) for part in parts)  # type: ignore[return-value]
    except ValueError as exc:  # pragma: no cover - invalid input is guarded above
        raise ValueError(f"Version '{version}' must be numeric") from exc


def _load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file into memory."""

    return json.loads(path.read_text())


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Persist JSON payload to disk with canonical formatting."""

    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
