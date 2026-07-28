"""Diagnostics support for the Cync Lights integration.

Home Assistant exposes a "Download diagnostics" button on the integration's
device and config-entry pages (Settings -> Devices & Services -> Cync Lights
-> the three-dot menu). This module produces the JSON that button downloads.

The goal here is specifically to make "some devices became unavailable"
debuggable after the fact: the dump captures connection health (when the
cloud last pushed anything, whether the connection is considered stale,
reconnect count) and per-device online/offline status with timestamps.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .const import DOMAIN
from .coordinator import CyncCoordinator

# Never include credentials or tokens in a downloadable diagnostics file.
TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    "access_token",
    "refresh_token",
    "authorize",
    "user_id",
    "title",
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the whole config entry."""
    coordinator: CyncCoordinator = hass.data[DOMAIN][entry.entry_id]

    return {
        "entry": {
            "title": entry.title,
            "version": entry.version,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
        },
        "cync": coordinator.diagnostics_snapshot(),
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics scoped to a single device.

    Useful when one specific light keeps going unavailable — download from
    that device's page to get just its record plus overall connection health.
    """
    coordinator: CyncCoordinator = hass.data[DOMAIN][entry.entry_id]
    snapshot = coordinator.diagnostics_snapshot()

    # The device's Cync switch_id is the identifier we registered it with.
    switch_ids = {
        ident[1] for ident in device.identifiers if ident[0] == DOMAIN
    }
    device_records = [
        d for d in snapshot["devices"] if str(d["switch_id"]) in switch_ids
    ]

    return {
        "device": {
            "name": device.name,
            "identifiers": [list(i) for i in device.identifiers],
        },
        "records": device_records,
        "connection": snapshot["connection"],
    }
