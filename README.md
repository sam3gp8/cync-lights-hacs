# Cync Lights

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=sam3gp8&repository=cync-lights-hacs&category=integration)
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

## Local control (optional, experimental)

By default the integration talks to the Cync cloud. It can optionally run a **local server** that physical Cync devices connect to instead, so commands keep working without internet. Enable it under **Settings → Devices & Services → Cync Lights → Configure**.

For devices to reach the local server, the hostname they dial (`cm-sec.gelighting.com`) has to resolve to the Home Assistant host. You can do that three ways:

- **Built-in DNS server** (no add-on needed) — tick *Run a built-in DNS server* and set the Home Assistant IP, then point your **router/DHCP at the Home Assistant host as the DNS server** for the Cync devices (ideally scoped to their subnet/VLAN). Home Assistant can only answer queries that are actually sent to it.
- **AdGuard Home** — let the integration manage the rewrite automatically (enter your AdGuard URL/credentials).
- **Your own DNS** — point `cm-sec.gelighting.com` (and `cm.gelighting.com`) at the Home Assistant host in whatever resolver you run.

> **Important:** the cloud client inside the integration *also* connects to `cm-sec.gelighting.com`, so the **Home Assistant host itself must use a direct upstream resolver** (Settings → System → Network → DNS), **not** the integration's built-in DNS server. Point only the devices (via your router/DHCP) at Home Assistant for DNS — if the HA host resolves `cm-sec` to itself, its next cloud reconnect lands on the local server.

Local control is experimental: devices farther from your access points may drop in and out of the local connection. The cloud connection keeps working regardless, and the feature is entirely opt-in.

## Known limitations

- By default this connects to the Cync cloud rather than controlling devices purely on the local network (this matches how the official Cync app and other community integrations like cync-lan operate). See **Local control** above for the experimental offline path.
- Dimmable/color features depend entirely on what your specific Cync device model supports; plain on/off switches will only expose an on/off control.
- Dimmable/color features depend entirely on what your specific Cync device model supports; plain on/off switches will only expose an on/off control.

## Troubleshooting

### Some devices show "unavailable"

First, **download diagnostics**: Settings → Devices & Services → Cync Lights → the three-dot menu → **Download diagnostics** (or the same menu on a specific device page). Credentials and tokens are automatically redacted. Look at the `connection` block:

- **`is_stale: true`, or `last_update_success: false`, or a rising `reconnect_count`** → the integration's connection to the Cync cloud is the problem. It rebuilds itself automatically after `stale_threshold_s` (5 minutes), so give it a few minutes; if it doesn't recover, reload the integration.
- **`connection` looks healthy** (`connected: true`, `is_stale: false`, `last_update_success: true`, `reconnect_count: 0`) **but devices are still unavailable** → the problem is almost always on the **Cync account side**, not this integration. The integration reports exactly what the Cync cloud tells it, and a stale account session can make the cloud report devices as offline to everything using that session.

  The fix that reliably clears this: **open the official Cync app and re-authenticate it** — sign out and back in, or delete and reinstall the app and log in again. Toggle the affected devices once in the app to confirm they respond. This refreshes your account's device state on Cync's servers; the integration will then see the devices come back online, usually within a poll cycle (60s) or after a reload.

- **One specific device is persistently offline while everything else is fine** → check that switch physically (power, Wi-Fi signal). Confirm whether it also shows offline in the official Cync app — if it does, it's a device/network issue, not something the integration can resolve.

### Enabling debug logs

Add this to `configuration.yaml`, restart, and reproduce the issue:

```yaml
logger:
  logs:
    custom_components.cync_lights: debug
    pycync: info
```

Note that pycync's own messages log under the `pycync` namespace, not `custom_components.cync_lights`, so include both.

## Support this project

If this integration is useful to you, consider [buying me a coffee](https://www.buymeacoffee.com/sam3gp8) ☕


## Issues & contributions

Found a bug or want to contribute? Open an issue or pull request at [github.com/sam3gp8/cync-lights-hacs](https://github.com/sam3gp8/cync-lights-hacs).

## License

MIT — see [LICENSE](LICENSE).
