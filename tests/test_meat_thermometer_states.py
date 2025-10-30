"""Tests for the meat thermometer specific state handlers."""

from __future__ import annotations

import inspect
import json
from typing import Any

import pytest

from custom_components.govee_ultimate.state import states
from custom_components.govee_ultimate.state.states import (
    BuzzerState,
    EarlyWarningState,
    EarlyWarningEnabledState,
    EarlyWarningSettingState,
    PresetState,
    ProbeTempState,
    TemperatureUnitState,
)


class DummyDevice:
    """Minimal device stub recording status callbacks."""

    def __init__(self) -> None:
        """Initialise callback storage."""

        self._callbacks: list[Any] = []

    def add_status_listener(self, callback: Any) -> None:
        """Record the provided callback for inspection."""

        self._callbacks.append(callback)


def _build_probe_commands() -> list[list[int]]:
    """Return a multi-op payload representing four probe readings."""

    base = [0xE4, 0x00, 0x01, 0x03, 0x03, 0x00, 0x01, 0x00, 0x00, 0x00]

    probe1 = [0x0B, 0xB8, 0x0C, 0x1C, 0x0A, 0xF0, 0x00, 0x00, 0x03]
    probe2 = [0x09, 0xC4, 0x0A, 0x28, 0x09, 0xC4, 0x05, 0x00, 0x01]
    probe3 = [0x0C, 0x80, 0x0D, 0x48, 0x0B, 0xB8, 0x06, 0x00, 0x02]
    probe4 = [0x07, 0xD0, 0x08, 0x34, 0x06, 0xA4, 0x0B, 0x00, 0x01]

    return [base + probe1 + probe2, probe3 + probe4]


@pytest.mark.parametrize(
    "probe, expected", [(1, 30.0), (2, 25.0), (3, 32.0), (4, 20.0)]
)
def test_probe_temp_state_parses_multi_op_chunks(probe: int, expected: float) -> None:
    """Probe temperature state should flatten multi-op payloads per probe."""

    device = DummyDevice()
    state = ProbeTempState(device=device, probe=probe)

    state.parse({"op": {"command": _build_probe_commands()}})

    assert state.value == pytest.approx(expected)


def test_buzzer_state_reflects_device_flag() -> None:
    """Buzzer state should report enabled/disabled based on header byte."""

    device = DummyDevice()
    state = BuzzerState(device=device)

    state.parse({"op": {"command": _build_probe_commands()}})

    assert state.value is True


def test_temperature_unit_state_decodes_unit_marker() -> None:
    """Temperature unit state should map flag values to symbols."""

    device = DummyDevice()
    state = TemperatureUnitState(device=device)

    state.parse({"op": {"command": _build_probe_commands()}})

    assert state.value == "F"


def test_early_warning_state_exposes_setting_and_enabled() -> None:
    """Early warning state should return the configured offset level."""

    device = DummyDevice()
    state = EarlyWarningState(device=device)

    state.parse({"op": {"command": _build_probe_commands()}})

    assert state.value == {"enabled": True, "setting": "MEDIUM"}


def test_early_warning_state_reports_low_setting_and_json_contract() -> None:
    """Early warning state should expose the low setting as a plain string."""

    device = DummyDevice()
    state = EarlyWarningState(device=device)

    commands = [list(command) for command in _build_probe_commands()]
    commands[0][3] = 1
    commands[0][4] = 1

    state.parse({"op": {"command": commands}})

    expected = {"enabled": True, "setting": "low"}

    assert state.value == expected
    assert json.dumps(state.value, sort_keys=True) == json.dumps(
        expected, sort_keys=True
    )


@pytest.mark.parametrize(
    "probe, food, high, low, done",
    [
        (1, "BEEF", 31.0, 28.0, "MEDIUM"),
        (2, "FISH", 26.0, 25.0, "REFERENCE"),
        (3, "DIY", 34.0, 30.0, "HIGH"),
        (4, "POTATO", 21.0, 17.0, "REFERENCE"),
    ],
)
def test_preset_state_parses_food_and_alarm_ranges(
    probe: int, food: str, high: float, low: float, done: str
) -> None:
    """Preset state should decode food, alarms, and doneness per probe."""

    device = DummyDevice()
    state = PresetState(device=device, probe=probe)

    state.parse({"op": {"command": _build_probe_commands()}})

    assert state.value == {
        "food": food,
        "alarm": {"high": pytest.approx(high), "low": pytest.approx(low)},
        "doneLevel": done,
    }


def test_early_warning_setting_wrapper_surfaces_offset() -> None:
    """Early warning setting wrapper should mirror the parsed offset."""

    device = DummyDevice()
    state = EarlyWarningState(device=device)
    wrapper = EarlyWarningSettingState(source=state)

    state.parse({"op": {"command": _build_probe_commands()}})

    assert wrapper.value == "MEDIUM"


def test_early_warning_enabled_wrapper_surfaces_flag() -> None:
    """Early warning enabled wrapper should surface the boolean flag."""

    device = DummyDevice()
    state = EarlyWarningState(device=device)
    wrapper = EarlyWarningEnabledState(source=state)

    state.parse({"op": {"command": _build_probe_commands()}})

    assert wrapper.value is True


def test_preset_state_options_follow_food_map_order() -> None:
    """Preset state options should mirror the upstream FoodMap sequence."""

    expected = tuple(states._FOOD_MAP.values())

    assert PresetState.options == expected
    assert "sorted(" not in inspect.getsource(PresetState)
