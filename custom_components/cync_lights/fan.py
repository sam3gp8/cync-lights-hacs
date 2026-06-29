"""Fan platform for the Cync Lights integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from .const import DOMAIN
from .coordinator import CyncCoordinator, CyncDeviceState

SPEED_RANGE = (1, 100)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Cync fan entities from a config entry."""
    coordinator: CyncCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        CyncFanEntity(coordinator, switch_id)
        for switch_id, state in coordinator.devices.items()
        if state.is_fan
    ]
    async_add_entities(entities)


class CyncFanEntity(CoordinatorEntity[CyncCoordinator], FanEntity):
    """Representation of a Cync fan."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = FanEntityFeature.SET_SPEED

    def __init__(self, coordinator: CyncCoordinator, switch_id: int) -> None:
        super().__init__(coordinator)
        self._switch_id = switch_id

        state = self._state
        self._attr_unique_id = f"cync_{switch_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(switch_id))},
            name=state.name,
            manufacturer="GE / Savant",
            model="Cync Fan",
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

    @property
    def percentage(self) -> int | None:
        if not self._state.power:
            return 0
        return ranged_value_to_percentage(SPEED_RANGE, self._state.brightness or 1)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        pd = self._state.pycync_dev
        cc = getattr(pd, "_command_client", None)
        self.coordinator.note_command(self._switch_id, True)
        if cc:
            await cc.set_power_state(pd, True)
        self._state.power = True
        if percentage is not None:
            await self.async_set_percentage(percentage)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        pd = self._state.pycync_dev
        cc = getattr(pd, "_command_client", None)
        self.coordinator.note_command(self._switch_id, False)
        if cc:
            await cc.set_power_state(pd, False)
        self._state.power = False
        self.async_write_ha_state()

    async def async_set_percentage(self, percentage: int) -> None:
        pd = self._state.pycync_dev
        if percentage == 0:
            await self.async_turn_off()
            return
        speed = round(percentage_to_ranged_value(SPEED_RANGE, percentage))
        if hasattr(pd, "set_brightness"):
            await pd.set_brightness(speed)
        self._state.brightness = speed
        self._state.power = True
        self.async_write_ha_state()
