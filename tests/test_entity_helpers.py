"""Unit tests for the entity helper utilities in the integration.

These tests exercise small, self-contained helpers and do not modify
component code.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.govee import DOMAIN
from custom_components.govee.device_types.base import HomeAssistantEntity
from custom_components.govee.entity import (
    async_add_platform_entities,
    build_platform_entities,
    iter_platform_entities,
    resolve_coordinator,
)
from custom_components.govee.state.device_state import DeviceState


@pytest.mark.asyncio
async def test_async_add_platform_entities_handles_sync_and_async() -> None:
    """Test that both sync and async adders are supported."""
    called: dict[str, Any] = {"sync": False, "async": False}

    def sync_adder(entities: list[Any]) -> None:
        called["sync"] = True
        called["sync_entities"] = list(entities)

    async def async_adder(entities: list[Any]) -> None:
        # simulate async work
        await asyncio.sleep(0)
        called["async"] = True
        called["async_entities"] = list(entities)

    # Sync adder
    await async_add_platform_entities(sync_adder, [1, 2, 3])
    assert called["sync"] is True
    assert called.get("sync_entities") == [1, 2, 3]

    # Async adder
    await async_add_platform_entities(async_adder, ["a"])
    assert called["async"] is True
    assert called.get("async_entities") == ["a"]


def _make_ha_entity(name: str, platform: str = "light") -> HomeAssistantEntity:
    """Create a HomeAssistantEntity for testing purposes."""
    # DeviceState is simple enough to instantiate for tests
    state = DeviceState(device=None, name=name, initial_value=None)
    return HomeAssistantEntity(platform=platform, state=state)


def test_iter_and_build_platform_entities_work_together() -> None:
    """Test that iter_platform_entities and build_platform_entities work as expected."""
    # Create two devices with entities on different platforms
    ent_a = _make_ha_entity("power", platform="humidifier")
    ent_b = _make_ha_entity("active", platform="binary_sensor")

    device_a = SimpleNamespace(home_assistant_entities={"power": ent_a})
    device_b = SimpleNamespace(home_assistant_entities={"active": ent_b})

    coordinator = SimpleNamespace(devices={"dev-a": device_a, "dev-b": device_b})

    # iter_platform_entities should return only the matching platform
    matches = iter_platform_entities(coordinator, "humidifier")
    assert matches == [("dev-a", ent_a)]

    # build_platform_entities should construct instances via the factory
    def factory(coord, device_id, entity):
        return (device_id, entity.platform, entity.state.name)

    built = build_platform_entities(coordinator, "binary_sensor", factory)
    assert built == [("dev-b", "binary_sensor", "active")]


def test_resolve_coordinator_reads_hass_data() -> None:
    """Test that resolve_coordinator reads the coordinator from hass data."""
    hass = SimpleNamespace(data={DOMAIN: {"entry-1": {"coordinator": "co1"}}})
    entry = SimpleNamespace(entry_id="entry-1")

    assert resolve_coordinator(hass, entry) == "co1"

    # Missing entry returns None
    hass2 = SimpleNamespace(data={DOMAIN: {}})
    entry2 = SimpleNamespace(entry_id="nope")
    assert resolve_coordinator(hass2, entry2) is None
