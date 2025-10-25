"""Ensure storage helper uses best-practice helpers."""

import inspect

from homeassistant.helpers.storage import Store

_SUPPRESS_SENTINEL = "contextlib.suppress"


def test_async_remove_uses_contextlib_suppress() -> None:
    """async_remove should use contextlib.suppress for file removal."""

    source = inspect.getsource(Store.async_remove)
    assert _SUPPRESS_SENTINEL in source
