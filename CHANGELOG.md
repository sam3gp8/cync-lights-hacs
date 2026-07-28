# Changelog

All notable changes to this integration are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versioning follows [Semantic Versioning](https://semver.org/) (MAJOR.MINOR.PATCH — patch for fixes, minor for new features, major for breaking changes).

## [1.1.2] - 2026-07-28

### Changed
- Replaced `icon.png` and `logo.png` with the official Cync mark artwork. `icon.png` is normalized to 256×256 for the HACS tile. No integration code changed.

## [1.1.1] - 2026-07-28

### Added
- Repo-root `icon.png` (256×256) and `logo.png` (512×512) with the Cync mark, so HACS shows a proper tile image for the integration instead of a placeholder.
- `CONTRIBUTING.md` with bug-report guidance that points to the new diagnostics download.

### Changed
- The distributed repo archive now extracts with its contents at the top level (`custom_components/`, `hacs.json`, `README.md`, `icon.png`, … directly at the archive root, with no wrapper folder) — matching the standard HACS repository layout. Extract it straight into an empty repo and the tree is correct with nothing to move. No integration code changed.

## [1.1.0] - 2026-07-23

### Added
- **Downloadable diagnostics.** Home Assistant now shows a "Download diagnostics" option on the Cync Lights config entry and on each Cync device (Settings → Devices & Services → Cync Lights → three-dot menu, or the same menu on an individual device page). Built specifically to make the intermittent "device became unavailable" problem debuggable after the fact — capture a download at the moment a device is showing unavailable and the cause is usually visible in the connection section.
  - **Connection block:** whether the cloud connection is live, seconds since the last state push from the cloud, whether that has crossed the staleness threshold, total reconnect count, seconds since the last reconnect, the poll interval, and the coordinator's `last_update_success`. If devices are dropping because the cloud has gone quiet, `last_cloud_push_s_ago` climbing past `stale_threshold_s` (300s) shows it directly.
  - **Summary block:** device/online/offline counts and an explicit list of which devices are currently offline.
  - **Per-device records:** type, capabilities, current power/brightness, and — key for this problem — how many seconds ago each device last changed state and was last seen online. Offline devices are listed first.
  - Credentials and tokens (`username`, `password`, `access_token`, `refresh_token`, `authorize`, `user_id`) are redacted from the download. All timestamps are relative ("seconds ago") rather than wall-clock, so no location/timezone data leaks either.
- Coordinator now tracks reconnect count, connection timestamp, and per-device last-change / last-online timestamps to support the above.

## [1.0.6] - 2026-07-23

### Fixed
- **HACS download failed with `No manifest.json file found 'custom_components/None/manifest.json'`.** The literal `None` in that path is HACS reporting that it could not resolve the integration's domain — it does so by listing `custom_components/*/` at the **repository root** and reading `domain` from the manifest inside. Getting `None` means nothing was found there.
  - Cause: the distributed repo archive wrapped everything in a top-level `cync-lights-hacs/` folder. Committing that folder as-is produces `<repo-root>/cync-lights-hacs/custom_components/cync_lights/` on GitHub — one level too deep for HACS, which only ever looks at `<repo-root>/custom_components/`.
  - The repo archive now has its contents at the archive root (`custom_components/`, `hacs.json`, `README.md`, … with no wrapper directory), so extracting it into a cloned repo produces the layout HACS requires.

### Note
No integration code changed in this release. The version bump exists so a clean release tag can be published — the `1.0.5` tag's tree has the wrong layout and HACS caches per-ref repository structure.

## [1.0.5] - 2026-07-23

### Fixed
- **Manual install failed with a missing `manifest.json`.** The distributed zip was packaged with the *repository* at its root, so extracting it into `/config/custom_components/` produced `/config/custom_components/cync-lights-hacs/custom_components/cync_lights/manifest.json`. Home Assistant looks for `manifest.json` directly inside `/config/custom_components/<domain>/`, found a folder without one, and refused to load the integration. Releases now additionally ship an install-ready archive whose root **is** the `cync_lights` folder, so it extracts straight into `/config/custom_components/` with the correct depth.
- Removed `aiohttp` from `manifest.json` `requirements`. It is bundled with Home Assistant core, and declaring it (with a version constraint, no less) makes HA attempt a pip resolution during setup — which can fail or conflict in constrained environments and prevent the integration from loading. Nothing about the code changes; `pycync` still imports `aiohttp` from core.
- Normalized `manifest.json` key ordering to what `hassfest` expects (`domain`, `name`, then remaining keys alphabetically).

## [1.0.4] - 2026-06-29

### Fixed
- **Devices getting permanently stuck "unavailable", with no log output from the integration.** Several separate problems compounded here:
  - **No periodic polling.** The coordinator was created with `update_interval=None` and an `async_refresh_states()` helper that was never actually scheduled — a leftover from the add-on conversion, where a `_refresh_loop()` task handled this. State therefore arrived *only* via pycync's push callback, with nothing to recover if that stopped.
  - **No recovery after a dropped connection.** pycync reconnects its own TCP socket (`_read_task_finished` retries after 10s), but nothing re-syncs device state afterwards. Devices whose `is_online` flag flipped to `False` during the outage stayed `False` indefinitely, which is exactly what surfaces as a permanently unavailable entity. The coordinator now tracks when the cloud last pushed anything and rebuilds the entire connection if it has gone quiet for `STALE_PUSH_SECONDS` (5 minutes).
  - **No token refresh.** `Cync.refresh_credentials()` existed but was never called, so an expiring access token would silently kill the connection. Now refreshed automatically when within 24 hours of expiry, and the new token is persisted back to the config entry.
  - **Effectively no logging.** The only `_LOGGER` calls in the integration were exception handlers in the config flow, so a healthy-but-idle integration genuinely produced zero output — matching the reported "no activity even with a reload". pycync's own messages also log under the `pycync.*` logger namespace rather than `custom_components.cync_lights`, so filtering by this integration hid them. Connect, reconnect, device load, token refresh, per-device online/offline transitions, and poll cycles are now all logged.
- Entities no longer raise `KeyError` out of a property if a device is briefly absent from the coordinator cache; they fall back to their last known state and read as unavailable instead. `_load_devices()` also now updates existing device records in place rather than clearing and rebuilding the dict, so entity references survive a reconnect.
- `available` now also reflects coordinator health (`last_update_success`), so a dead cloud connection shows as unavailable rather than a stale on/off state.
- Removed a stray `{pycync` directory that was being shipped inside `custom_components/cync_lights/` — an artifact of a `mkdir` brace-expansion that silently failed under `/bin/sh` when the package was first scaffolded.

### Changed
- Default poll interval is now 60s (was an unused 30s constant).

To see the new diagnostics, add this to `configuration.yaml` and restart:

```yaml
logger:
  logs:
    custom_components.cync_lights: debug
    pycync: info
```

## [1.0.3] - 2026-06-29

### Fixed
- **Root cause of the recurring "Home ID not found on user account" error.** The traceback finally showed it plainly: the failing code was executing from `/usr/local/lib/python3.14/site-packages/pycync/...` — a real, separately-installed `pycync` package (almost certainly a dependency of Home Assistant's own official Cync integration), not our vendored copy at `custom_components/cync_lights/pycync/`.
  - Every file inside our vendored `pycync/` used absolute imports internally (e.g. `from pycync.tcp.command_client import CommandClient`). Since `pycync` also exists as a real top-level package in this environment, Python's import resolver could bind those internal cross-references to the *other* package instead of a sibling file in our own copy.
  - In practice this meant a device object built by *our* `Cync`/`Auth` classes could end up with a `_command_client` attribute that was an instance from the *real* package — which has its own separate, never-populated `device_storage`. Every command attempt failed because that module's home registry was empty for the user, regardless of how correct our own `device_storage` was.
  - Converted all internal imports across `pycync/` (9 files: `__init__.py`, `cync.py`, `tcp/packet_parser.py`, `tcp/tcp_manager.py`, `tcp/command_client.py`, `devices/devices.py`, `devices/groups.py`, `devices/controllable.py`, `devices/device_storage.py`) to relative imports (`from .x import y` / `from ..x import y`), so the vendored copy can never resolve to anything other than itself, regardless of what else is installed in the environment.
  - Verified in isolation: `device_storage` now resolves to the identical module object no matter which file inside the package imports it.

The two previous attempts at this error (v1.0.1's `int()` cast fix) were real and worth keeping, but were treating a symptom — type mismatches inside *our own* `device_storage` — when the actual failures were happening inside a *different* `device_storage` entirely.

## [1.0.2] - 2026-06-29

### Added
- One-click "Open in HACS" badge in the README, using the official My Home Assistant redirect service. Opens HACS directly to this repository's download page instead of requiring people to manually paste the repo URL into HACS's custom repositories dialog.

## [1.0.1] - 2026-06-29

### Fixed
- `light.async_turn_on` / `async_turn_off` crashed with `'CyncDevice' object has no attribute 'turn_on'` for plain on/off devices (e.g. type 52 WiFi switches). pycync only attaches `turn_on()`/`turn_off()` to its `CyncLight` subclass — base `CyncDevice` objects need to go through the command client's `set_power_state()` instead. `light.py` now checks `isinstance(pd, CyncLight)` and falls back accordingly.
- Commands intermittently failed with `Home ID <id> not found on user account <id>` even though the account and device were correct. Root cause: `pycync/auth.py` built the `User` object straight from the REST API's raw JSON (`user_info["user_id"]`) with no type cast, while the saved-token restore path in `coordinator.py` explicitly cast to `int`. A fresh login and a restored session could end up registering/looking up the same user's homes under two different dict key types (`"123"` vs `123`), causing lookups to silently miss.
  - `auth.py`: both login paths now cast `user_id` to `int` at the source.
  - `pycync/devices/device_storage.py`: added a `_norm()` helper so every lookup/store function normalizes `user_id` to `int` before touching the internal dict, closing off this class of bug regardless of caller.

## [1.0.0] - 2026-06-29

### Added
- Initial release. Converted from the standalone `cync-lights-bridge` Home Assistant OS add-on into a native HACS integration.
- Config flow setup (email + password, with a second step for two-factor codes).
- Native `light`, `switch`, and `fan` entities backed by a `DataUpdateCoordinator` connected to the Cync cloud.
- Device classification by `device_type_id` (plugs: 64–77, fans: 113–116, everything else: light).
- Token persistence in the config entry — no repeated 2FA prompts after restarts.
- Vendored `pycync` cloud client (cloud TCP connection to `cm-sec.gelighting.com:23779`, same approach as cync-lan).
