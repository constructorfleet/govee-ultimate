"""Version guard tests for pinned dependencies."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Final

import pytest
from packaging.requirements import Requirement

Version = tuple[int, int, int]

EXPECTED_EXACT_VERSIONS: Final[dict[str, Version]] = {
    "attrs": (24, 2, 0),
    "awesomeversion": (24, 6, 0),
    "bcrypt": (4, 2, 0),
    "ciso8601": (2, 3, 1),
    "cryptography": (43, 0, 1),
    "home-assistant-bluetooth": (1, 13, 0),
    "Jinja2": (3, 1, 4),
    "PyJWT": (2, 10, 1),
    "pyOpenSSL": (24, 2, 1),
    "propcache": (0, 2, 1),
    "orjson": (3, 10, 12),
    "python-slugify": (8, 0, 4),
    "PyYAML": (6, 0, 2),
    "requests": (2, 32, 3),
    "ulid-transform": (1, 0, 2),
    "lru-dict": (1, 3, 0),
    "httpx": (0, 27, 2),
}

REQUIREMENTS_PATH = Path("requirements.txt")


def _requirement_line(package: str) -> str:
    content = REQUIREMENTS_PATH.read_text(encoding="utf-8")
    pattern = rf"^{re.escape(package)}==[^\n]+$"
    match = re.search(pattern, content, flags=re.MULTILINE)
    assert match, f"Expected an exact {package} pin in requirements.txt"
    return match.group(0)


def _pinned_version(package: str) -> Version:
    requirement = _requirement_line(package)
    match = re.search(r"==(?P<version>\d+\.\d+\.\d+)", requirement)
    assert match, f"Expected an exact {package} pin in requirements.txt"
    return tuple(int(part) for part in match.group("version").split("."))  # type: ignore[return-value]


def _assert_exact_pin(package: str) -> None:
    version = _pinned_version(package)
    assert (
        version == EXPECTED_EXACT_VERSIONS[package]
    ), f"{package} must match Home Assistant 2024.12.5 pin"


def _assert_version_in_range(package: str, minimum: Version, maximum: Version) -> None:
    version = _pinned_version(package)
    assert (
        minimum <= version < maximum
    ), f"{package} must stay within {minimum} and {maximum}"


def test_aiohttp_pin_is_python312_compatible() -> None:
    """Ensure the aiohttp dependency is new enough for Python 3.12 wheels."""

    major, minor, _ = _pinned_version("aiohttp")
    assert (major, minor) >= (
        3,
        9,
    ), "aiohttp must be >= 3.9 for Python 3.12 compatibility"


def test_yarl_pin_matches_aiohttp_expectations() -> None:
    """Ensure the yarl dependency stays aligned with aiohttp's requirements."""

    version = _pinned_version("yarl")
    assert version >= (
        1,
        18,
        3,
    ), "yarl must be >= 1.18.3 for aiohttp 3.11 compatibility"


def test_urllib3_pin_remains_below_major_two() -> None:
    """Ensure urllib3 stays within Home Assistant's supported range."""

    _assert_version_in_range("urllib3", (1, 26, 5), (2, 0, 0))


@pytest.mark.parametrize(
    ("package", "minimum", "maximum"),
    [
        pytest.param("httpcore", (1, 0, 0), (2, 0, 0), id="httpcore"),
        pytest.param("h11", (0, 16, 0), (1, 0, 0), id="h11"),
    ],
)
def test_http_stack_pins_match_expectations(
    package: str, minimum: Version, maximum: Version
) -> None:
    """Ensure the HTTP client stack stays within compatible version ranges."""

    _assert_version_in_range(package, minimum, maximum)


def test_homeassistant_pin_is_python313_guarded() -> None:
    """Ensure the homeassistant dependency only installs on Python 3.13+."""

    requirement = Requirement(_requirement_line("homeassistant"))
    assert str(requirement.specifier) == "==2024.12.5"
    assert (
        requirement.marker is not None
        and str(requirement.marker) == 'python_version >= "3.13"'
    ), "homeassistant pin must be gated for Python 3.13 environments"


@pytest.mark.parametrize(
    "package",
    sorted(EXPECTED_EXACT_VERSIONS.keys()),
    ids=lambda pkg: pkg,
)
def test_exact_pins_match_homeassistant(package: str) -> None:
    """Ensure exact pins align with Home Assistant's dependency graph."""

    _assert_exact_pin(package)
