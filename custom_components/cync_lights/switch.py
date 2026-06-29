"""Switch platform for the Cync Lights integration (plug-type devices)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CyncCoordinator, CyncDeviceState


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Cync switch entities (plugs) from a config entry."""
    coordinator: CyncCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        CyncSwitchEntity(coordinator, switch_id)
        for switch_id, state in coordinator.devices.items()
        if state.is_plug
    ]
    async_add_entities(entities)


class CyncSwitchEntity(CoordinatorEntity[CyncCoordinator], SwitchEntity):
    """Representation of a Cync plug/switch."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator: CyncCoordinator, switch_id: int) -> None:
        super().__init__(coordinator)
        self._switch_id = switch_id

        state = self._state
        self._attr_unique_id = f"cync_{switch_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(switch_id))},
            name=state.name,
            manufacturer="GE / Savant",
            model="Cync Smart Plug",
        )

    @property
    def _state(self) -> CyncDeviceState:
        return self.coordinator.devices[self._switch_id]

    @property
    def name(self) -> str | None:
        return self._state.name

    @property
    def is_on(self) -> bool:
        return self._state.online and self._state.power

    @property
    def available(self) -> bool:
        return self._state.online

    async def async_turn_on(self, **kwargs: Any) -> None:
        pd = self._state.pycync_dev
        cc = getattr(pd, "_command_client", None)
        self.coordinator.note_command(self._switch_id, True)
        if cc:
            await cc.set_power_state(pd, True)
        self._state.power = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        pd = self._state.pycync_dev
        cc = getattr(pd, "_command_client", None)
        self.coordinator.note_command(self._switch_id, False)
        if cc:
            await cc.set_power_state(pd, False)
        self._state.power = False
        self.async_write_ha_state()
