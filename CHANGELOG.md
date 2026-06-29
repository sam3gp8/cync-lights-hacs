# Changelog

All notable changes to this integration are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versioning follows [Semantic Versioning](https://semver.org/) (MAJOR.MINOR.PATCH — patch for fixes, minor for new features, major for breaking changes).

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
