"""Ice maker device wiring mirroring the Ultimate Govee implementation."""

from __future__ import annotations

from typing import Any

from custom_components.govee_ultimate.state import (
    ActiveState,
    ConnectedState,
    PowerState,
)
from custom_components.govee_ultimate.state.states import (
    IceMakerBasketFullState,
    IceMakerMakingIceState,
    IceMakerNuggetSizeState,
    IceMakerScheduledStartState,
    IceMakerStatusState,
    IceMakerTemperatureState,
    IceMakerWaterEmptyState,
)

from .base import BaseDevice, EntityCategory


class IceMakerDevice(BaseDevice):
    """Home Assistant wrapper for Govee countertop ice makers."""

    def __init__(self, device_model: Any) -> None:
        """Register ice maker specific states and entity metadata."""

        super().__init__(device_model)

        power = self.add_state(PowerState(device_model))
        self.expose_entity(platform="switch", state=power)

        connected = self.add_state(ConnectedState(device=device_model))
        self.expose_entity(
            platform="binary_sensor",
            state=connected,
            translation_key="connected",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

        active = self.add_state(ActiveState(device_model))
        self.expose_entity(
            platform="binary_sensor",
            state=active,
            entity_category=EntityCategory.DIAGNOSTIC,
        )

        status = self.add_state(IceMakerStatusState(device=device_model))
        self._status_state = status
        self.expose_entity(platform="sensor", state=status)

        nugget_size = self.add_state(IceMakerNuggetSizeState(device=device_model))
        self._nugget_size_state = nugget_size
        self.expose_entity(platform="select", state=nugget_size)

        basket_full = self.add_state(IceMakerBasketFullState(device=device_model))
        self.expose_entity(
            platform="binary_sensor",
            state=basket_full,
            entity_category=EntityCategory.DIAGNOSTIC,
        )

        water_shortage = self.add_state(IceMakerWaterEmptyState(device=device_model))
        self.alias_state("water_shortage", water_shortage)
        self.expose_entity(
            platform="binary_sensor",
            state=water_shortage,
            entity_category=EntityCategory.DIAGNOSTIC,
        )

        self._scheduled_start_state = self.add_state(
            IceMakerScheduledStartState(device=device_model)
        )
        self.expose_entity(
            platform="sensor",
            state=self._scheduled_start_state,
            translation_key="ice_maker_scheduled_start",
            entity_category=EntityCategory.CONFIG,
        )

        temperature = self.add_state(IceMakerTemperatureState(device=device_model))
        self.expose_entity(
            platform="sensor",
            state=temperature,
            translation_key="temperature",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

        make_ice = self.add_state(
            IceMakerMakingIceState(
                device=device_model,
                status_state=status,
            )
        )
        self.expose_entity(
            platform="binary_sensor",
            state=make_ice,
            entity_category=EntityCategory.DIAGNOSTIC,
        )
