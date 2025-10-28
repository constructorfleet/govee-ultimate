# Govee Ultimate Integration

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

Control your supported Govee devices through Home Assistant using the
functionality ported from the Ultimate Govee project.

**This integration currently provides the following Home Assistant platforms:**

Platform | Description
-- | --
`light` | Manage supported Govee light products with full color and effects control.
`sensor` | Surface telemetry reported by the device catalogue.
`switch` | Toggle power and exposed device features.

## Installation

1. Open your Home Assistant configuration directory (the folder containing
   `configuration.yaml`).
2. Copy the `custom_components/govee_ultimate` folder from this repository into
   `<config>/custom_components/`.
3. Restart Home Assistant to load the integration.
4. Navigate to **Settings → Devices & Services**, choose **Add Integration**, and
   search for **Govee Ultimate**.
5. Follow the on-screen prompts to authenticate with your Govee account.

## Configuration

The configuration flow guides you through account authentication and device
selection. Advanced options, such as enabling BLE support or experimental
features, can be adjusted from the integration options once setup completes.

## Contributions are welcome!

If you want to contribute please read the [Contribution guidelines](CONTRIBUTING.md)
and open an issue or pull request describing your improvement.

***

[commits-shield]: https://img.shields.io/github/commit-activity/y/constructorfleet/ultimate-govee.svg?style=for-the-badge
[commits]: https://github.com/constructorfleet/ultimate-govee/commits/main
[license-shield]: https://img.shields.io/github/license/constructorfleet/ultimate-govee.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/constructorfleet/ultimate-govee.svg?style=for-the-badge
[releases]: https://github.com/constructorfleet/ultimate-govee/releases
