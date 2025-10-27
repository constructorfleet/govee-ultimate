"""Verify essential third-party modules are stubbed for tests."""

from __future__ import annotations


def test_httpx_stub_is_available() -> None:
    """Importing httpx should succeed via the test stubs."""

    import httpx  # noqa: F401


def test_pydantic_stub_is_available() -> None:
    """Importing pydantic should succeed via the test stubs."""

    import pydantic  # noqa: F401


def test_yaml_stub_is_available() -> None:
    """Importing yaml should succeed via the test stubs."""

    import yaml  # noqa: F401
