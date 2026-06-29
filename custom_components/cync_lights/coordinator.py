"""DataUpdateCoordinator for the Cync Lights integration.

Manages the pycync cloud connection, authentication/token refresh, and
keeps a live device-state cache that platform entities read from.
"""
from __future__ import annotations

import logging
import ssl
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    DEFAULT_SCAN_INTERVAL,
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


class CyncCoordinator(DataUpdateCoordinator[dict[int, CyncDeviceState]]):
    """Coordinates the pycync cloud connection for one Cync account."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,  # push-driven; we also poll on a timer below
        )
        self.entry = entry
        self.username: str = entry.data[CONF_USERNAME]
        self.password: str = entry.data[CONF_PASSWORD]

        self._cync: Optional[Cync] = None
        self.devices: dict[int, CyncDeviceState] = {}
        self._cmd_time: dict[int, float] = {}
        self._cmd_state: dict[int, bool] = {}

    async def async_connect(self) -> None:
        """Authenticate (using the stored token if possible) and connect."""
        session = async_get_clientsession(self.hass)
        auth = Auth(session, username=self.username, password=self.password)

        data = self.entry.data
        try:
            user = User(
                data["access_token"],
                data.get("refresh_token", ""),
                data["authorize"],
                int(data["user_id"]),
                expires_at=data.get("expires_at") or (time.time() + 604800),
            )
            auth._user = user  # noqa: SLF001 - restoring a saved session
        except (KeyError, AuthFailedError):
            user = await auth.login()
            self._async_persist_token(user)

        try:
            self._cync = await Cync.create(
                auth, ssl_context=_SSL_CONTEXT, ssl_context_no_verify=_SSL_CONTEXT
            )
        except Exception as err:
            raise UpdateFailed(f"Could not connect to Cync cloud: {err}") from err

        self._cync.set_update_callback(self._handle_state_update)

        # Probe takes a few seconds to populate device capabilities/state
        await self._async_wait_for_probe()
        self._load_devices()
        self._cync.update_device_states()

    def _async_persist_token(self, user: User) -> None:
        """Save the refreshed token back into the config entry."""
        new_data = {
            **self.entry.data,
            "access_token": user.access_token,
            "refresh_token": user.refresh_token,
            "authorize": user.authorize,
            "user_id": user.user_id,
            "expires_at": user.expires_at,
        }
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)

    async def _async_wait_for_probe(self) -> None:
        import asyncio

        await asyncio.sleep(5)

    def _load_devices(self) -> None:
        """Build the HA-facing device cache from pycync's device list."""
        pycync_devices = self._cync.get_devices()
        self.devices.clear()

        for pd in pycync_devices:
            is_light = isinstance(pd, CyncLight)
            supports_bri = pd.supports_capability(CyncCapability.DIMMING)
            supports_ct = pd.supports_capability(CyncCapability.CCT_COLOR)
            supports_rgb = pd.supports_capability(CyncCapability.RGB_COLOR)

            is_fan = pd.device_type_id in FAN_TYPE_IDS
            is_plug = pd.device_type_id in PLUG_TYPE_IDS and not is_fan

            state = CyncDeviceState(
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
            self.devices[pd.device_id] = state

        self.async_set_updated_data(self.devices)

    def _handle_state_update(self, updated: dict) -> None:
        """Callback fired by pycync whenever device state changes."""
        for dev_id, pdev in updated.items():
            st = self.devices.get(dev_id)
            if st is None:
                continue

            is_light = isinstance(pdev, CyncLight)
            new_on = pdev.is_on if is_light else False
            new_bri = pdev.brightness if is_light else 0
            new_online = pdev.is_online

            changed = (
                st.online != new_online
                or st.power != new_on
                or st.brightness != new_bri
            )
            if not changed:
                continue

            # Accept confirmations of our own recent commands; reject stale
            # contradicting echoes that arrive within the same window.
            if time.time() - self._cmd_time.get(dev_id, 0) < 5.0:
                commanded = self._cmd_state.get(dev_id)
                if commanded is not None and new_on != commanded:
                    continue
                self._cmd_time.pop(dev_id, None)
                self._cmd_state.pop(dev_id, None)

            st.online = new_online
            st.power = new_on
            st.brightness = new_bri
            if is_light:
                st.rgb = pdev.rgb

        self.async_set_updated_data(self.devices)

    def note_command(self, switch_id: int, on: bool) -> None:
        """Record that we just sent a command, to filter the echo window."""
        self._cmd_time[switch_id] = time.time()
        self._cmd_state[switch_id] = on

    async def async_refresh_states(self) -> None:
        """Ask the cloud for a fresh state snapshot of all devices."""
        if self._cync:
            self._cync.update_device_states()

    async def async_shutdown_connection(self) -> None:
        if self._cync:
            await self._cync.shut_down()
