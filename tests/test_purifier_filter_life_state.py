"""Tests for purifier filter life state parsing."""

from __future__ import annotations

from typing import Any
from collections.abc import Callable

import pytest

from custom_components.govee_ultimate.device_types.purifier import PurifierDevice
from custom_components.govee_ultimate.state.states import FilterLifeState, ParseOption


class DummyDevice:
    """Simple device stub exposing identifier metadata."""

    def __init__(self, *, model: str = "H7126") -> None:
        """Initialise purifier metadata for tests."""

        self.model = model
        self.sku = model
        self.category = "Home Appliances"
        self.category_group = "Air Treatment"
        self.model_name = "Purifier"
        self._listeners: list[Callable[[dict[str, Any]], None]] = []

    def add_status_listener(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Record listeners to simulate device callbacks."""

        self._listeners.append(callback)


@pytest.fixture
def device() -> DummyDevice:
    """Return a purifier device stub."""

    return DummyDevice()


@pytest.fixture
def filter_life_state(device: DummyDevice) -> FilterLifeState:
    """Return a filter life state bound to a dummy device."""

    return FilterLifeState(device=device, identifier=[0x19])


def test_filter_life_state_parses_opcode_payload(
    filter_life_state: FilterLifeState,
) -> None:
    """Opcode payloads should update the filter life percentage."""

    payload = {"cmd": "status", "op": {"command": [[0xAA, 0x19, 0x4B]]}}

    filter_life_state.parse(payload)

    assert filter_life_state.value == 75


def test_filter_life_state_falls_back_to_rest_payload(
    filter_life_state: FilterLifeState,
) -> None:
    """REST payloads should populate filter life when opcode data is absent."""

    payload = {"cmd": "status", "state": {"filterLife": 63}}

    filter_life_state.parse(payload)

    assert filter_life_state.value == 63


def test_purifier_filter_life_state_uses_opcode_identifier(device: DummyDevice) -> None:
    """Purifier devices should wire filter life state with opcode metadata."""

    purifier = PurifierDevice(device)
    state = purifier.states["filterLife"]

    assert isinstance(state, FilterLifeState)
    assert state.parse_option == ParseOption.OP_CODE | ParseOption.STATE

    payload = {"cmd": "status", "op": {"command": [[0xAA, 0x19, 0x32]]}}

    state.parse(payload)

    assert state.value == 50
