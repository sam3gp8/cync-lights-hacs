# Cync Lights

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/sam3gp8/cync-lights-hacs)](https://github.com/sam3gp8/cync-lights-hacs/releases)
[![License](https://img.shields.io/github/license/sam3gp8/cync-lights-hacs)](LICENSE)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-donate-yellow.svg)](https://www.buymeacoffee.com/sam3gp8)

See [CHANGELOG.md](CHANGELOG.md) for release history.

A native Home Assistant integration for GE / Savant **Cync** smart lights, plugs, and fans. Connects directly to the Cync cloud and creates `light`, `switch`, and `fan` entities — no MQTT broker, no separate add-on container, no YAML to hand-edit. Just add the integration through the Home Assistant UI.

## Features

- Config-flow setup (email + password, with two-factor code support)
- Automatic device discovery — lights, plugs, and fans show up as native HA entities
- Push-based state updates from the Cync cloud
- Token persisted in the config entry, so you won't be asked to re-authenticate after a Home Assistant restart
- Brightness, color temperature, and RGB control where the device supports it

## Installation

### One-click (easiest)

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=sam3gp8&repository=cync-lights-hacs&category=integration)

Click the badge above (must be opened from a browser on the same network as your Home Assistant instance, with [My Home Assistant](https://www.home-assistant.io/integrations/my/) enabled). It opens HACS directly to this repository — click **Download**, then restart Home Assistant.

### Via HACS (manual add)

1. In Home Assistant, go to **HACS → Integrations**.
2. Click the **⋮** menu (top right) → **Custom repositories**.
3. Add `https://github.com/sam3gp8/cync-lights-hacs` as an **Integration**.
4. Find **Cync Lights** in HACS and click **Download**.
5. Restart Home Assistant.

### Manual install (no HACS)

1. Copy the `custom_components/cync_lights` folder from this repo into your Home Assistant's `config/custom_components/` directory.
2. Restart Home Assistant.

## Setup

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Cync Lights**.
3. Enter the email and password you use for the Cync app.
4. If your account has two-factor authentication enabled, you'll be prompted for the one-time code Cync emails you.
5. Your devices will appear automatically as `light`, `switch`, or `fan` entities, grouped by device.

## Grouping devices

This integration creates one entity per device. For multi-device control (e.g. "all kitchen lights"), use Home Assistant's built-in **Areas** or the **Light Group** / **Switch Group** helpers (Settings → Devices & Services → Helpers → Create Helper) rather than a custom grouping feature — it integrates better with the rest of Home Assistant (scripts, automations, voice assistants).

## Known limitations

- Requires an internet connection — this connects to the Cync cloud rather than controlling devices purely on the local network. (This matches how the official Cync app and other community integrations like cync-lan operate.)
- Dimmable/color features depend entirely on what your specific Cync device model supports; plain on/off switches will only expose an on/off control.

## Support this project

If this integration is useful to you, consider [buying me a coffee](https://www.buymeacoffee.com/sam3gp8) ☕

## Issues & contributions

Found a bug or want to contribute? Open an issue or pull request at [github.com/sam3gp8/cync-lights-hacs](https://github.com/sam3gp8/cync-lights-hacs).

## License

MIT — see [LICENSE](LICENSE).
