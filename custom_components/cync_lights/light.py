"""Light platform for the Cync Lights integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MIN_MIREDS, MAX_MIREDS
from .coordinator import CyncCoordinator, CyncDeviceState
from .pycync.devices.devices import CyncLight


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Cync light entities from a config entry."""
    coordinator: CyncCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        CyncLightEntity(coordinator, switch_id)
        for switch_id, state in coordinator.devices.items()
        if not state.is_plug and not state.is_fan
    ]
    async_add_entities(entities)


class CyncLightEntity(CoordinatorEntity[CyncCoordinator], LightEntity):
    """Representation of a Cync light."""

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
            model="Cync Smart Light",
        )

        modes: set[ColorMode] = set()
        if state.supports_rgb:
            modes.add(ColorMode.RGB)
        if state.supports_color_temp:
            modes.add(ColorMode.COLOR_TEMP)
        if state.supports_brightness and not modes:
            modes.add(ColorMode.BRIGHTNESS)
        if not modes:
            modes.add(ColorMode.ONOFF)
        self._attr_supported_color_modes = modes

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
    def brightness(self) -> int | None:
        if not self._state.supports_brightness:
            return None
        return round(self._state.brightness * 255 / 100)

    @property
    def color_mode(self) -> ColorMode | None:
        modes = self._attr_supported_color_modes
        if ColorMode.RGB in modes:
            return ColorMode.RGB
        if ColorMode.COLOR_TEMP in modes:
            return ColorMode.COLOR_TEMP
        if ColorMode.BRIGHTNESS in modes:
            return ColorMode.BRIGHTNESS
        return ColorMode.ONOFF

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        return self._state.rgb if self._state.supports_rgb else None

    @property
    def min_color_temp_kelvin(self) -> int:
        return round(1_000_000 / MAX_MIREDS)

    @property
    def max_color_temp_kelvin(self) -> int:
        return round(1_000_000 / MIN_MIREDS)

    async def async_turn_on(self, **kwargs: Any) -> None:
        pd = self._state.pycync_dev
        self.coordinator.note_command(self._switch_id, True)

        is_light = isinstance(pd, CyncLight)
        command_client = getattr(pd, "_command_client", None)

        if ATTR_BRIGHTNESS in kwargs and self._state.supports_brightness and is_light:
            pct = max(1, min(100, round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)))
            await pd.set_brightness(pct)
        elif is_light:
            await pd.turn_on()
        elif command_client:
            # Plain ON/OFF devices (e.g. type 52 WiFi switches) come back from
            # pycync as a base CyncDevice, which has no turn_on()/turn_off().
            # Every device carries a reference to the command client though,
            # and set_power_state() accepts any CyncControllable.
            await command_client.set_power_state(pd, True)

        if ATTR_COLOR_TEMP_KELVIN in kwargs and self._state.supports_color_temp and is_light:
            mireds = round(1_000_000 / kwargs[ATTR_COLOR_TEMP_KELVIN])
            pct = max(1, min(100, round((MAX_MIREDS - mireds) / (MAX_MIREDS - MIN_MIREDS) * 100)))
            await pd.set_color_temp(pct)

        if ATTR_RGB_COLOR in kwargs and self._state.supports_rgb and is_light:
            await pd.set_rgb(tuple(kwargs[ATTR_RGB_COLOR]))

        self._state.power = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        pd = self._state.pycync_dev
        self.coordinator.note_command(self._switch_id, False)

        if isinstance(pd, CyncLight):
            await pd.turn_off()
        else:
            command_client = getattr(pd, "_command_client", None)
            if command_client:
                await command_client.set_power_state(pd, False)

        self._state.power = False
        self.async_write_ha_state()
