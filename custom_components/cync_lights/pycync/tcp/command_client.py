"""
The proverbial "beating heart" of the Cync client.
This client listens for device state changes and updates them accordingly, and also handles sending all device action commands.
"""

from __future__ import annotations

import ssl
from typing import TYPE_CHECKING

import asyncio
import logging

from .packet import MessageType, ParsedMessage, PipeCommandCode
from .tcp_manager import TcpManager
from ..devices.controllable import CyncControllable
from ..exceptions import NoHubConnectedError, CyncError
from ..devices.capabilities import CyncCapability
from ..devices import device_storage
from ..user import User

if TYPE_CHECKING:
    from pycync.devices import CyncDevice
    from pycync.devices.groups import CyncHome


# How long to wait for the initial device probe to report at least one
# Wi-Fi-connected device before giving up on a mesh state query. Without a
# bound here the query task waits forever - silently - when the Cync server
# accepts the login but never sends probe responses (e.g. a stale account
# session), which leaves every device stuck "unavailable" with nothing logged.
HUB_PROBE_TIMEOUT_SECONDS = 15


class CommandClient:
    _LOGGER = logging.getLogger(__name__)

    def __init__(self, user: User):
        self._user = user

        self._device_statuses_updated = False
        self._tcp_manager: TcpManager = None

        # Diagnostics counters: how many of each server message we've handled.
        # These distinguish "cloud never answers the state query" (all zero)
        # from "cloud answers but the reply can't be parsed" (parse errors on
        # the TcpManager) - the two remaining reasons devices stay unavailable
        # when the connection, probe, and hub all look healthy.
        self.status_responses = 0
        self.sync_pushes = 0
        self.probe_responses = 0

    @property
    def probe_completed(self) -> bool:
        """True once at least one device has answered the initial probe."""
        return self._device_statuses_updated

    @property
    def parse_error_count(self) -> int:
        """Count of server packets that failed to parse (from the TCP layer)."""
        return self._tcp_manager.parse_error_count if self._tcp_manager else 0

    @property
    def last_parse_error(self) -> str | None:
        """Message of the most recent packet parse failure, if any."""
        return self._tcp_manager.last_parse_error if self._tcp_manager else None

    @property
    def hub_available(self) -> bool:
        """True if any known device can currently act as a Wi-Fi mesh proxy.

        This is what a mesh state query needs; when it is False the account has
        no reachable bridge and every mesh device will read as unavailable.
        """
        return any(
            device.wifi_connected and CyncCapability.CAN_ACT_AS_WIFI_PROXY in device.capabilities
            for device in device_storage.get_flattened_devices(self._user.user_id)
        )

    def start_connection(self, ssl_context: ssl.SSLContext = None, ssl_context_no_verify: ssl.SSLContext = None):
        self._tcp_manager = TcpManager(self._user, self.on_message_received, ssl_context, ssl_context_no_verify)

    async def on_message_received(self, parsed_message: ParsedMessage):
        match parsed_message.message_type:
            case MessageType.LOGIN.value:
                await self.probe_devices()
            case MessageType.PROBE.value if parsed_message.version != 0:
                self.probe_responses += 1
                devices_in_home = device_storage.get_associated_home_devices(self._user.user_id,
                                                                             parsed_message.device_id)
                device = next(device for device in devices_in_home if device.device_id == parsed_message.device_id)
                device.set_wifi_connected(True)
                self._device_statuses_updated = True
            case MessageType.SYNC.value:
                self.sync_pushes += 1
                await self._send_update_to_listener(parsed_message.data)
            case MessageType.PIPE.value:
                if parsed_message.command_code == PipeCommandCode.QUERY_DEVICE_STATUS_PAGES.value:
                    self.status_responses += 1
                    updated_devices: dict[int, CyncDevice] = parsed_message.data
                    for device in device_storage.get_flattened_devices(self._user.user_id):
                        device.is_online = device.device_id in updated_devices
                    await self._send_update_to_listener(parsed_message.data)

    async def probe_devices(self):
        await self._tcp_manager.probe_devices(device_storage.get_flattened_devices(self._user.user_id))

    async def update_mesh_devices(self):
        """Get new device state."""
        homes_for_user = device_storage.get_user_homes(self._user.user_id)

        hub_devices: list[CyncDevice] = []
        for home in homes_for_user:
            hub_device = await self._fetch_hub_device(home)
            hub_devices.append(hub_device)

        await self._tcp_manager.update_mesh_devices(hub_devices)

    async def set_power_state(self, controllable: CyncControllable, is_on: bool):
        """Set device(s) to either on or off."""
        associated_home = device_storage.get_home_by_id(self._user.user_id, controllable.parent_home_id)
        hub_device = await self._fetch_hub_device(associated_home)

        await self._tcp_manager.set_power_state(hub_device, controllable.mesh_reference_id, is_on)

    async def set_brightness(self, controllable: CyncControllable, brightness: int):
        """Sets the brightness. Must be between 0 and 100 inclusive."""
        if brightness < 0 or brightness > 100:
            raise CyncError("Brightness must be between 0 and 100 inclusive")

        associated_home = device_storage.get_home_by_id(self._user.user_id, controllable.parent_home_id)
        hub_device = await self._fetch_hub_device(associated_home)

        await self._tcp_manager.set_brightness(hub_device, controllable.mesh_reference_id, brightness)

    async def set_color_temp(self, controllable: CyncControllable, color_temp: int):
        """
        Sets the color temperature. Must be between 1 and 100 inclusive.
        1 represents the most "blue" and 100 represents the most "orange".
        """
        if color_temp < 1 or color_temp > 100:
            raise CyncError("Color temperature must be between 1 and 100 inclusive.")

        associated_home = device_storage.get_home_by_id(self._user.user_id, controllable.parent_home_id)
        hub_device = await self._fetch_hub_device(associated_home)

        await self._tcp_manager.set_color_temp(hub_device, controllable.mesh_reference_id, color_temp)

    async def set_rgb(self, controllable: CyncControllable, rgb: tuple[int, int, int]):
        """Sets the RGB color. Each color must be between 0 and 255 inclusive."""
        if rgb[0] > 255 or rgb[1] > 255 or rgb[2] > 255:
            raise CyncError("Each RGB value must be between 0 and 255 inclusive")

        associated_home = device_storage.get_home_by_id(self._user.user_id, controllable.parent_home_id)
        hub_device = await self._fetch_hub_device(associated_home)

        await self._tcp_manager.set_rgb(hub_device, controllable.mesh_reference_id, rgb)

    async def shut_down(self):
        await self._tcp_manager.shut_down()

    async def _send_update_to_listener(self, updated_data: dict[int, CyncDevice]):
        callback = device_storage.get_user_device_callback(self._user.user_id)
        if callback is not None:
            if asyncio.iscoroutinefunction(callback):
                await callback(updated_data)
            else:
                callback(updated_data)

    async def _fetch_hub_device(self, home: CyncHome) -> CyncDevice:
        """
        Fetches an eligible 'hub device' from a given home.
        A hub device is a device that is actively connected to Wi-Fi, and can act as a proxy into the Bluetooth mesh.
        """

        waited = 0
        while not self._device_statuses_updated:
            if waited >= HUB_PROBE_TIMEOUT_SECONDS:
                raise NoHubConnectedError(
                    "No device answered the initial probe within "
                    f"{HUB_PROBE_TIMEOUT_SECONDS}s - the Cync server accepted the "
                    "login but is not reporting any online devices. This is "
                    "usually a stale Cync account session; re-authenticate the "
                    "official Cync app to refresh it.")
            await asyncio.sleep(1)
            waited += 1
            self._LOGGER.debug("Awaiting probe initialization before fetching hub.")

        hub_device = next((device for device in home.get_flattened_device_list() if
                           device.wifi_connected and CyncCapability.CAN_ACT_AS_WIFI_PROXY in device.capabilities), None)
        if hub_device is None:
            raise NoHubConnectedError(
                "No Wi-Fi-connected device in this home can act as a mesh proxy.")

        return hub_device
