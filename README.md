# Govee Ultimate for Home Assistant

This repository contains the Home Assistant custom integration that mirrors the
capabilities of the [`constructorfleet/ultimate-govee`](https://github.com/constructorfleet/ultimate-govee)
project. It exposes a full-featured control surface for compatible Govee
Bluetooth and cloud-connected devices directly from your Home Assistant
instance.

## Key features

- Unified Home Assistant entities for lights, climate controllers, appliances,
  and sensors supported by the upstream Ultimate Govee library.
- Data-driven state catalogue shared with the TypeScript project to keep
  behavior consistent across ecosystems.
- Cloud and BLE command handling designed to match the original application
  semantics, enabling advanced automation scenarios.

## Installation

1. Ensure Home Assistant 2023.8 or newer is installed.
2. Copy the `custom_components/govee_ultimate` directory from this repository to
   `<config>/custom_components/govee_ultimate` within your Home Assistant
   configuration directory.
3. Restart Home Assistant to load the integration.
4. Use the Home Assistant UI to add the **Govee Ultimate** integration and
   authenticate with your Govee credentials when prompted.

For development, the repository includes helper scripts under `scripts/` and a
comprehensive pytest suite under `tests/` to keep parity with the upstream
feature set.

## Contributing

Contributions that expand device support or align behavior with the upstream
Ultimate Govee project are welcome. Please review `CONTRIBUTING.md` for
workflow expectations and open a pull request when your changes are ready.
