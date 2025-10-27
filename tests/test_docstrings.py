"""Docstring coverage tests for key constructors."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from custom_components.govee_ultimate import config_flow
from custom_components.govee_ultimate.auth import GoveeAuthManager
from custom_components.govee_ultimate.device_client import DeviceListClient
from homeassistant.helpers.storage import Store


@pytest.mark.parametrize(
    ("constructor", "message"),
    (
        (GoveeAuthManager.__init__, "GoveeAuthManager.__init__ missing docstring"),
        (DeviceListClient.__init__, "DeviceListClient.__init__ missing docstring"),
        (Store.__init__, "Store.__init__ missing docstring"),
    ),
)
def test_constructor_docstrings(constructor: Callable[..., None], message: str) -> None:
    """All targeted constructors should expose explanatory docstrings."""

    assert constructor.__doc__, message


def test_config_flow_stub_flow_result_type_docstring() -> None:
    """The config flow fallback FlowResultType should include guidance."""

    assert config_flow.FlowResultType.__doc__ == (
        "Document stub flow result values when Home Assistant is unavailable."
    )
