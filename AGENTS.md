# Agent Guidelines

This repository is the Home Assistant custom component port of the [`constructorfleet/ultimate-govee`](https://github.com/constructorfleet/ultimate-govee) TypeScript library, effectively serving as the Home-Assistant-focused adaptation of that project.

## Project Context
- Source TypeScript library: constructorfleet/ultimate-govee
- Purpose: expose the same capabilities within Home Assistant through a custom component integration.
- Alignment: maintain feature parity and consistent API semantics with the upstream library where applicable.
- Protocol coverage: op codes map directly to the BLE and cloud command identifiers defined in the upstream library; keep the
  catalogue (`custom_components/govee/data/opcode_catalog.json`) synchronized with the source repository when new
  command types land.
- Device states: state models are data driven via `custom_components/govee/data/device_states.json` and
  `custom_components/govee/state/states.py`, mirroring the TypeScript definitions of device types, report op codes, and
  setter command templates.

## Contributor Notes
- When adding new capabilities, consult the upstream TypeScript implementation to ensure the Home Assistant port stays synchronized.
- Document any deviations from the upstream behavior in this file to aid future agents.
- Prefer writing or updating tests that mirror behaviors covered in the TypeScript project before porting functionality.
- Always describe new op codes, including request and report semantics, and link them to the device types and states they affect.
- If a device type introduces additional state payload shapes (for example, timers, schedules, or RGB values), extend the
  catalogue data and state handlers to keep automation parity with the upstream TypeScript implementation.
- Before opening a pull request, run the formatting and linting suite (`scripts/lint`) and execute the full test suite (`pytest`)
  so reviewers receive green builds.
