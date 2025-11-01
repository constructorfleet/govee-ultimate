"""Presence sensor device wiring."""

from __future__ import annotations

from collections.abc import Callable
from types import MethodType
from typing import Any

from ..state import (
    BiologicalPresenceState,
    ConnectedState,
    DetectionSettingsState,
    EnablePresenceState,
    MMWavePresenceState,
    PowerState,
)
from ..state.device_state import DeviceState
from .base import BaseDevice, EntityCategory


class _PresenceEnableSwitchState(DeviceState[bool]):
    """Expose a boolean toggle backed by ``EnablePresenceState``."""

    def __init__(
        self,
        parent: EnablePresenceState,
        *,
        name: str,
        field: str,
    ) -> None:
        """Initialise the proxy switch state."""

        super().__init__(device=parent.device, name=name, initial_value=False)
        self._parent = parent
        self._field = field
        self._sync_from_parent()

    def _sync_from_parent(self) -> None:
        value = self._parent.value
        if isinstance(value, dict) and value.get(self._field) is not None:
            self._update_state(bool(value[self._field]))

    def set_state(self, next_state: bool) -> list[str]:
        """Route state changes through the parent enable state."""

        command_ids = self._parent.set_state({self._field: next_state})
        while not self._parent.command_queue.empty():
            payload = self._parent.command_queue.get_nowait()
            self.command_queue.put_nowait(payload)
        while not self._parent.clear_queue.empty():
            payload = self._parent.clear_queue.get_nowait()
            self.clear_queue.put_nowait(payload)
        return command_ids


class _DetectionSettingsNumberState(DeviceState[float | None]):
    """Expose a numeric field from ``DetectionSettingsState``."""

    def __init__(
        self,
        parent: DetectionSettingsState,
        *,
        name: str,
        field: str,
        unit: str | None,
    ) -> None:
        """Initialise the numeric proxy state."""

        super().__init__(device=parent.device, name=name, initial_value=None)
        self._parent = parent
        self._field = field
        self._unit = unit
        self._sync_from_parent()

    def _sync_from_parent(self) -> None:
        value = self._parent.value
        if isinstance(value, dict):
            field_value = value.get(self._field, {})
            if isinstance(field_value, dict) and field_value.get("value") is not None:
                numeric = field_value.get("value")
                try:
                    numeric_value = float(numeric)
                except (TypeError, ValueError):
                    return
                self._update_state(numeric_value)

    def set_state(self, next_state: float | None) -> list[str]:
        """Forward numeric updates through the parent detection state."""

        if next_state is None:
            return []
        payload: dict[str, dict[str, Any]] = {self._field: {"value": next_state}}
        if self._unit:
            payload[self._field]["unit"] = self._unit
        command_ids = self._parent.set_state(payload)
        while not self._parent.command_queue.empty():
            payload = self._parent.command_queue.get_nowait()
            self.command_queue.put_nowait(payload)
        while not self._parent.clear_queue.empty():
            payload = self._parent.clear_queue.get_nowait()
            self.clear_queue.put_nowait(payload)
        return command_ids


class PresenceDevice(BaseDevice):
    """Home Assistant device wrapper for presence sensors."""

    def __init__(self, device_model: Any) -> None:
        """Register presence sensor states and Home Assistant entities."""

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

        mmwave = self.add_state(MMWavePresenceState(device=device_model))
        self.expose_entity(
            platform="binary_sensor",
            state=mmwave,
            translation_key="presence_mmwave",
        )

        biological = self.add_state(BiologicalPresenceState(device=device_model))
        self.expose_entity(
            platform="binary_sensor",
            state=biological,
            translation_key="presence_biological",
        )

        enable = self.add_state(EnablePresenceState(device=device_model))
        detection = self.add_state(DetectionSettingsState(device=device_model))

        self._enable_proxies: list[_PresenceEnableSwitchState] = []
        self._detection_proxies: list[_DetectionSettingsNumberState] = []

        self._register_enable_switches(enable)
        self._register_detection_numbers(detection)

    def _register_enable_switches(self, enable: EnablePresenceState) -> None:
        """Create and expose switch proxies for presence enable flags."""

        mmwave_proxy = _PresenceEnableSwitchState(
            enable,
            name="presenceEnable-mmWave",
            field="mmWaveEnabled",
        )
        self._enable_proxies.append(mmwave_proxy)
        self.add_state(mmwave_proxy)
        self.expose_entity(
            platform="switch",
            state=mmwave_proxy,
            translation_key="presence_mmwave_enabled",
        )

        biological_proxy = _PresenceEnableSwitchState(
            enable,
            name="presenceEnable-biological",
            field="biologicalEnabled",
        )
        self._enable_proxies.append(biological_proxy)
        self.add_state(biological_proxy)
        self.expose_entity(
            platform="switch",
            state=biological_proxy,
            translation_key="presence_biological_enabled",
        )

        self._attach_state_update_hook(enable, self._sync_enable_proxies)

    def _register_detection_numbers(self, detection: DetectionSettingsState) -> None:
        """Expose detection tuning fields as number entities."""

        distance = _DetectionSettingsNumberState(
            detection,
            name="detectionDistance",
            field="detectionDistance",
            unit="cm",
        )
        self._detection_proxies.append(distance)
        self.add_state(distance)
        self.expose_entity(
            platform="number",
            state=distance,
            translation_key="presence_detection_distance",
            entity_category=EntityCategory.CONFIG,
        )

        absence = _DetectionSettingsNumberState(
            detection,
            name="absenceDuration",
            field="absenceDuration",
            unit="s",
        )
        self._detection_proxies.append(absence)
        self.add_state(absence)
        self.expose_entity(
            platform="number",
            state=absence,
            translation_key="presence_absence_duration",
            entity_category=EntityCategory.CONFIG,
        )

        report = _DetectionSettingsNumberState(
            detection,
            name="reportDetection",
            field="reportDetection",
            unit="s",
        )
        self._detection_proxies.append(report)
        self.add_state(report)
        self.expose_entity(
            platform="number",
            state=report,
            translation_key="presence_report_interval",
            entity_category=EntityCategory.CONFIG,
        )

        self._attach_state_update_hook(detection, self._sync_detection_proxies)

    def _attach_state_update_hook(
        self, state: DeviceState[Any], callback: Callable[[], None]
    ) -> None:
        """Wrap ``state`` updates so ``callback`` runs after each change."""

        original_update = state._update_state

        def _update_and_notify(self_state: DeviceState[Any], value: Any) -> None:
            original_update(value)
            callback()

        state._update_state = MethodType(_update_and_notify, state)

    def _sync_enable_proxies(self) -> None:
        """Synchronise enable proxies with the parent state."""

        for proxy in self._enable_proxies:
            proxy._sync_from_parent()

    def _sync_detection_proxies(self) -> None:
        """Synchronise detection proxies with the parent state."""

        for proxy in self._detection_proxies:
            proxy._sync_from_parent()
