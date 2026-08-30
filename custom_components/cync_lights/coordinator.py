"""DataUpdateCoordinator for the Cync Lights integration.

Manages the pycync cloud connection, authentication/token refresh, and
keeps a live device-state cache that platform entities read from.

Note on connection health: pycync reconnects its own TCP socket when it
drops, but it does not re-sync device state afterwards. Devices whose
`is_online` flag flipped to False during the outage stay False forever,
which surfaces in Home Assistant as permanently "unavailable" entities.
This coordinator therefore polls actively and rebuilds the whole
connection if the cloud stops pushing state altogether.
"""
from __future__ import annotations

import asyncio
import logging
import ssl
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    DEFAULT_SCAN_INTERVAL,
    STALE_PUSH_SECONDS,
    TOKEN_REFRESH_MARGIN,
    PLUG_TYPE_IDS,
    FAN_TYPE_IDS,
)
from .pycync.auth import Auth, AuthFailedError
from .pycync.cync import Cync
from .pycync.user import User
from .pycync.devices.devices import CyncLight
from .pycync.devices.capabilities import CyncCapability

_LOGGER = logging.getLogger(__name__)


def _make_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
    except ssl.SSLError:
        pass
    return ctx


_SSL_CONTEXT = _make_ssl_context()


@dataclass
class CyncDeviceState:
    """Lightweight, HA-facing snapshot of one Cync device's state."""

    pycync_dev: Any
    switch_id: int
    name: str
    device_type: int
    is_plug: bool = False
    is_fan: bool = False
    supports_brightness: bool = False
    supports_color_temp: bool = False
    supports_rgb: bool = False
    online: bool = False
    power: bool = False
    brightness: int = 0
    color_temp_kelvin: int = 0
    rgb: tuple[int, int, int] = (255, 255, 255)
    # Diagnostics: monotonic timestamps of the last state change and the last
    # time this device was reported online. Help pinpoint when/why a device
    # dropped to unavailable.
    last_change: float = 0.0
    last_online: float = 0.0


