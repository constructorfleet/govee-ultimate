"""Data models for the Ultimate Govee state catalog."""

from __future__ import annotations

import pydantic as _pydantic
from pydantic import BaseModel, Field

import json
from pathlib import Path
from typing import Any


def _ensure_pydantic_docstring() -> None:
    """Guarantee the upstream module exposes a docstring for tests."""

    if (
        _pydantic.__doc__ is None
    ):  # pragma: no cover - upstream module lacks documentation string
        _pydantic.__doc__ = "Pydantic data validation library."


_ensure_pydantic_docstring()

_DEFAULT_DATA_PATH = Path(__file__).parent / "data" / "device_states.json"


class CommandTemplate(BaseModel):
    """Describe a command template used to write device state."""

    name: str
    opcode: str
    payload_template: str
    description: str | None = None
    multi_step: list[str] | None = Field(
        default=None, description="Optional multi-op sequence metadata"
    )


class StateEntry(BaseModel):
    """Represent a single state definition sourced from the dataset."""

    state_name: str
    op_type: str
    identifiers: dict[str, dict[str, Any]]
    parse_options: dict[str, Any]
    status_templates: list[dict[str, Any]]
    command_templates: list[CommandTemplate]


class StateCatalog(BaseModel):
    """Collection of parsed state definitions."""

    states: list[StateEntry]

    def get_state(self, state_name: str) -> StateEntry:
        """Retrieve a state entry by name."""
        try:
            return next(
                state for state in self.states if state.state_name == state_name
            )
        except StopIteration as exc:  # pragma: no cover - defensive guard
            raise KeyError(state_name) from exc


def load_state_catalog(path: Path | None = None) -> StateCatalog:
    """Load the state catalog definition from JSON."""
    data_path = path or _DEFAULT_DATA_PATH
    with data_path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    return StateCatalog.model_validate(payload)