class CyncCoordinator(DataUpdateCoordinator[dict[int, CyncDeviceState]]):
    """Coordinates the pycync cloud connection for one Cync account."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.entry = entry
        self.username: str = entry.data[CONF_USERNAME]
        self.password: str = entry.data[CONF_PASSWORD]

        self._cync: Optional[Cync] = None
        self._auth: Optional[Auth] = None
        self.devices: dict[int, CyncDeviceState] = {}
        self._cmd_time: dict[int, float] = {}
        self._cmd_state: dict[int, bool] = {}

        # Monotonic timestamp of the last state push received from the cloud.
        self._last_push: float = time.monotonic()
        self._reconnecting = False
        # Diagnostics counters.
        self._reconnect_count: int = 0
        self._connected_at: float = 0.0
        self._last_reconnect_at: float = 0.0

    # -- Connection lifecycle ------------------------------------------------

    async def async_connect(self) -> None:
        """Authenticate (using the stored token if possible) and connect."""
        session = async_get_clientsession(self.hass)
        auth = Auth(session, username=self.username, password=self.password)

        data = self.entry.data
        restored = False
        user = None
        try:
            user = User(
                data["access_token"],
                data.get("refresh_token", ""),
                data["authorize"],
                int(data["user_id"]),
                expires_at=data.get("expires_at") or (time.time() + 604800),
            )
            auth._user = user  # noqa: SLF001 - restoring a saved session
            restored = True
            _LOGGER.debug("Restored saved Cync session for user_id=%s", user.user_id)
        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.info("No usable saved token (%s) - logging in fresh", err)

        if not restored:
            try:
                user = await auth.login()
            except AuthFailedError as err:
                raise ConfigEntryAuthFailed(
                    f"Cync authentication failed: {err}"
                ) from err
            self._async_persist_token(user)
            _LOGGER.info("Authenticated with Cync as %s", self.username)

        self._auth = auth

        try:
            self._cync = await Cync.create(
                auth, ssl_context=_SSL_CONTEXT, ssl_context_no_verify=_SSL_CONTEXT
            )
        except AuthFailedError as err:
            # A saved token that the server has since invalidated. Try a fresh
            # username/password login once; if that also fails, ask the user to
            # reauthenticate via the HA UI.
            if restored:
                _LOGGER.info("Saved Cync token rejected - retrying fresh login")
                try:
                    user = await auth.login()
                except AuthFailedError as login_err:
                    raise ConfigEntryAuthFailed(
                        f"Cync credentials no longer valid: {login_err}"
                    ) from login_err
                self._async_persist_token(user)
                try:
                    self._cync = await Cync.create(
                        auth,
                        ssl_context=_SSL_CONTEXT,
                        ssl_context_no_verify=_SSL_CONTEXT,
                    )
                except Exception as err2:  # noqa: BLE001
                    raise UpdateFailed(
                        f"Could not connect to Cync cloud: {err2}"
                    ) from err2
            else:
                raise ConfigEntryAuthFailed(
                    f"Cync authentication failed: {err}"
                ) from err
        except Exception as err:
            raise UpdateFailed(f"Could not connect to Cync cloud: {err}") from err

        self._cync.set_update_callback(self._handle_state_update)
        _LOGGER.debug("Connected to Cync cloud; waiting for device probe")

        # pycync probes devices right after login; capabilities and state are
        # not reliably populated until that finishes.
        await asyncio.sleep(5)

        self._load_devices()
        self._last_push = time.monotonic()
        self._connected_at = time.monotonic()
        self._request_states()

        _LOGGER.info(
            "Cync connected - %d device(s) loaded (%d online)",
            len(self.devices),
            sum(1 for d in self.devices.values() if d.online),
        )

    async def _async_reconnect(self) -> None:
        """Tear down and rebuild the cloud connection."""
        if self._reconnecting:
            return
        self._reconnecting = True
        try:
            self._reconnect_count += 1
            self._last_reconnect_at = time.monotonic()
            _LOGGER.warning(
                "No state received from Cync in %ds - rebuilding connection "
                "(reconnect #%d)",
                STALE_PUSH_SECONDS,
                self._reconnect_count,
            )
            if self._cync is not None:
                try:
                    await self._cync.shut_down()
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("Error shutting down old Cync connection: %s", err)
                self._cync = None

            await self.async_connect()
            _LOGGER.info("Cync connection re-established")
        finally:
            self._reconnecting = False

    async def async_shutdown_connection(self) -> None:
        if self._cync:
            try:
                await self._cync.shut_down()
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Error during Cync shutdown: %s", err)

    # -- Periodic update -----------------------------------------------------

    async def _async_update_data(self) -> dict[int, CyncDeviceState]:
        """Poll: refresh the token if needed, then request fresh state.

        If the cloud has gone quiet for too long, rebuild the connection -
        pycync's own socket-level reconnect does not restore device state.
        """
        await self._async_maybe_refresh_token()

        silent_for = time.monotonic() - self._last_push
        if silent_for > STALE_PUSH_SECONDS:
            await self._async_reconnect()
        else:
            _LOGGER.debug(
                "Requesting Cync state refresh (last push %.0fs ago)", silent_for
            )
            self._request_states()

        return self.devices

    def _request_states(self) -> None:
        """Ask the cloud for a fresh state snapshot of all devices."""
        if self._cync is None:
            return
        try:
            self._cync.update_device_states()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to request Cync device states: %s", err)

    async def _async_maybe_refresh_token(self) -> None:
        """Refresh the access token when it is close to expiring."""
        if self._cync is None or self._auth is None:
            return
        user = self._auth.user
        if user is None:
            return
        if user.expires_at - time.time() > TOKEN_REFRESH_MARGIN:
            return

        try:
            refreshed = await self._cync.refresh_credentials()
        except AuthFailedError as err:
            raise ConfigEntryAuthFailed(
                f"Cync token refresh rejected: {err}"
            ) from err
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Cync token refresh failed: %s", err)
            return

        _LOGGER.info("Refreshed Cync access token")
        self._async_persist_token(refreshed or user)

    def _async_persist_token(self, user: User) -> None:
        """Save the current token back into the config entry."""
        new_data = {
            **self.entry.data,
            "access_token": user.access_token,
            "refresh_token": user.refresh_token,
            "authorize": user.authorize,
            "user_id": user.user_id,
            "expires_at": user.expires_at,
        }
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)

    # -- Device cache --------------------------------------------------------

    def _load_devices(self) -> None:
        """Build the HA-facing device cache from pycync's device list.

        Existing CyncDeviceState objects are updated in place where possible so
        that entities holding a reference keep working across a reconnect.
        """
        pycync_devices = self._cync.get_devices()
        seen: set[int] = set()

        for pd in pycync_devices:
            is_light = isinstance(pd, CyncLight)
            supports_bri = pd.supports_capability(CyncCapability.DIMMING)
            supports_ct = pd.supports_capability(CyncCapability.CCT_COLOR)
            supports_rgb = pd.supports_capability(CyncCapability.RGB_COLOR)

            is_fan = pd.device_type_id in FAN_TYPE_IDS
            is_plug = pd.device_type_id in PLUG_TYPE_IDS and not is_fan

            existing = self.devices.get(pd.device_id)
            if existing is not None:
                # Re-point at the new pycync object; keep the same state object
                # so entities don't see it vanish.
                existing.pycync_dev = pd
                existing.name = pd.name
                existing.online = pd.is_online
                if is_light:
                    existing.power = pd.is_on
                    existing.brightness = pd.brightness
            else:
                self.devices[pd.device_id] = CyncDeviceState(
                    pycync_dev=pd,
                    switch_id=pd.device_id,
                    name=pd.name,
                    device_type=pd.device_type_id,
                    is_plug=is_plug,
                    is_fan=is_fan,
                    supports_brightness=supports_bri,
                    supports_color_temp=supports_ct,
                    supports_rgb=supports_rgb,
                    online=pd.is_online,
                    power=pd.is_on if is_light else False,
                    brightness=pd.brightness if is_light else 0,
                )
            seen.add(pd.device_id)

        missing = set(self.devices) - seen
        if missing:
            # Don't delete - the entities still exist in HA. Mark them offline
            # so they read as unavailable rather than raising a lookup error.
            for dev_id in missing:
                self.devices[dev_id].online = False
            _LOGGER.warning(
                "Cync did not return %d previously-known device(s): %s",
                len(missing),
                ", ".join(self.devices[d].name for d in missing),
            )

    # -- State push from the cloud -------------------------------------------

    def _handle_state_update(self, updated: dict) -> None:
        """Callback fired by pycync whenever device state changes."""
        self._last_push = time.monotonic()
        changed_any = False

        for dev_id, pdev in updated.items():
            st = self.devices.get(dev_id)
            if st is None:
                continue

            is_light = isinstance(pdev, CyncLight)
            new_on = pdev.is_on if is_light else False
            new_bri = pdev.brightness if is_light else 0
            new_online = pdev.is_online

            if (
                st.online == new_online
                and st.power == new_on
                and st.brightness == new_bri
            ):
                continue

            # Accept confirmations of our own recent commands; reject stale
            # contradicting echoes that arrive within the same window.
            if time.time() - self._cmd_time.get(dev_id, 0) < 5.0:
                commanded = self._cmd_state.get(dev_id)
                if commanded is not None and new_on != commanded:
                    continue
                self._cmd_time.pop(dev_id, None)
                self._cmd_state.pop(dev_id, None)

            if st.online != new_online:
                _LOGGER.debug(
                    "%s is now %s", st.name, "online" if new_online else "offline"
                )

            now = time.monotonic()
            st.last_change = now
            if new_online:
                st.last_online = now

            st.online = new_online
            st.power = new_on
            st.brightness = new_bri
            if is_light:
                st.rgb = pdev.rgb
            changed_any = True

        if changed_any:
            self.async_set_updated_data(self.devices)

    def note_command(self, switch_id: int, on: bool) -> None:
        """Record that we just sent a command, to filter the echo window."""
        self._cmd_time[switch_id] = time.time()
        self._cmd_state[switch_id] = on

    # -- Diagnostics ---------------------------------------------------------

    def diagnostics_snapshot(self) -> dict:
        """Return a JSON-serializable snapshot of connection & device health.

        Consumed by diagnostics.py. All timestamps are seconds-ago relative to
        now (monotonic-based), which is what actually matters when diagnosing a
        device that has gone unavailable, and avoids leaking wall-clock/TZ data.
        """
        now = time.monotonic()

        def ago(ts: float) -> float | None:
            return round(now - ts, 1) if ts else None

        online = sum(1 for d in self.devices.values() if d.online)

        devices = []
        for st in self.devices.values():
            devices.append(
                {
                    "switch_id": st.switch_id,
                    "name": st.name,
                    "device_type": st.device_type,
                    "kind": "fan" if st.is_fan else "plug" if st.is_plug else "light",
                    "online": st.online,
                    "power": st.power,
                    "brightness": st.brightness,
                    "supports_brightness": st.supports_brightness,
                    "supports_color_temp": st.supports_color_temp,
                    "supports_rgb": st.supports_rgb,
                    "last_change_s_ago": ago(st.last_change),
                    "last_online_s_ago": ago(st.last_online),
                }
            )
        devices.sort(key=lambda d: (d["online"], d["name"]))

        return {
            "connection": {
                "connected": self._cync is not None,
                "reconnecting": self._reconnecting,
                "connected_s_ago": ago(self._connected_at),
                "last_cloud_push_s_ago": ago(self._last_push),
                "stale_threshold_s": STALE_PUSH_SECONDS,
                "is_stale": ago(self._last_push) is not None
                and (now - self._last_push) > STALE_PUSH_SECONDS,
                "reconnect_count": self._reconnect_count,
                "last_reconnect_s_ago": ago(self._last_reconnect_at),
                "poll_interval_s": self.update_interval.total_seconds()
                if self.update_interval
                else None,
                "last_update_success": self.last_update_success,
            },
            "summary": {
                "device_count": len(self.devices),
                "online_count": online,
                "offline_count": len(self.devices) - online,
                "offline_devices": [
                    d["name"] for d in devices if not d["online"]
                ],
            },
            "devices": devices,
        }
